import csv
import io
import json

from yinju.audit import AuditReport, CitationCheck, ClaimCheck
from yinju.claims import Claim
from yinju.report import report_to_csv, report_to_dict, report_to_markdown, write_reports
from yinju.store import HybridHit, PaperRecord
from yinju.verdicts import Evidence


def _paper(key: str) -> PaperRecord:
    return PaperRecord(
        paper_key=key,
        title="Attention Is All You Need",
        authors="Vaswani et al.",
        year=2017,
        source_url="https://arxiv.org/abs/1706.03762",
        file_name="paper.pdf",
        file_sha256="a" * 64,
        page_count=15,
        para_count=67,
        sent_count=315,
        unit_mode="para+sent",
        ingested_at="2026-10-26T00:00:00Z",
    )


def _report() -> AuditReport:
    claim = Claim(
        claim_id="claim-01",
        line_start=3,
        line_end=3,
        text="The Transformer relies on attention.",
        citations=("vaswani2017",),
    )
    evidence = Evidence(
        unit_id="vaswani2017:p1:sent2",
        paper_key="vaswani2017",
        page=1,
        unit_type="sent",
        parent_id="vaswani2017:p1:para1",
        text="The Transformer is based solely on attention mechanisms.",
        score=0.82,
        cosine=0.81,
        keyword_coverage=0.75,
        number_status="none",
    )
    hit = HybridHit(
        unit_id="vaswani2017:p1:para1",
        paper_key="vaswani2017",
        page=1,
        unit_type="para",
        text="paragraph",
        parent_id="",
        rrf_score=0.0325,
        fulltext_rank=1,
        vector_rank=2,
        fulltext_score=3.5,
        vector_distance=0.19,
    )
    check = CitationCheck(
        citation="vaswani2017",
        paper=_paper("vaswani2017"),
        verdict="partial",
        confidence="high",
        review_required=True,
        reason="证据高度吻合，但 verifier=none 不出具 supported 结论",
        evidence=evidence,
        keywords=("transformer", "relies", "attention"),
        number_status="none",
        paragraph_hits=(hit,),
        sentence_candidates=(evidence,),
        seconds=0.12,
    )
    failed = CitationCheck(
        citation="devlin2019",
        paper=_paper("devlin2019"),
        verdict="unknown",
        confidence="low",
        review_required=True,
        reason="核对失败：检索不可用",
        evidence=None,
        keywords=(),
        number_status="none",
        paragraph_hits=(),
        sentence_candidates=(),
        seconds=0.01,
        error="RuntimeError: boom",
    )
    return AuditReport(
        run_id="20261026T120000000000Z",
        generated_at="2026-10-26T12:00:00+00:00",
        draft_path="data/samples/draft.md",
        bib_path="data/samples/bib.json",
        verifier="none/baseline",
        embedding_model="default|all-MiniLM-L6-v2",
        claims=(
            ClaimCheck(claim=claim, checks=(check, failed), verdict="unknown", seconds=0.2),
        ),
        warnings=("verifier=none：需人工确认。",),
    )


def test_report_dict_has_summary_and_evidence() -> None:
    payload = report_to_dict(_report())
    assert payload["summary"]["citations"] == 2
    assert payload["summary"]["citation_verdicts"]["partial"] == 1
    assert payload["claims"][0]["checks"][0]["evidence"]["unit_id"] == "vaswani2017:p1:sent2"
    assert payload["claims"][0]["checks"][0]["paragraph_hits"][0]["rrf_score"] == 0.0325
    assert payload["claims"][0]["checks"][1]["error"] == "RuntimeError: boom"
    json.dumps(payload)


def test_report_markdown_contains_quotes_pages_and_audit() -> None:
    markdown = report_to_markdown(_report())
    assert "# 引用核对报告" in markdown
    assert "verifier=none" in markdown
    assert "> The Transformer is based solely on attention mechanisms." in markdown
    assert "vaswani2017:p1:sent2" in markdown
    assert "| 1 | `vaswani2017:p1:para1` | 1 | 0.0325 | 1 | 2 |" in markdown
    assert "证据：无" in markdown
    assert "RuntimeError: boom" in markdown


def test_report_csv_is_one_row_per_citation() -> None:
    rows = list(csv.DictReader(io.StringIO(report_to_csv(_report()))))
    assert len(rows) == 2
    assert rows[0]["evidence_id"] == "vaswani2017:p1:sent2"
    assert rows[0]["page"] == "1"
    assert rows[0]["review_required"] == "yes"
    assert "attention mechanisms" in rows[0]["quote"]
    assert rows[1]["evidence_id"] == ""
    assert rows[1]["error"] == "RuntimeError: boom"


def test_write_reports_creates_three_files(tmp_path) -> None:
    paths = write_reports(_report(), tmp_path)
    assert {path.name for path in paths.values()} == {"report.md", "report.csv", "report.json"}
    assert all(path.is_file() for path in paths.values())
    assert paths["markdown"].parent.name == "20261026T120000000000Z-draft"
    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert payload["run_id"] == "20261026T120000000000Z"
    assert paths["csv"].read_bytes().startswith(b"\xef\xbb\xbf")
    assert paths["markdown"].read_text(encoding="utf-8").endswith("\n")
