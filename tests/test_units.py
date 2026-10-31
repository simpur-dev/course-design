import pytest

from yinju.units import (
    MAX_PARAGRAPH_CHARS,
    UNIT_PARA,
    UNIT_SENT,
    PdfParseError,
    file_sha256,
    normalize_page_text,
    parse_pdf,
    split_sentences,
    units_from_pages,
)


def test_normalize_page_text_joins_lines_and_dehyphenates() -> None:
    raw = "atten-\ntion\u00a0works\r\n\r\nwell  today\x0c"
    assert normalize_page_text(raw) == "attention works well today"


def test_split_sentences_keeps_abbreviations_and_decimals() -> None:
    text = (
        "We pre-train on 3.3 billion tokens, e.g. from Wikipedia. "
        "Results improve (see Fig. 2). Next we fine-tune BERT."
    )
    assert split_sentences(text) == [
        "We pre-train on 3.3 billion tokens, e.g. from Wikipedia.",
        "Results improve (see Fig. 2).",
        "Next we fine-tune BERT.",
    ]


def test_units_from_pages_links_sentences_to_paragraphs() -> None:
    first = "The Transformer relies entirely on attention mechanisms and dispenses with recurrence."
    short = "Short."
    second = "This sentence is also long enough to become a standalone evidence unit."
    units = units_from_pages([f"{first} {short} {second}"], "paper")

    paras = [unit for unit in units if unit.unit_type == UNIT_PARA]
    sents = [unit for unit in units if unit.unit_type == UNIT_SENT]
    assert len(paras) == 1
    assert len(sents) == 2
    assert short in paras[0].text
    assert [unit.unit_id for unit in sents] == ["paper:p1:sent1", "paper:p1:sent3"]
    assert all(unit.parent_id == paras[0].unit_id for unit in sents)
    assert paras[0].to_metadata() == {
        "paper_key": "paper",
        "page": 1,
        "unit_type": UNIT_PARA,
        "unit_index": 1,
        "parent_id": "",
    }


def test_units_from_pages_splits_long_pages_into_paragraph_blocks() -> None:
    sentences = [
        f"Sentence {number:02d} carries enough words to remain a useful evidence unit in this test."
        for number in range(1, 25)
    ]
    units = units_from_pages([" ".join(sentences)], "paper")
    paras = [unit for unit in units if unit.unit_type == UNIT_PARA]
    sents = [unit for unit in units if unit.unit_type == UNIT_SENT]
    assert len(paras) > 1
    assert all(len(unit.text) <= MAX_PARAGRAPH_CHARS for unit in paras)
    para_ids = {unit.unit_id for unit in paras}
    assert {unit.parent_id for unit in sents} <= para_ids
    assert " ".join(unit.text for unit in paras) == " ".join(sentences)


def test_units_from_pages_uses_one_based_page_anchors() -> None:
    pages = [
        "The first page contains a sentence that is long enough to be indexed.",
        "The second page contains another sentence that is long enough to be indexed.",
    ]
    units = units_from_pages(pages, "paper")
    assert {unit.page for unit in units} == {1, 2}
    assert any(unit.unit_id.startswith("paper:p2:") for unit in units)


def test_parse_pdf_extracts_two_pages(tmp_path, make_pdf) -> None:
    path = tmp_path / "sample.pdf"
    make_pdf(
        path,
        [
            "The Transformer relies entirely on attention mechanisms and dispenses with recurrence.",
            "BERT uses a bidirectional Transformer encoder and masked language modeling.",
        ],
    )
    parsed = parse_pdf(path, "sample")
    assert parsed.page_count == 2
    assert parsed.para_count == 2
    assert parsed.sent_count == 2
    assert {unit.page for unit in parsed.units} == {1, 2}
    assert "attention mechanisms" in " ".join(unit.text for unit in parsed.units)


def test_parse_pdf_rejects_scanned_pdf(tmp_path, make_pdf) -> None:
    path = tmp_path / "blank.pdf"
    make_pdf(path, ["", ""])
    with pytest.raises(PdfParseError, match="no extractable text"):
        parse_pdf(path, "blank")


def test_parse_pdf_reports_missing_file(tmp_path) -> None:
    with pytest.raises(PdfParseError, match="cannot open"):
        parse_pdf(tmp_path / "missing.pdf", "missing")


def test_file_sha256_matches_known_digest(tmp_path) -> None:
    path = tmp_path / "abc.txt"
    path.write_bytes(b"abc")
    assert file_sha256(path) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
