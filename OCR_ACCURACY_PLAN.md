# OCR Accuracy & Layout Fidelity — Production Plan
## Fully local · free · open-source only

**Status:** proposal, awaiting decisions in §10
**Constraint set:** no cloud APIs, no paid services, everything runs on-premise
**Date:** 2026-07-30

---

## 0. Two hard truths, stated up front

### 0.1 "100% accuracy" is not achievable as raw OCR — but 100% *delivered* output is

No OCR system reaches 100% character accuracy on arbitrary scanned documents. For Kannada, fully local and open-source, the published reality is much starker than most people expect. Measured Word Recognition Rate on Indian-language text, off-the-shelf:

| Engine (off-the-shelf, no fine-tuning) | Word Recognition Rate |
|---|---|
| **Tesseract** | **~15%** |
| EasyOCR | ~18% |
| PaddleOCR | ~29% |
| IndicPhotoOCR | ~36% (54% character rate) |

Those are scene-text numbers, and clean document scans score considerably higher — but **the ranking holds, and it tells you that the current Tesseract-based pipeline is built on the weakest available foundation for Kannada.** That is not a tuning problem.

Now the number that matters most, from the same benchmark — the same models **after fine-tuning**:

| Language | Fine-tuned WRR |
|---|---|
| English | **92%** |
| Marathi | 86% |
| Bengali | 82% |
| Tamil | 80% |
| Hindi | 71% |
| Malayalam | 58% |
| Telugu | 56% |

**Fine-tuning moves accuracy more than any engine swap will.** 36% → 80%+ is a bigger jump than anything available by choosing a different off-the-shelf model. Kannada is Dravidian like Telugu and Malayalam, so expect it to land in that 55–75% band fine-tuned on hard input, and meaningfully higher on clean document scans. **This makes fine-tuning a first-class phase of this plan, not an optional extra** (§7).

**So the path to 100% is: maximize machine accuracy, then gate on confidence and route the remainder to a human reviewer.** The machine does 90–99%; a person verifies the flagged remainder; the *delivered document* is 100% correct. That is the only honest route to 100%, and it is a genuinely achievable target. Fully local and open-source, the human-review gate matters **more**, not less, because the raw accuracy ceiling is lower than a cloud stack's.

### 0.2 Your current hardware is the binding constraint

#### Machine inventory (verified 2026-07-30)

| Machine | Spec | Role |
|---|---|---|
| **Laptop** | RTX 3050 Laptop **6 GB VRAM** · Ryzen 5 7235HS 4C/8T · 11.7 GB RAM | **inference + dev** — the only GPU you have |
| **Remote "GPU server"** (`38.247.130.64`) | **NO GPU** · 2 vCPU · **3.8 GB RAM** · 47 GB free · Ubuntu 24.04 | **app host only** |
| Rented GPU (hourly, optional) | 24 GB class, ~$0.30–0.60/hr | **fine-tuning bursts only** |

> ⚠️ **The remote server has no GPU.** Verified: its only display device is a `Red Hat QXL paravirtual graphic card` (QEMU's emulated VGA — zero compute), `systemd-detect-virt` returns `kvm`, and every PCI device is a virtio/QEMU emulation. `nvidia-smi` is absent because there is no accelerator to drive.
>
> **Its 3.8 GB RAM is a harder blocker than the missing GPU** — you need roughly 2× VRAM in system RAM to stage model weights, so a 7B model needs ~15 GB RAM regardless of card. Fine-tuning is out of reach on this host.
>
> **Use it for:** FastAPI, job queue, review UI, Postgres, document store, **and the digital-born PDF fast path + Stage 0 normalization — both CPU-only, both deployable today.** Phase 2 (the missing-text fix) runs entirely here and on the laptop, with no GPU needed.

Detected on the laptop:

| Component | Spec | Verdict |
|---|---|---|
| GPU | **NVIDIA RTX 3050 Laptop, 6 GB VRAM** | tight — see below |
| CPU | AMD Ryzen 5 7235HS, **4 cores** / 8 threads | low for CPU-side OCR throughput |
| RAM | **11.7 GB** | limits CPU offload and batch size |

What that means concretely for local VLM OCR:

| Model | Memory need | Fits in 6 GB? |
|---|---|---|
| DeepSeek-OCR (3B) FP16 | ~6.3 GB weights, **~13 GB** with cache + activations | ❌ **No** |
| dots.ocr (3B) FP16 | vendor guidance: **16+ GB VRAM** | ❌ **No** |
| **dots.ocr GGUF Q8** | **1.8 GB text + 2.4 GB vision ≈ 4.2 GB** | ✅ **Yes**, with trade-offs |
| Qwen2.5-VL-7B 4-bit | ~5–6 GB weights + vision activations | ⚠️ Marginal; high-res pages will OOM |
| Qwen2.5-VL-3B 4-bit | ~2.5–3 GB | ✅ Yes |
| PaddleOCR PP-OCRv6 | small CNN/transformer | ✅ Yes (or CPU) |
| Tesseract / EasyOCR | CPU-only | ✅ Yes |
| IndicPhotoOCR | small detection + recognition models | ✅ Yes |

**Running any of the strong document VLMs at full precision is not feasible on 6 GB.** Quantized GGUF via llama.cpp is feasible and is the right dev path — accepting accuracy and speed trade-offs.

> ### ⚠️ CORRECTED 2026-07-30 — see [OCR_RND_LANDSCAPE.md](OCR_RND_LANDSCAPE.md) §0
>
> Follow-up R&D **overturned the conclusion that was here.** I had written that a GPU upgrade was near-mandatory for a usable VLM stage. That is wrong.
>
> **PaddleOCR-VL-0.9B beats GPT-4o, Gemini 2.5 Pro, and Qwen3-VL-235B on document parsing, and runs in ~2.5 GB VRAM at FP16 (~0.5 GB at INT4).** It fits your existing 6 GB laptop GPU with room to spare, it is Apache 2.0, and it is fine-tunable. The "43.7 GB VRAM" figure in its paper is a high-throughput vLLM batch config on an A100, not a floor.
>
> **Revised position:** you can run a SOTA document-parsing VLM today, on this laptop, for free. A used RTX 3090 24 GB (~$800) is still worth it for *comfortable fine-tuning and throughput* — but it is **no longer a capability blocker**, and it is no longer the top priority.
>
> The model table in §0.2 above remains accurate for dots.ocr / DeepSeek-OCR / Qwen-VL; those are simply **superseded by a smaller, better, licence-safer model.** Read the landscape survey before acting on §4 or §9.
>
> **You can start Phases 0–2 today on this laptop.** Those phases fix the missing-text bug and need no VLM at all.

---

## 1. Root-cause diagnosis (evidence-backed)

Measured against the current code and `ocr_workspace/03a8208bb34d/input.jpg` (1944×2592, ~235 DPI).

### 1.1 Causes of MISSING text

| # | Cause | Evidence | Location |
|---|---|---|---|
| **C1** | **Blind 8% edge crop discards 29.4% of every page** before OCR runs. Text near the margin is *deleted*, not mis-read. Largest single cause of missing text. | Measured: 155px/side horizontal, 207px vertical = 1,479,996 of 5,038,848 px | [main.py:113-116](ocr/main.py#L113-L116), duplicated in [docx_generator.py:33-35](ocr/docx_generator.py#L33-L35) |
| **C2** | **`clean_output()` silently deletes real lines.** `symbols/total > 0.15` kills table rows (`\|`), dates, times, reference numbers. `startswith('ut 584')` is a hardcoded hack for one image. | Dropped 1/18 lines on the test image; rules are unbounded and will drop far more on table-heavy pages | [main.py:138-175](ocr/main.py#L138-L175) |
| **C3** | **Aggressive binarization erases thin strokes.** `medianBlur(3)` + `adaptiveThreshold(41,15)`, tuned for one dark-folder scan, destroys Kannada matras and conjunct sub-glyphs before Tesseract sees them. | Kannada output mangled: `ನಗ ನ ಸಂಸ ಲಾ` where the company name should be | [main.py:129-132](ocr/main.py#L129-L132) |
| **C4** | **No DPI normalization.** Input is ~235 DPI; code passes `image_dpi=300` as a *claim* without resampling. Indic scripts need x-height ≥ 20px to resolve matras. | `image_dpi=300` asserted on a 235 DPI image | [main.py:194](ocr/main.py#L194) |
| **C5** | **Tesseract is structurally wrong for Kannada.** In Indic scripts, vowel signs that logically *follow* a consonant are *rendered before* it; Tesseract's left-to-right decoding mis-orders them. Confirmed independently by two sources. At ~15% WRR off-the-shelf it is the weakest available choice. | Indic-OCR project documentation; benchmark table in §0.1 | engine choice |

### 1.2 Causes of BROKEN alignment

| # | Cause | Evidence | Location |
|---|---|---|---|
| **C6** | **No table model.** `--psm 3` has no table structure, so columns flatten into reading-order lines. The test document's INDEX table collapsed into `Item SUBJECT Page` / `No. : ಪ No.`. **Primary cause of "didn't align properly how in document present".** | Extracted output lines 8–11 | [main.py:236](ocr/main.py#L236) |
| **C7** | **Cascading collision resolver → progressive vertical drift.** `if item['top'] < last_bottom + 4: item['top'] = last_bottom + 4` — one over-tall bbox pushes every later line down, and error accumulates monotonically down the page. | Same flawed logic duplicated in two files | [main.py:328-332](ocr/main.py#L328-L332), [docx_generator.py:533-536](ocr/docx_generator.py#L533-L536) |
| **C8** | **Magic fudge factors** as general logic: `+2` px offset, `*0.8` height shrink, `0.65/0.55` char-width guesses. Per-image calibration in disguise. | `scaled_top = ... + margin_y + 2`, `scaled_height = int(robust_height * 0.8)` | [main.py:312-314](ocr/main.py#L312-L314) |
| **C9** | **Three different font-sizing algorithms** → preview never matches DOCX: frontend canvas binary-search; backend char-width heuristic; raw bbox height. | `calculateOptimalFontSize()` vs `char_factor` vs `item.height` | [app.js:344](ocr/app.js#L344), [docx_generator.py:545-553](ocr/docx_generator.py#L545-L553) |
| **C10** | **Font size derived from bbox height** — Kannada bboxes are inflated by matras above/below baseline, so Kannada renders systematically larger than adjacent English. | `fontSizePixels = Math.max(8, item.height)` | [app.js:318](ocr/app.js#L318) |

### 1.3 Systemic causes

| # | Cause | Evidence | Location |
|---|---|---|---|
| **C11** | **Two independent OCR passes that disagree.** `/extract` runs pytesseract for positions *and* ocrmypdf for text, producing different strings for the same region. UI shows one; stats/export use the other. Also doubles runtime (77s/page measured). | Same image: sidecar `085110867937500001321` vs pytesseract `UBS110KA1947SGC001321`; truth `U85110KA1947SGC001321` — **both wrong, differently** | [main.py:390-393](ocr/main.py#L390-L393) |
| **C12** | **Mixed coordinate frames.** `rotate_pages=True` + `deskew=True` let ocrmypdf rotate the page, but pytesseract bboxes are in the *un*-rotated frame. Any rotated page has text and positions in different geometries. | `rotate_pages=True, deskew=True` | [main.py:195-196](ocr/main.py#L195-L196) |
| **C13** | **No confidence propagated to output.** `conf` is read and used only to drop `-1` markers. Without per-token confidence there is no review queue — this structurally blocks any path to 100%. | `if conf < 0: continue` and nothing else | [main.py:249-251](ocr/main.py#L249-L251) |
| **C14** | **Double destruction of the source image.** Frontend swaps the canvas for the inpainted preview, then uploads *that* to `/formatted`, which preprocesses and inpaints it again. | `state.image = previewImg` → `canvas.toBlob` → `/formatted` | [app.js:245-251](ocr/app.js#L245-L251) |
| **C15** | **Only `kan+eng`, no script detection.** Stacking languages into one Tesseract call degrades all of them — so "just add more languages" is not a valid fix. | `language=["kan","eng"]` hardcoded | [main.py:193](ocr/main.py#L193) |

---

## 2. The key architectural insight

The current code tries to produce a **pixel-accurate visual replica that is also editable**: inpaint away the original text, then float an absolutely-positioned text box over the hole for each OCR line.

**This is the hardest possible target and the least valuable one.** Every bbox error becomes visible misalignment, and C7 compounds those errors down the page. It cannot be made robust by tuning — the failure is structural.

Two legitimate targets, needing different outputs:

| | **(A) Archival fidelity** | **(B) Editable structure** |
|---|---|---|
| **Requirement** | Page looks exactly like the original | Content editable, searchable, extractable |
| **Right output** | Searchable PDF: original image + **invisible** text layer | DOCX/JSON with real headings, paragraphs, **real Word tables** |
| **Alignment risk** | **Zero** — the original image *is* the layout | Semantic, not pixel — no bbox arithmetic to get wrong |
| **Working today?** | **Yes** — ocrmypdf already does this correctly | No — this is what needs building |

**Recommendation: ship both A and B; delete the floating-text-box hybrid.** This one decision eliminates **C7, C8, C9, C10, and C14** outright, and it is free.

---

## 3. Target architecture (all local)

```
┌── STAGE 0 ── Ingest & Normalize ───────────────── CPU, runs today ──┐
│  NO blind cropping (kills C1)                                       │
│  • orientation detect → rotate upright                              │
│  • deskew + dewarp (page-curl for phone photos)                     │
│  • real page-boundary segmentation, not a fixed 8% guess             │
│  • resample to 300–400 DPI effective; upscale if x-height < 20px    │
│  • ONE canonical image, ONE coordinate frame (kills C12)            │
│  Tools: OpenCV (already installed), jdeskew / docdewarp             │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌── STAGE 1 ── Layout Analysis ──────────────── GPU-light, 6GB OK ───┐
│  Detect text blocks, TABLES (row/col indices), figures, headings,   │
│  reading order.  Output a page TREE, not a flat line list (C6)     │
│  Tools: PaddleOCR PP-Structure  OR  Docling + TableFormer (MIT)    │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌── STAGE 2 ── Script Detection (per block) ──── small ViT, 6GB OK ──┐
│  Route each block to a script specialist instead of stacking every │
│  language into one call (kills C15)                                │
│  Tools: IndicPhotoOCR's ViT script identifier                      │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌── STAGE 3 ── Recognition (per block, ensemble) ─── 6GB OK ─────────┐
│  2–3 engines/block, each emitting per-token confidence             │
│  Gentle reversible preprocessing — keep grayscale, NEVER hard-      │
│  binarize Indic text (kills C3, C4)                                │
│  Kannada: IndicPhotoOCR (PARSeq) + Indic-OCR Tesseract models      │
│  Latin:   PaddleOCR PP-OCRv6                                       │
│  ► FINE-TUNED on your corpus — biggest single lever (§7)  (C5)     │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌── STAGE 4 ── Local VLM Reconciliation ─── needs 24GB for full qual ┐
│  Where engines disagree OR confidence is low: send the IMAGE CROP  │
│  + candidate readings to a local VLM to adjudicate on pixels.      │
│  ALL rule-based filters DELETED — a model that sees the crop       │
│  replaces every hardcoded heuristic.        (kills C2, C11)        │
│  6GB:  dots.ocr GGUF Q8 (~4.2GB) or Qwen2.5-VL-3B 4-bit           │
│  24GB: dots.ocr / Qwen2.5-VL-7B full precision  ← recommended      │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌── STAGE 5 ── Confidence Gate ─────────────────── the 100% mechanism┐
│  ≥ τ_high      → auto-accept                                       │
│  τ_low..τ_high → human review queue (crop shown side-by-side)      │
│  < τ_low       → flagged unreadable, NEVER silently dropped        │
│                                              (kills C13)           │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌── STAGE 6 ── Export ───────────────────────────────────────────────┐
│  (A) searchable PDF — image + invisible text layer                 │
│  (B) DOCX/JSON — real headings, paragraphs, real Word tables        │
│  (C) audit record — per-token confidence, engine votes, reviewer   │
└─────────────────────────────────────────────────────────────────────┘
```

**Non-negotiable invariant: nothing is ever silently discarded.** Every region either reaches the output or reaches the review queue with a reason. C1 and C2 both violate this, and that is why text currently vanishes without a trace.

---

## 4. Engine selection — all free & open-source

> ### ⚠️ SUPERSEDED — read [OCR_RND_LANDSCAPE.md](OCR_RND_LANDSCAPE.md) §2–§6 first
>
> The table below is still correct but **incomplete**. Follow-up R&D found four things it misses:
> 1. **PaddleOCR-VL-0.9B** — new top pick. SOTA document parsing, ~2.5 GB VRAM, Apache 2.0, fine-tunable. Supersedes dots.ocr and DeepSeek-OCR below.
> 2. **Digital-born PDF fast path** — pages that already have a text layer need *no OCR at all*. Free, instant, 100% accurate. Your code destroys this today with `force_ocr=True` at [main.py:198](ocr/main.py#L198).
> 3. **Anuvaad + NLTM OCR** — Indian government Indic OCR models, production-deployed at the **Supreme Court of India**. Closest match to your document class of anything surveyed.
> 4. **eScriptorium** — GUI that both transcribes ground truth *and* trains models on it. Solves Phase 0 tooling.

**Licence column matters now.** Verify before committing; a GPL model in a commercial product is a legal problem, not a technical one.

| Engine | Role | Licence | Runs in 6 GB? | Notes |
|---|---|---|---|---|
| **PaddleOCR PP-OCRv6 / PP-Structure** | layout + tables + Latin recognition | **Apache 2.0** ✅ | ✅ | v3.7.0 (Jun 2026). +4.6% det / +5.1% rec over v5. Native table structure. **Best all-round self-hosted base.** |
| **Docling + TableFormer** | layout + table structure | **MIT** ✅ | ✅ | IBM. Excellent table structure, clean Python API, structured JSON/MD export. Safest licence. |
| **IndicPhotoOCR** (Bhashini-IITJ) | **Kannada recognition + script ID** | open ✅ | ✅ | TextBPN++ detection + ViT script ID + PARSeq recognition. **11 Indian languages incl. Kannada** (added Feb 2025). Has **batch inference AND confidence scoring** — exactly what Stage 5 needs. **Primary Kannada engine.** |
| **Indic-OCR Tesseract models** | Kannada second vote | Apache 2.0 ✅ | ✅ (CPU) | Tesseract retrained to treat Indic dependent glyphs individually, working around C5. Described as the best open-source Tesseract models for Indic. **Free drop-in upgrade over your current `kan.traineddata`.** |
| **Surya** | layout + recognition, 90+ langs | ⚠️ **GPL-ish — verify commercial terms** | ✅ | Strong layout module. **Check the licence before shipping commercially.** |
| **dots.ocr** (3B) | Stage 4 VLM | open ✅ | ⚠️ only as **GGUF Q8 (~4.2 GB)** | Qwen2.5-VL-based, layout-aware. FP16 wants 16+ GB. GGUF quantized fits your 6 GB. |
| **DeepSeek-OCR** (3B) | Stage 4 VLM | open ✅ | ❌ (~13 GB w/ activations) | Strong, but needs the GPU upgrade. |
| **Qwen2.5-VL / Qwen3-VL** | Stage 4 VLM | Apache 2.0 ✅ | 3B ✅ / 7B ⚠️ | Best messy-layout + handwriting handling. 7B is the sweet spot **on 24 GB**. |
| **Tesseract 5.5** (stock `kan`) | ❌ demote | Apache 2.0 | ✅ | **~15% WRR on Indic — do not keep as primary.** Third vote only. |
| **EasyOCR** | not recommended | Apache 2.0 | ✅ | ~18% WRR; PaddleOCR strictly better. |

**Recommended local stack:** PaddleOCR PP-Structure (Stage 1) → IndicPhotoOCR ViT (Stage 2) → **IndicPhotoOCR PARSeq fine-tuned** + Indic-OCR Tesseract (Stage 3) → dots.ocr / Qwen2.5-VL (Stage 4). Confirm with the Phase 1 bake-off.

---

## 5. Stage 4: local VLM reconciliation

Replaces every hardcoded heuristic in `clean_output()` with a model that can look at the pixels.

**On 6 GB (now):** `dots.ocr` GGUF Q8 via **llama.cpp** — 1.8 GB text + 2.4 GB vision ≈ 4.2 GB. Or Qwen2.5-VL-3B at 4-bit. Serve via llama.cpp's OpenAI-compatible server so the app code is identical when you upgrade the GPU.

**On 24 GB (recommended):** dots.ocr or Qwen2.5-VL-7B at full precision — materially better on Kannada conjuncts.

**Implementation notes:**
- **Give the VLM a `crop_region(x,y,w,h)` tool** so it can zoom into an ambiguous conjunct rather than guessing from the full-page view. Iterative crop-and-verify beats one full-page look at equal compute.
- **Constrain output to a JSON schema** with a mandatory per-token confidence field — use llama.cpp GBNF grammars to enforce it. Never free text to re-parse.

**Guardrail — mandatory.** A VLM asked to "clean up" OCR text will confidently **invent** plausible text for illegible regions. That is worse than a blank, because it is undetectable downstream. Two mitigations:
1. The schema must offer an explicit `illegible` verdict as a first-class option, and the prompt must state that `illegible` is a *correct* answer.
2. Constrain the model to **choosing among candidate readings** or returning `illegible` — never free-generating replacement text for a region no engine could read.

A 2026 benchmark exists specifically because naive VLM post-correction can *degrade* Indic accuracy. **Treat Stage 4 as measured, not assumed — A/B it against no-reconciliation in Phase 4.** Smaller/quantized models hallucinate more, so this guardrail matters more on your 6 GB setup, not less.

---

## 6. Multilingual & regional language strategy

**Do not stack languages into one recognizer call** — that is C15 and it degrades every language at once.

1. **Script detection per block** (Stage 2). Kannada, Devanagari, Tamil, Telugu, Malayalam, Bengali, Gujarati, Gurmukhi, Odia, Latin are reliably separable at block level. IndicPhotoOCR ships a ViT script identifier for exactly this.
2. **Route to a script specialist.** One model per script beats one model for all scripts.
3. **Handle mixed-script lines explicitly** — very common in Indian government documents (`ಸಂಸ್ಥೆ (Company) 424th`). Segment the line into script runs, recognize each with its specialist, reassemble in reading order. The single-pass approach is why `3. ಓಟ 1 ಎ °° Bengaluru. ,` came out garbled.
4. **Unicode NFC normalization at the boundary.** Indic text has multiple valid encodings for the same rendered glyph; without normalization, search and diff silently fail *even when the OCR was correct*.
5. **Fonts for export.** Bundle and embed per-script Noto faces. Note: `NotoSansKannada.zip` is sitting **unextracted** in the repo, and `styles.css` references `'Noto Sans Kannada'` with **no `@font-face` rule** — so the browser silently falls back to a font that cannot render Kannada. Fix in Phase 5.

**Phase the languages.** Kannada + English first. Add one script at a time, each gated on its own measured accuracy. IndicPhotoOCR gives you 11 Indian languages on one architecture, so adding a script means fine-tuning, not re-architecting.

---

## 7. Fine-tuning — the single biggest accuracy lever

Per §0.1, fine-tuning takes Indic WRR from ~36% to 80%+. **No engine swap comes close to that.** It is also free apart from compute, which fits the constraints perfectly.

- **Data:** your own scanned corpus is the highest-value training data because it matches your real distribution (same scanner, same folders, same fonts, same lighting). Supplement with the **Bharat Scene Text Dataset (BSTD)** and Indic-OCR's public data.
- **Volume:** start with the Phase 0 ground-truth set (100–200 pages); a few thousand line-level crops materially move recognition accuracy.
- **What to fine-tune:** the PARSeq recognizer in IndicPhotoOCR (small, trains on modest hardware) before attempting any VLM fine-tune.
- **Hardware:** 6 GB can fine-tune a small PARSeq recognizer with small batches and gradient accumulation. **24 GB makes this comfortable and opens VLM LoRA fine-tuning.** This is the main reason the GPU upgrade is worth it.
- **Synthetic augmentation is free and effective:** render Kannada text in your document's fonts, then apply your actual degradations — blur, JPEG artifacts, shadow gradients, the dark-blue folder background, phone-camera perspective. Cheap way to multiply training data.

---

## 8. Cost model

Licences: **₹0 / $0.** Cost shifts from per-page API spend to one-time hardware plus throughput.

| Item | Cost | Note |
|---|---|---|
| All software in §4 | **$0** | verify Surya's licence for commercial use |
| Current laptop (RTX 3050 6 GB) | already owned | Phases 0–2 fully; Phase 3–4 degraded |
| **Used RTX 3090 24 GB** | **~$700–900 one-time** | unlocks 7B VLMs + fine-tuning. **Highest-leverage spend in this plan.** |
| New RTX 4090 / 5090 24–32 GB | ~$1,800–2,500 | faster, not required |
| Electricity | ~$0.05–0.15/hr under load | negligible |
| **Per-page marginal cost** | **≈ $0** | this is the whole point of going local |

**Throughput is your real constraint, not money.** Current pipeline: **77 s/page** — and [app.js:275](ocr/app.js#L275) fires a *second* full OCR pass right after the first, so one click costs ~2.5 minutes. Fixing C11 (one pass, not two) roughly halves that for free. Expect ~5–15 s/page on the 3050 for the deterministic stack, and 30–90 s/page when a quantized VLM adjudicates.

**Break-even framing:** at 10k pages/month, a cloud stack would run ~$300–900/month. A $800 GPU pays for itself in **1–3 months** and then costs nothing. Going local is the economically correct choice at your volume — it is just front-loaded.

---

## 9. Delivery phases

Each phase is independently shippable and gated on a measurement.

### Phase 0 — Ground truth & harness *(prerequisite — nothing else is meaningful without it)*
- Hand-transcribe **100–200 representative pages**: Kannada, English, mixed, tables, stamps, handwriting, poor scans. Unglamorous and non-optional — **without ground truth, "did this help?" is unanswerable.** This set doubles as fine-tuning data (§7), so the effort pays twice.
- Harness metrics: **CER, WER, table-cell F1, reading-order accuracy** (Kendall tau), and a **coverage** metric — % of ground-truth characters appearing *anywhere* in output. Coverage is what would have caught C1 and C2 immediately.
- Baseline today's pipeline. Expect a sobering number; that's the point.
- **Runs on:** this laptop. **Exit:** reproducible score on every metric.

### Phase 1 — Engine bake-off *(laptop)*
- Run every §4 candidate against the Phase 0 corpus. Measure; don't trust datasheets.
- Confirm licences — especially Surya.
- **Exit:** ranked table with real numbers on *your* documents.

### Phase 2 — Rebuild Stages 0–1 *(laptop; fixes the missing-text bug)*
- Delete the 8% crop → real page-boundary detection (C1).
- **Delete `clean_output()` entirely** (C2).
- Add orientation detect, deskew, dewarp, DPI normalization (C4).
- Single canonical coordinate frame (C12).
- Adopt the layout model — tables become structured objects with row/col indices (C6).
- Fix C11: one OCR pass, not two (also ~halves runtime).
- **Exit: coverage ≥ 99%.** Text may still be *wrong*, but it is no longer *missing*. **This phase alone should resolve the bulk of the "some text is missing" complaint — and it needs no GPU upgrade and no VLM.**

### Phase 3 — Recognition + fine-tuning *(GPU upgrade strongly recommended)*
- Script detection + per-script routing (C15).
- Gentle reversible preprocessing; no hard binarization of Indic text (C3).
- Replace Tesseract-as-primary with IndicPhotoOCR + Indic-OCR models (C5).
- **Fine-tune on the Phase 0 corpus + synthetic augmentation (§7) — the single biggest accuracy gain in the whole plan.**
- **Exit:** CER < 5% Kannada, < 1% English on clean scans, measured. *(Deliberately more conservative than a cloud stack would target — this is the honest local ceiling before review.)*

### Phase 4 — VLM reconciliation
- Stage 4 with crop tools + grammar-constrained JSON output.
- **A/B against no-reconciliation** to confirm it helps rather than hallucinates. Enforce the §5 guardrails.
- **Exit:** measured net CER improvement, and **zero** fabricated-text incidents on the eval set.

### Phase 5 — Confidence gate, review UI, export *(delivers the 100%)*
- Per-token confidence end to end (C13).
- Reviewer UI: image crop beside editable text, sorted by ascending confidence, keyboard-driven.
- Calibrate τ_high / τ_low against ground truth to hit a target review rate.
- Rebuild export: searchable PDF (A) + structured DOCX with **real Word tables** (B). Delete the floating-text-box path (C7, C8, C9, C10, C14).
- Embed per-script Noto fonts; add the missing `@font-face` rules.
- **Exit:** 100% accuracy on delivered documents at a review rate you can staff.

### Phase 6 — Production hardening
- Async job queue — 77 s/page synchronous is not viable under load.
- Worker pool, retries, dead-letter queue, idempotent job IDs.
- Structured logging; per-stage latency and accuracy metrics.
- Auth, tenant isolation, encryption at rest, retention policy, audit trail.
- **CI regression gate: no merge if CER worsens on the Phase 0 corpus.**

---

## 10. Decisions I need from you

1. **Volume?** Pages/month sizes the hardware and the review staffing.
2. **GPU upgrade approved?** ~$800 for a used 24 GB card. **If no, Phases 0–2 still deliver the missing-text fix, but Kannada accuracy will plateau well short of what's achievable and fine-tuning is largely off the table.** This is now the biggest open question.
3. **Commercial product or internal use?** Decides whether Surya's GPL-ish licence is usable.
4. **Which regional language is third**, after Kannada + English?
5. **Is a human review step acceptable?** If it must be fully automatic with no human ever, **100% is not achievable locally** and we should agree a realistic target instead (e.g. 95% with flagged uncertainty).
6. **Primary output: (A) searchable PDF, (B) editable DOCX, or both?** Sizes Phase 5.
7. **Handwriting in scope?** Materially harder, especially for Indic. Currently untested.

---

## 11. What I would NOT do

- **Don't tune the current preprocessing further.** C1/C2/C5 are structural — better `adaptiveThreshold` parameters cannot recover text that was cropped away, filtered out, or mis-decoded by the wrong engine.
- **Don't keep stock Tesseract as the primary Kannada engine.** ~15% WRR. Swap to IndicPhotoOCR + Indic-OCR models — free, and the largest easy win after Phase 2.
- **Don't add languages to `language=["kan","eng"]`.** It degrades all of them (C15).
- **Don't keep the floating-text-box DOCX.** Direct cause of the alignment complaint; cannot be made robust (§2).
- **Don't try to run a 7B VLM at full precision on 6 GB.** It will OOM on high-res pages. Quantize, or upgrade.
- **Don't build anything before Phase 0.** Without ground truth every change is a guess — and it's also your fine-tuning data, so it's the highest-value work available right now.

---

## Sources

- [IndicPhotoOCR — Bhashini-IITJ](https://github.com/Bhashini-IITJ/IndicPhotoOCR) · [docs](https://bhashini-iitj.github.io/IndicPhotoOCR/) · [demo](https://huggingface.co/spaces/Bhashini-IITJ/IndicPhotoOCR)
- [Bharat Scene Text: Dataset and Benchmark for Indian Language Scene Text](https://arxiv.org/pdf/2511.23071) — source of the §0.1 accuracy tables
- [Indic-OCR: Tesseract Models for Indian Languages](https://indic-ocr.github.io/tessdata/)
- [What is the Status of OCR in Indian languages?](https://milvus.io/ai-quick-reference/what-is-the-status-of-ocr-in-indian-languages)
- [PaddleOCR](https://paddleocr.dev/)
- [Docling: Efficient Open-Source Toolkit for Document Conversion](https://arxiv.org/pdf/2501.17887) · [Advanced Layout Analysis Models for Docling](https://arxiv.org/pdf/2509.11720)
- [PP-StructureV2: A Stronger Document Analysis System](https://arxiv.org/pdf/2210.05391)
- [dots.ocr: Self-Hosted Multilingual Document Parser](https://llm.co/llms/dots-ocr) · [dots.ocr GGUF](https://huggingface.co/anthonym21/dots.ocr-GGUF/blob/main/README.md)
- [deepseek-ocr.rs — multi-backend local OCR/VLM engine](https://github.com/TimmyOVO/deepseek-ocr.rs)
- [Best Vision Models You Can Run Locally, by GPU Tier](https://insiderllm.com/guides/vision-models-locally/)
- [Local AI Vision Tasks 2026: OCR with Open VLMs](https://localaimaster.com/blog/local-ai-vision-tasks)
- [Can OCR-VLMs Read Devanagari? Stress-Test Benchmark and Post-Correction Study (2026)](https://arxiv.org/pdf/2606.29213)
- [Hall of Multimodal OCR VLMs](https://huggingface.co/blog/prithivMLmods/multimodal-ocr-vlms)
- [Best Open Source OCR Tools & Models for Developers in 2026](https://unstract.com/blog/best-opensource-ocr-tools/)
