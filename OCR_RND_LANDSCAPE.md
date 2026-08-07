# R&D: What's Available to Extract Text — Full Landscape Survey
## Free / open-source / locally-runnable only

**Date:** 2026-07-30
**Companion to:** [OCR_ACCURACY_PLAN.md](OCR_ACCURACY_PLAN.md)
**Target hardware:** RTX 3050 Laptop 6 GB VRAM · Ryzen 5 7235HS 4-core · 11.7 GB RAM

---

## 0. Headline finding — this changes the plan

**PaddleOCR-VL-0.9B beats GPT-4o, Gemini 2.5 Pro, and Qwen3-VL-235B on document parsing, and it runs in ~2.5 GB of VRAM.**

That fits your existing 6 GB laptop GPU with room to spare. My earlier plan said a GPU upgrade was near-mandatory for a usable VLM stage. **That is now wrong, and I'm correcting it.**

Where the confusion came from: the PaddleOCR-VL paper reports "avg. VRAM usage 43.7 GB." That figure is a **high-throughput vLLM batch configuration on an A100 processing 512 PDFs** — vLLM pre-allocates a huge KV cache by design. It is not a floor. Independent measurements of single-image inference put it at **~2–4 GB at FP16 (~2.5 GB typical), and ~0.5 GB at INT4.**

| Config | VRAM | Runs on your 3050 6 GB? |
|---|---|---|
| PaddleOCR-VL-0.9B FP16, single image | **~2.5 GB** | ✅ comfortably |
| PaddleOCR-VL-1.6 INT4 | **~0.5 GB** | ✅ trivially |
| PaddleOCR-VL, vLLM high-throughput batch | 43.7 GB | ❌ (not needed) |

**Revised hardware position:** you can run a SOTA document-parsing VLM *today*, on this laptop, for free. The GPU upgrade drops from "needed for the VLM stage" to "worth it for comfortable fine-tuning and higher throughput." That is a much better place to be.

---

## 1. The category the plan completely missed: documents that need no OCR at all

**Check for an existing text layer before running any OCR.** A digital-born PDF (exported from Word, a government e-filing system, an accounting package) already contains the text as data. Extracting it is:

- **100% accurate** — it's the original text, not a recognition guess
- **Instant** — milliseconds vs your current 77 s/page
- **Free** — no model, no GPU

Your pipeline currently OCRs *everything* unconditionally, so any digital-born PDF in the corpus is being needlessly degraded from perfect text into ~15%-WRR Tesseract output. **This is free accuracy you're throwing away.**

### Detection (reliable, two-signal test)

```python
import fitz  # PyMuPDF

def needs_ocr(page) -> bool:
    """True if the page is a scan (image, no text layer)."""
    has_text   = bool(page.get_text().strip())
    has_images = bool(page.get_images())
    return (not has_text) and has_images
```

Route per **page**, not per document — mixed PDFs (typed pages + scanned annexures) are extremely common in government filings, which is exactly your document type.

### Tools

| Tool | Licence | Role | Notes |
|---|---|---|---|
| **PyMuPDF** (`fitz`) | AGPL ⚠️ | text layer + image extraction | **Substantially faster** than pdfminer/pdfplumber. **AGPL — check licence for commercial use.** Already installed in your venv. |
| **pdfplumber** | MIT ✅ | text + **tables** + char-level positions | Built on pdfminer.six. Best for table extraction and precise positioning. Safe licence. |
| **pdftotext** (Poppler) | GPL ⚠️ | fast CLI text dump | `-layout` preserves columns. |
| **pypdf** | BSD ✅ | basic text | Simplest, weakest layout handling. |
| **Camelot / Tabula** | MIT / MIT ✅ | tables from digital PDFs | Only works on text-layer PDFs, not scans. |

**Recommended:** pdfplumber (MIT, tables, safe licence) as primary; PyMuPDF for speed if AGPL is acceptable.

**Also note:** `ocrmypdf` already has `--skip-text` / `--redo-ocr` flags for exactly this. You're calling it with `force_ocr=True` at [main.py:198](ocr/main.py#L198), which **forcibly discards any existing text layer.** Changing that one flag is a one-line accuracy win.

---

## 2. Document-parsing VLMs (the current state of the art)

These treat a page as one multimodal task: image in → structured markdown/JSON/HTML out, including layout, reading order, and tables. This is where the field has moved.

| Model | Size | OmniDocBench | VRAM (single-image) | Licence | 6 GB? | Verdict |
|---|---|---|---|---|---|---|
| **PaddleOCR-VL-1.6** | **0.9B** | **96.33** (v1.6, vendor) | **~2.5 GB** FP16 / ~0.5 GB INT4 | Apache 2.0 ✅ | ✅ | **Top pick.** SOTA + tiny + safe licence + fine-tunable |
| **PaddleOCR-VL-1.5** | 0.9B | 92.56 (v1.5, paper) | ~2.5 GB | Apache 2.0 ✅ | ✅ | stable predecessor |
| **MinerU2.5-Pro** | 1.2B | 95.69 (v1.6, vendor) | low | AGPL ⚠️ | ✅ | strong; **check licence** |
| **dots.ocr** | 3B | 88.41 | 16+ GB FP16 / **~4.2 GB GGUF Q8** | open ✅ | ⚠️ quantized only | "structure SOTA", full markdown+tables |
| **Granite-Docling** | ~250M–2B | — | low | Apache 2.0 ✅ | ✅ | IBM. TableFormer-trained → **strong on legal/financial tables** |
| **GLM-OCR** | 0.9B | — | low | open ✅ | ✅ | direct PaddleOCR-VL competitor, newer |
| **DeepSeek-OCR** | 3B | — | ~13 GB w/ activations | open ✅ | ❌ | needs GPU upgrade |
| **olmOCR-2-7B** | 7B | **82.4** (olmOCR-Bench) | 12 GB rec / **~5.5 GB Q4_K_M** | Apache 2.0 ✅ | ⚠️ quantized | AllenAI. **ENGLISH-ONLY BY DESIGN** — see assessment below |
| **Qwen2.5-VL / Qwen3-VL** | 3B/7B/72B | — | 3B ~3 GB, 7B ~6 GB @4-bit | Apache 2.0 ✅ | 3B ✅ | best general reasoning; good handwriting |
| **GOT-OCR 2.0** | 580M | — | ~2 GB | open ✅ | ✅ | very light, weaker layout |
| **Nanonets-OCR-s** | 3B | — | ~4 GB @4-bit | open ✅ | ⚠️ | markdown-focused |

**PaddleOCR-VL architecture** (worth knowing, because it maps onto the plan's stages):
- **PP-DocLayoutV2** — RT-DETR layout detection **+ a pointer network that predicts reading order.** This is Stage 1 and directly fixes **C6** (no table model) and the reading-order half of the alignment problem.
- **NaViT-style dynamic high-resolution vision encoder** + ERNIE-4.5-0.3B language model, joined by a 2-layer MLP projector.
- **Table TEDS 0.9195** — genuinely good table structure recognition.
- **109 languages.**
- Throughput: 1.22 pages/sec on A100 (expect far slower on a 3050, but workable).

### olmOCR 2 (AllenAI) — assessed on request

**What it is:** `olmOCR-2-7B-1025-FP8` (v0.4.0, Oct 2025), a fine-tune of **Qwen2.5-VL-7B**. Apache 2.0. Outputs Markdown (+ Dolma format), auto-strips headers/footers, handles reading order. Available via Ollama (`richardyoung/olmocr2`) and LM Studio. Claims **< $200 per million pages** on local GPU. Needs ~30 GB disk (Docker image ~30 GB).

**olmOCR-Bench v0.4.0 breakdown (82.4 ± 1.1 overall, 7,000+ cases):**

| Category | Score |
|---|---|
| Headers / footers | 96.1 |
| Tables | 84.9 |
| Tiny text | 83.7 |
| ArXiv documents | 83.0 |
| Old scans with math | 82.3 |
| **Multi-column layouts** | **47.7** ⚠️ |

**Verdict: DISQUALIFIED for the Kannada path — explicitly, not by inference.**

> The authors **deliberately excluded non-English text from the training dataset, and the benchmark is English-only.** The repo describes "basic filtering to English PDFs." Their own framing: "fine-tuned on English documents using a multilingual base VLM; other languages may work."

This is a stated design decision, unlike OpenDataLoader where weak Indic support was inferred from a documentation gap. No Indic or Kannada support is claimed anywhere.

**Correction to an earlier claim in this document:** I first marked olmOCR ❌ for 6 GB. That was wrong — **at Q4_K_M it runs in ~5.5 GB** (12 GB is the *recommended* figure, tested on 4090/L40S/A100/H100). The blocker is language, not memory.

**Useful corollary — prefer the base model over the fine-tune for Kannada.** olmOCR's base is Qwen2.5-VL-7B, which *is* multilingual. Fine-tuning on English-only data may have **degraded** its Indic ability. So if you want a 7B Qwen-family VLM for Kannada, use **plain Qwen2.5-VL-7B**, not olmOCR.

**Where it earns a place:** if your corpus has a meaningful **English-only subset** (English annexures, correspondence, typed filings), olmOCR 2 is arguably the best open-source choice for those pages specifically, and the automatic header/footer removal is a genuine convenience. Note the 47.7 multi-column score makes it a poor fit for column-heavy pages even in English.

**Benchmark caveat:** olmOCR-Bench has published critique — see [LlamaIndex's "OlmOCR-Bench Review: Insights and Pitfalls"](https://www.llamaindex.ai/blog/olmocr-bench-review-insights-and-pitfalls-on-an-ocr-benchmark). Note also that olmOCR (82.4) is scored on *its own* English-only benchmark, where PaddleOCR-VL scores 80.0 — that comparison says nothing about Kannada.

---

### ⚠️ The one open question on PaddleOCR-VL: is Kannada in the 109?

**Not confirmed.** The paper's evaluation names **Telugu (0.011 edit distance — excellent)** and **Devanagari (0.097)**, but does not list Kannada explicitly. The full language table is in the paper appendix; there's an open HuggingFace discussion asking for the list.

Telugu at 0.011 is a strong signal — Telugu and Kannada are closely related Dravidian scripts with similar conjunct structure and share many glyph forms. But **this must be verified empirically on your own Kannada pages in Phase 1.** Do not build on the assumption.

**Available via:** HuggingFace `PaddlePaddle/PaddleOCR-VL`, vLLM (officially supported), FastDeploy, and **Ollama** (`MedAIBase/PaddleOCR-VL`) — Ollama being the easiest local path.

---

## 3. Indic-specific resources (highest relevance to your problem)

This is the most valuable category for you and it's dominated by Indian government and academic work — all free.

| Resource | What it is | Why it matters to you |
|---|---|---|
| **Anuvaad OCR models** ([project-anuvaad/anuvaad-ocr-model](https://github.com/project-anuvaad/anuvaad-ocr-model)) | Open-source OCR models for Indic languages | **Anuvaad is deployed in production at the Supreme Court of India (SUVAS), the Supreme Court of Bangladesh, and NCERT Diksha.** Production-proven on Indian legal/government documents — the closest match to your Board-agenda corpus of anything in this survey. **Investigate first.** |
| **NLTM OCR** ([ilocr.iiit.ac.in](https://ilocr.iiit.ac.in/)) | Govt of India National Language Translation Mission OCR consortium — IIIT Hyderabad, IIT Delhi, IIT Jodhpur, IIT Bombay, CDAC Noida, Punjabi University Patiala | Targets **13 Indic languages including Kannada**, explicitly for document + scene OCR. *(Site returned HTTP 502 when I checked — retry; it may be intermittent.)* |
| **IndicPhotoOCR** ([Bhashini-IITJ](https://github.com/Bhashini-IITJ/IndicPhotoOCR)) | TextBPN++ detection + ViT script ID + PARSeq recognition, 11 Indian languages | **Kannada supported** (added Feb 2025). Has **batch inference + confidence scoring** — needed for the plan's Stage 5 review gate. Small, trains on modest hardware. |
| **Indic-OCR Tesseract models** ([indic-ocr.github.io/tessdata](https://indic-ocr.github.io/tessdata/)) | Tesseract retrained to treat Indic dependent glyphs individually | **Works around C5** (Tesseract's left-to-right mis-ordering of pre-rendered vowel signs). Described as the best open-source Tesseract models for Indic. **Drop-in replacement for your current `kan.traineddata` — zero code change.** |
| **Bhashini / lekhaanuvaad** ([bhashini-dibd](https://github.com/bhashini-dibd/lekhaanuvaad)) | National language platform; open-sourced models incl. Kannada | Ecosystem hub; models and datasets |
| **Bharat Scene Text Dataset (BSTD)** ([arXiv 2511.23071](https://arxiv.org/html/2511.23071v2)) | Comprehensive Indian-language scene-text dataset + benchmark | **Source of the accuracy tables in the plan.** Use as supplementary fine-tuning data. |
| **"Towards Deployable OCR models for Indic languages"** ([arXiv 2205.06740](https://arxiv.org/pdf/2205.06740)) | IIIT-H paper on production Indic OCR | Architecture and training guidance |
| **bbOCR** ([arXiv 2308.10647](https://arxiv.org/pdf/2308.10647)) | Open-source multi-domain OCR pipeline for Bengali documents | **Reference architecture** for an Indic document pipeline — same problem shape, different script |

**Action:** Anuvaad and NLTM are the two I'd chase hardest. Both are government-funded, free, and purpose-built for exactly your document class (Indian institutional documents in regional scripts). Neither appeared in my first pass.

---

## 4. Trainable OCR frameworks — the fine-tuning toolchain

Fine-tuning is the single biggest accuracy lever (§7 of the plan: ~36% → 80%+ WRR). These are the tools that make it practical, and one of them solves your Phase 0 problem too.

| Tool | Licence | Role |
|---|---|---|
| **eScriptorium** | open ✅ | **GUI for transcribing ground truth AND training models — "with just a few clicks", no code.** Trains both layout-segmentation and text-recognition models; from scratch or fine-tune. **This directly solves Phase 0 tooling: you need a transcription UI anyway, and this one trains on what you transcribe.** Strongest single recommendation in this section. |
| **Kraken** | Apache 2.0 ✅ | The recognition engine behind eScriptorium. RNN + CTC. **Best open-source engine for handwriting (HTR) and connected/cursive scripts**, flexible layout analysis, trains on custom datasets. Relevant if handwriting is in scope. |
| **PyLaia** | open ✅ | Alternative HTR engine, also trainable from eScriptorium |
| **Calamari** | Apache 2.0 ✅ | Trainable line-recognition OCR, LSTM-based, ensemble/voting support |
| **PaddleOCR-VL SFT** | Apache 2.0 ✅ | Official supervised fine-tuning recipe ([PaddlePaddle/ERNIE docs](https://github.com/PaddlePaddle/ERNIE/blob/release/v1.5/docs/paddleocr_vl_sft.md)) — fine-tune the SOTA model on your Kannada corpus |
| **IndicPhotoOCR PARSeq** | open ✅ | Small recognizer; cheapest thing to fine-tune first |
| **Tesseract `lstmtraining`** | Apache 2.0 ✅ | Fine-tune `kan.traineddata`. Low ceiling (C5 is architectural) but very cheap |

**Recommended fine-tuning path:** transcribe ground truth in **eScriptorium** → fine-tune **IndicPhotoOCR PARSeq** first (small, fast, fits 6 GB) → then **PaddleOCR-VL SFT** once you have a bigger GPU.

---

## 5. Classical / non-VLM OCR engines

Still useful as ensemble votes, and they run on CPU.

| Engine | Licence | Indic WRR (off-the-shelf) | 6 GB? | Verdict |
|---|---|---|---|---|
| **PaddleOCR PP-OCRv6** | Apache 2.0 ✅ | **n/a — no Kannada** | ✅ / CPU | Best classical engine, but **Latin/CJK only** — see warning below |
| **Tesseract 5.5** | Apache 2.0 ✅ | **~15%** | ✅ CPU | **Your current primary. Demote to third vote.** Use Indic-OCR models if kept |
| **EasyOCR** | Apache 2.0 ✅ | ~18% | ✅ | PaddleOCR is strictly better |
| **docTR** (Mindee) | Apache 2.0 ✅ | — | ✅ | Clean API, modular detect+recognize, weak Indic |
| **MMOCR** (OpenMMLab) | Apache 2.0 ✅ | — | ✅ | Research toolkit; many detectors/recognizers to mix |
| **Surya** | ⚠️ **GPL-ish — verify** | — | ✅ | 90+ languages, strong layout. **Licence-check before commercial use** |

### ⚠️ Three different things are called "PaddleOCR" — only one reads Kannada

A common confusion, worth stating plainly because it changes the recommendation:

| Name | What it is | Languages | Kannada? |
|---|---|---|---|
| **PaddleOCR 3.x** (e.g. v3.7.0, Jun 2026) | the **toolkit / Python library** version | — | — |
| **PP-OCRv3 / v4 / v5 / v6** | the **classical OCR model** generation shipped inside the toolkit | **PP-OCRv6: 50 = Chinese, English, Japanese + 46 Latin-script** | ❌ **NO** |
| **PaddleOCR-VL-0.9B** | the **vision-language model** (§2) | **109** | ⚠️ **unconfirmed — test required** |

Toolkit version and model version are **not alternatives** — you install PaddleOCR 3.7 *to obtain* PP-OCRv6.

**The material point:** PP-OCRv6 is the newest and most accurate classical PaddleOCR model (+5.1% recognition, +4.6% detection over PP-OCRv5_server, PPLCNetV4 backbone, 1.5M–34.5M params across tiny/small/medium tiers) — **but its 50 languages are Latin-script and CJK only. It cannot read Kannada.** Use it for the English/Latin portions of a page and nothing else.

**For Kannada, the PaddleOCR-family answer is PaddleOCR-VL, not PP-OCRv6.** Older PP-OCRv3/v4 multilingual models had some Indic coverage (Devanagari, Tamil, Telugu) at lower accuracy; Kannada support there is not confirmed either. The ~29% "PaddleOCR" Indic WRR figure quoted in §0.1 of the plan comes from the BSTD benchmark testing whatever Indic models existed at the time — **do not read it as a PP-OCRv6 number.**

---

**Components worth knowing** (if you build a custom pipeline): **CRAFT**, **DBNet/DBNet++** (text detection); **PARSeq**, **ABINet**, **SATRN**, **TrOCR** (recognition); **TableFormer**, **PP-Structure** (table structure).

---

## 6. Orchestration frameworks

Don't hand-roll the pipeline if one of these already does it.

| Framework | Licence | Notes |
|---|---|---|
| **Docling** (IBM) | **MIT** ✅ | PDF/DOCX/PPTX/HTML/images → structured JSON/MD. Includes **TableFormer**. Clean Python API. **Safest licence + best engineering.** Can use Surya or Tesseract as OCR backend |
| **MinerU** | AGPL ⚠️ | Very strong PDF→markdown. Check licence |
| **Marker** | GPL-ish ⚠️ | Surya-based PDF→markdown. Check licence |
| **unstructured.io** | Apache 2.0 ✅ | Broad document ingestion for RAG pipelines |
| **OCRmyPDF** | MPL-2.0 ✅ | **Already in your stack.** Best-in-class searchable-PDF generation — keep it for output (A) |
| **OpenDataLoader PDF** | **Apache 2.0** ✅ | Hancom Inc. (Korea). Java 11+, ~28k stars. See assessment below |

### OpenDataLoader PDF — assessed on request

**What it is:** PDF → AI-ready structured data (JSON with bounding boxes / Markdown / HTML) for RAG pipelines, plus PDF accessibility auto-tagging (EAA / ADA / Section 508). **XY-Cut++ reading order** for multi-column, borderless-table extraction, built-in OCR claiming 80+ languages via `--force-ocr`, and AI-safety filtering for hidden text and prompt-injection attempts. Apache 2.0 (MPL-2.0 before v2.0). Ships LangChain and LlamaIndex integrations and its own benchmark suite.

**Verdict: useful for the digital-born PDF lane (§1), NOT the answer to the Kannada scan problem.** Three reasons:

| Issue | Detail |
|---|---|
| **Local table accuracy is far worse** | Quoted TEDS: **0.489 standard vs 0.928 hybrid** — and "hybrid" routes complex pages to *AI backends* / "optional LLM enhancement", i.e. a cloud LLM. You've ruled that out. Honest local comparison: **OpenDataLoader 0.489 vs PaddleOCR-VL 0.9195**, both local. PaddleOCR-VL wins decisively, and tables are your stated alignment problem. |
| **No Indic / Kannada support listed** | Repo and site name Korean, Japanese, Chinese, Arabic, German, French, English — no Indic in the 80+. Java PDF tools typically wrap Tesseract for OCR, which would inherit the ~15%-WRR Kannada failure (C5). Unverified, but the signal is bad. |
| **PDF-first; your hard case is JPG** | Your corpus is phone photos of Kannada documents on dark folders. OCR is this tool's secondary path, not its focus. |
| **Java 11+ vs your Python stack** | CLI bridge or JVM in the deployment. Not fatal, but real integration friction. |

**Where it earns its place:** the text-layer PDF fast path — reading order + bounding boxes + tables + JSON in one Apache-2.0 local package, better than hand-rolling pdfplumber. The hidden-text / prompt-injection filter is a genuine plus for a DMS, and accessibility tagging may satisfy a compliance requirement.

**Test it in Phase 1 for the PDF lane only.** Do not put it on the Kannada-scan path without measuring Kannada first.

---

## 7. Benchmarks — use these instead of guessing

| Benchmark | Use |
|---|---|
| **OmniDocBench** ([opendatalab, CVPR 2025](https://github.com/opendatalab/OmniDocBench)) | The standard document-parsing benchmark. **Run it yourself** — it's an open harness, so Phase 1 doesn't need building from scratch |
| **olmOCR-Bench** | Complementary; unit-test-style pass rates |
| **BSTD** ([arXiv 2511.23071](https://arxiv.org/html/2511.23071v2)) | Indian-language benchmark — the only one here that actually covers your scripts |

> ⚠️ **Every headline score in §2 is vendor self-reported.** OmniDocBench's own maintainers and multiple independent reviewers flag this and recommend private evaluation. **Treat all of it as a prior for what to test, never as a result.** Your Phase 0 corpus is the only benchmark that decides anything.

---

## 8. Revised recommendation

### Do this now (free, this laptop, no upgrade)

1. **Add the digital-born fast path** (§1). Detect text-layer pages and extract directly — 100% accurate, instant. Change `force_ocr=True` → `--skip-text` at [main.py:198](ocr/main.py#L198). *Hours of work, immediate accuracy win.*
2. **Swap in Indic-OCR's Kannada `traineddata`** (§3). Drop-in file replacement, no code change, works around C5.
3. **Install PaddleOCR-VL-0.9B via Ollama or vLLM** (§2) and run it on your existing Kannada pages. ~2.5 GB VRAM. **This one test tells you whether the whole problem is already solved** — and whether Kannada is in the 109 languages.
4. **Stand up eScriptorium** (§4) as the Phase 0 transcription UI — it doubles as the fine-tuning trainer.
5. **Chase Anuvaad + NLTM models** (§3). Production-proven on Indian government documents; nothing else in this survey is that well-matched.

### Then

6. Phase 1 bake-off using **OmniDocBench's harness** + your own corpus: PaddleOCR-VL vs MinerU vs Granite-Docling vs IndicPhotoOCR vs Anuvaad.
7. Fine-tune the winner on your corpus (§4).
8. GPU upgrade **only if** fine-tuning throughput or page volume demands it — no longer a blocker for capability.

### Licence watch-list (matters if this ships commercially)

**Safe:** PaddleOCR / PaddleOCR-VL (Apache 2.0), Docling (MIT), pdfplumber (MIT), Granite-Docling (Apache 2.0), Qwen (Apache 2.0), Tesseract (Apache 2.0), OCRmyPDF (MPL-2.0), Kraken (Apache 2.0).

**Verify before shipping:** PyMuPDF (**AGPL**), MinerU (**AGPL**), Surya (**GPL-ish**), Marker (**GPL-ish**), pdftotext/Poppler (**GPL**).

AGPL/GPL is fine for internal use; it is a genuine problem in a distributed commercial product. Since PaddleOCR-VL (Apache 2.0) is also the accuracy leader, **the licence-safe choice and the best choice are the same model** — which is a rare and convenient outcome.

---

## 9. What changed vs. the original plan

| Original claim | Corrected |
|---|---|
| GPU upgrade near-mandatory for a usable VLM stage | **Wrong.** PaddleOCR-VL-0.9B runs in ~2.5 GB. Upgrade is now for fine-tuning comfort and throughput, not capability |
| Best local VLMs are dots.ocr / DeepSeek-OCR / Qwen-VL | **Superseded.** PaddleOCR-VL-0.9B scores higher, is 3× smaller, and is Apache 2.0 |
| (not covered) | **Digital-born PDF fast path** — free, perfect accuracy on any text-layer page; your code currently destroys it with `force_ocr=True` |
| (not covered) | **Anuvaad + NLTM** — Indian government Indic OCR, production-deployed at the Supreme Court of India |
| (not covered) | **eScriptorium** — solves Phase 0 transcription tooling *and* trains models on the result |
| Phase 1 bake-off harness to be built | **OmniDocBench is an open harness** — adapt it rather than build |
| Layout via PP-Structure or Docling | Also **PP-DocLayoutV2** inside PaddleOCR-VL: RT-DETR + pointer network for reading order, TEDS 0.9195 on tables |

---

## Sources

- [PaddleOCR-VL: Boosting Multilingual Document Parsing via a 0.9B Ultra-Compact VLM](https://arxiv.org/html/2510.14528v1) · [HuggingFace](https://huggingface.co/PaddlePaddle/PaddleOCR-VL) · [docs](https://paddlepaddle.github.io/PaddleOCR/main/en/version3.x/algorithm/PaddleOCR-VL/PaddleOCR-VL.html) · [SFT guide](https://github.com/PaddlePaddle/ERNIE/blob/release/v1.5/docs/paddleocr_vl_sft.md) · [language-list discussion](https://huggingface.co/PaddlePaddle/PaddleOCR-VL/discussions/12)
- [PaddleOCR-VL-1.6 VRAM Requirements: ~2 GB](https://www.spheron.network/tools/gpu-recommender/PaddlePaddle/PaddleOCR-VL-1.6)
- [PaddleOCR-VL 1.5 deep dive — outperforms GPT-4o](https://pub.towardsai.net/paddleocr-vl-1-5-a-deep-dive-into-the-0-9b-model-that-outperforms-gpt-4o-on-document-parsing-c93bac97ac1f)
- [Best Open-Source OCR/Document VLMs to Self-Host 2026](https://www.spheron.network/blog/best-open-source-ocr-vlm-self-host-gpu-cloud-2026/)
- [OmniDocBench (CVPR 2025)](https://github.com/opendatalab/OmniDocBench)
- [FastDeploy — PaddleOCR-VL-0.9B best practices](https://paddlepaddle.github.io/FastDeploy/best_practices/PaddleOCR-VL-0.9B/)
- [Anuvaad OCR models for Indic languages](https://github.com/project-anuvaad/anuvaad-ocr-model) · [Anuvaad platform](https://github.com/project-anuvaad/anuvaad) · [Wikipedia](https://en.wikipedia.org/wiki/Anuvaad_(Document_Translation_Platform))
- [NLTM OCR — IIIT Hyderabad consortium](https://ilocr.iiit.ac.in/)
- [Bhashini lekhaanuvaad](https://github.com/bhashini-dibd/lekhaanuvaad)
- [IndicPhotoOCR](https://github.com/Bhashini-IITJ/IndicPhotoOCR) · [docs](https://bhashini-iitj.github.io/IndicPhotoOCR/)
- [Indic-OCR Tesseract models](https://indic-ocr.github.io/tessdata/)
- [Bharat Scene Text Dataset](https://arxiv.org/html/2511.23071v2)
- [Towards Deployable OCR models for Indic languages](https://arxiv.org/pdf/2205.06740)
- [bbOCR: Open-source Multi-domain OCR Pipeline for Bengali](https://arxiv.org/pdf/2308.10647)
- [Kraken OCR engine](https://github.com/mittagessen/kraken) · [training docs](https://kraken.re/3.0/training.html)
- [Training with eScriptorium — step-by-step](https://ub-mannheim.github.io/eScriptorium_Dokumentation/Training-with-eScriptorium-EN.html)
- [Docling toolkit](https://arxiv.org/pdf/2501.17887)
- [pdfplumber](https://github.com/jsvine/pdfplumber) · [PyMuPDF text recipes](https://pymupdf.readthedocs.io/en/latest/recipes-text.html)
- [PDF extraction library benchmark](https://github.com/justin-aj/pdf-extraction-benchmark)
- [Technical Analysis of Modern Non-LLM OCR Engines](https://intuitionlabs.ai/articles/non-llm-ocr-technologies)
- [GLM-OCR vs PaddleOCR: 0.9B benchmarks](https://decodethefuture.org/en/glm-ocr-explained/)
