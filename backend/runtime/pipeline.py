from __future__ import annotations

from typing import Any

from ..audit import ProgressCallback
from ..core import Settings
from ..evidence import ingest_paper
from .jobs import IngestSpec
from .providers import build_embedder, open_cache, open_store


def run_ingest(settings: Settings, spec: IngestSpec, progress: ProgressCallback) -> dict[str, Any]:
    progress({"stage": "ingest", "done": 0, "total": 1, "message": "正在解析 PDF"})
    embedder = build_embedder(settings)
    store = open_store(settings, embedder)
    cache = open_cache(settings, embedder)

    def on_progress(done: int, total: int) -> None:
        progress(
            {
                "stage": "ingest",
                "done": done,
                "total": total,
                "message": f"正在生成向量 {done}/{total} 批",
            }
        )

    return ingest_paper(spec.ref, store, cache, on_progress=on_progress).to_dict()
