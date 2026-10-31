from pathlib import Path

import pytest

from backend.audit.claims import DraftError, parse_draft


def _draft(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "draft.md"
    path.write_text(text, encoding="utf-8")
    return path


def test_parses_multiline_claim_and_keeps_line_numbers(tmp_path) -> None:
    path = _draft(
        tmp_path,
        "# Draft\n"
        "\n"
        "The Transformer relies on attention and removes recurrence\n"
        "and convolutions entirely [@vaswani2017].\n"
        "\n"
        "BERT uses masked language modeling [@devlin2019; @vaswani2017].\n",
    )
    claims = parse_draft(path)
    assert [claim.claim_id for claim in claims] == ["claim-01", "claim-02"]
    assert claims[0].text == (
        "The Transformer relies on attention and removes recurrence and convolutions entirely."
    )
    assert (claims[0].line_start, claims[0].line_end) == (3, 4)
    assert claims[0].citations == ("vaswani2017",)
    assert claims[1].citations == ("devlin2019", "vaswani2017")


def test_supports_list_and_blockquote_markers(tmp_path) -> None:
    path = _draft(
        tmp_path,
        "- A list claim about dense retrieval [@alpha]\n"
        "> A quoted claim about sparse retrieval [@beta]\n",
    )
    claims = parse_draft(path)
    assert claims[0].text == "A list claim about dense retrieval"
    assert claims[1].text == "A quoted claim about sparse retrieval"


def test_skips_fenced_code_and_headings(tmp_path) -> None:
    path = _draft(
        tmp_path,
        "```text\n"
        "Ignored [@alpha]\n"
        "```\n"
        "## Heading [@beta]\n"
        "Kept claim with enough text [@gamma]\n",
    )
    claims = parse_draft(path)
    assert len(claims) == 1
    assert claims[0].citations == ("gamma",)


def test_deduplicates_repeated_citations(tmp_path) -> None:
    path = _draft(tmp_path, "Claim with repeated citations [@alpha; @alpha]\n")
    assert parse_draft(path)[0].citations == ("alpha",)


def test_rejects_unsupported_citation_syntax(tmp_path) -> None:
    path = _draft(tmp_path, "A claim with a locator [see @alpha, p. 3]\n")
    with pytest.raises(DraftError, match="unsupported citation"):
        parse_draft(path)


def test_rejects_citation_only_block(tmp_path) -> None:
    path = _draft(tmp_path, "[@alpha]\n")
    with pytest.raises(DraftError, match="too short"):
        parse_draft(path)


def test_rejects_draft_without_citations(tmp_path) -> None:
    path = _draft(tmp_path, "# Notes\n\nA claim without any citation.\n")
    with pytest.raises(DraftError, match="no claims"):
        parse_draft(path)


def test_missing_file_reports_error(tmp_path) -> None:
    with pytest.raises(DraftError, match="cannot read"):
        parse_draft(tmp_path / "missing.md")
