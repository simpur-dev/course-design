# Third-party notices

## Sample papers

The files under `data/samples/papers/` are unmodified PDFs retrieved on 2026-10-26 and are used only as local test inputs. Their license terms are those stated by the respective publishers.

| File | Work | Authors | Source |
| --- | --- | --- | --- |
| `1706.03762.pdf` | Attention Is All You Need | Ashish Vaswani et al. | <https://arxiv.org/abs/1706.03762> |
| `1810.04805.pdf` | BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding | Jacob Devlin et al. | <https://arxiv.org/abs/1810.04805> |
| `photon-sigmod2022.pdf` | Photon: A Fast Query Engine for Lakehouse Systems (SIGMOD '22) | Alexander Behm et al. | <https://doi.org/10.1145/3514221.3526054> |

`data/samples/draft.md` is an original test draft written for this project; its claims are deliberately simple and cite the two NLP papers above. `data/samples/photon-demo.md` is an original database-systems demo draft; it cites only the Photon paper and includes one deliberately incorrect benchmark-capacity claim to exercise the unsupported verdict.

`data/samples/labels.json` is an original evaluation annotation set created for this project. Its claims are paraphrases of, or deliberate misattributions against, the two sample papers; evidence page numbers and unit ids refer to text extracted from those PDFs.

## Software

- [PowerContext](https://github.com/oceanbase/powercontext) 1.4.0, used as an installed service via its public HTTP API.
- [seekdb](https://github.com/oceanbase/seekdb) 1.4.0.0 container image, used as the evidence store.
- [PyMuPDF](https://pymupdf.readthedocs.io/) for PDF text extraction.
- [pyseekdb](https://pypi.org/project/pyseekdb/) for the seekdb collection API and local ONNX embeddings.
- [all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) (Apache-2.0) for local sentence embeddings; the model is downloaded by pyseekdb on first ingest and is not redistributed in this repository.

The React/Vite frontend, FastAPI backend and their transitive dependencies are installed from their published packages; no third-party source files are vendored.

No third-party source code has been copied into this repository; dependencies are installed from their published packages.
