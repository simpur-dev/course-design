import json

import pytest

from backend.evidence.bibliography import BibliographyError, load_bibliography


def _write(path, payload) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_loads_simple_and_rich_entries(tmp_path) -> None:
    papers = tmp_path / "papers"
    papers.mkdir()
    (papers / "a.pdf").write_bytes(b"%PDF")
    (papers / "z.pdf").write_bytes(b"%PDF")
    path = tmp_path / "bib.json"
    _write(
        path,
        {
            "zeta": "papers/z.pdf",
            "alpha": {
                "file": "papers/a.pdf",
                "title": "A Paper",
                "authors": "A. Author",
                "year": 2020,
                "source_url": "https://example.org/a",
            },
        },
    )

    refs = load_bibliography(path)
    assert list(refs) == ["alpha", "zeta"]
    assert refs["alpha"].file == (papers / "a.pdf").resolve()
    assert refs["alpha"].title == "A Paper"
    assert refs["alpha"].year == 2020
    assert refs["zeta"].title == ""


def test_rejects_missing_pdf(tmp_path) -> None:
    path = tmp_path / "bib.json"
    _write(path, {"alpha": "papers/missing.pdf"})
    with pytest.raises(BibliographyError, match="not found"):
        load_bibliography(path)


def test_rejects_unsupported_key(tmp_path) -> None:
    (tmp_path / "a.pdf").write_bytes(b"%PDF")
    path = tmp_path / "bib.json"
    _write(path, {"bad key": "a.pdf"})
    with pytest.raises(BibliographyError, match="invalid paper key"):
        load_bibliography(path)


def test_rejects_non_pdf_file(tmp_path) -> None:
    (tmp_path / "a.txt").write_text("text", encoding="utf-8")
    path = tmp_path / "bib.json"
    _write(path, {"alpha": "a.txt"})
    with pytest.raises(BibliographyError, match="not a PDF"):
        load_bibliography(path)


def test_rejects_duplicate_json_keys(tmp_path) -> None:
    (tmp_path / "a.pdf").write_bytes(b"%PDF")
    path = tmp_path / "bib.json"
    path.write_text('{"alpha": "a.pdf", "alpha": "a.pdf"}', encoding="utf-8")
    with pytest.raises(BibliographyError, match="duplicate key"):
        load_bibliography(path)


def test_rejects_invalid_year_and_missing_file_field(tmp_path) -> None:
    (tmp_path / "a.pdf").write_bytes(b"%PDF")
    path = tmp_path / "bib.json"
    _write(path, {"alpha": {"file": "a.pdf", "year": True}})
    with pytest.raises(BibliographyError, match="year"):
        load_bibliography(path)

    _write(path, {"alpha": {"title": "no file"}})
    with pytest.raises(BibliographyError, match="missing 'file'"):
        load_bibliography(path)


def test_rejects_empty_or_non_object_root(tmp_path) -> None:
    path = tmp_path / "bib.json"
    _write(path, [])
    with pytest.raises(BibliographyError, match="non-empty object"):
        load_bibliography(path)
