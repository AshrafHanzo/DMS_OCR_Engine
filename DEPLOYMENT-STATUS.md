# OCR Engine v3 — status, findings and what remains

Written 2026-08-07. Read this before resuming the deployment; it records what was
verified rather than what was assumed, so none of it needs re-deriving.

Companion to `DEPLOY.txt`, which the original author wrote. That document is
accurate about the CODE — every claim in it was checked against the source and all
held. It is wrong about the TARGET MACHINE, because it assumes x86 + Ubuntu 22/24 +
Python 3.12, and the intended server is none of those. See "The target server" below.

---

## What this repo is

The v3 OCR engine, taken from the working tree the original author shared, not
cloned from his GitHub.

**That distinction matters.** His repo (`mageshwaroffic-ship-it/doc_engine1`) does
NOT contain the v3 work — verified:

| File | His git | This repo |
|---|---|---|
| `ocr/aligned_pipeline.py` | absent | present |
| `ocr/ensemble.py` | absent | present |
| `ocr/tune_recog.py` | absent | present |
| `ocr/bakeoff.py` | absent | present |
| PaddleOCR-VL in `main.py` | 0 matches | present |

His last commit (`d1b7c39`) is v2. He upgraded locally and never pushed. **This
repository is the only copy of v3 in any git**, including his — worth telling him.

His original `.git` is preserved at `office/dms_engine-upstream-git-backup`.

### What v3 adds over v2

- **PaddleOCR-VL-1.6-0.9B** recognition (`DEFAULT_MODEL`, `aligned_pipeline.py:25`),
  served over HTTP by **Ollama** on `localhost:11434`. No PaddlePaddle, paddleocr
  or torch dependency — "Paddle" is only the model's lineage.
- **`aligned_pipeline.py`** — layout-preserving engine: detect page, deskew, detect
  line boxes, recognise each line, Telugu→Kannada codepoint shift (+0x80, because
  the model has no Kannada and emits Telugu), inpaint the original text away, redraw
  at the same position.
- **`/extract` gained `engine=`**, defaulting to `"aligned"` — the default
  behaviour changed. `engine="legacy"` is the old Tesseract path.
- **`ensemble.py`** — combines PaddleOCR-VL with Tesseract. Its docstring measures
  52.6% vs 41.8% on different lines, so combining should beat both. **It is not
  imported anywhere.** Probably the cheapest accuracy win available.
- `bakeoff.py`, `tune_recog.py` — benchmarking and preprocessing sweeps.

---

## Fixes already applied here

| Fix | Why |
|---|---|
| `normalise()` unpack | Returned 6 values, `main.py:504` unpacked 4 — every "edit text then download DOCX" returned 500 |
| `requirements-server.txt` | The old file **omits PyMuPDF entirely**, which `aligned_pipeline` imports as `fitz`, so every PDF upload 500s. Also specifies `opencv-python` (needs libGL, absent on servers) instead of `-headless`, and leaves Pillow unpinned — and Pillow does the text measuring that decides font size |
| CORS | Was `allow_origins=["*"]` **with** `allow_credentials=True`, which browsers reject outright |
| UI served by the API | `app.js` hardcoded `localhost:8000`, so any remote browser resolved that to its own machine |
| `run_in_threadpool` ×5 | `process_page`/`run_ocrmypdf` block for up to ~140s inside async handlers; one upload froze every other client |
| Cache thread-safety | `_CACHE` was rebound per request while worker threads wrote to it; two uploads discarded each other's entries and `json.dump` could raise "dictionary changed size during iteration". Now load-once, locked, atomic temp-file write |
| `/health` | Reports `font_file`, `raqm`, `pillow`, `ollama_up`, `model`, `tesseract`, `ghostscript` — this is how server-matches-local gets proven rather than assumed |
| `OCR_PORT`, default 8080 | 8000 and 8001 are taken on the target box |
| Author's machine paths | 22 doc references and 8 scripts hardcoded `c:\Users\avin4\...`; now `<REPO>` and env-driven |
| Repo hygiene | 7,195 files → 46. The upstream `.gitignore` was **UTF-16LE**, which git cannot parse, so every rule was silently inert and the whole venv was tracked |

---

## Not done yet

**1. Font vendoring (`DEPLOY.txt` §6).** The server will load a different font than
the author's Windows machine. Font size is *measured* — `assign_font_sizes()` shrinks
until the text fits its box — so a different font file gives different `font_px` and a
different DOCX. This is a **licensing decision**, not a technical one:

- **Option A:** copy `Nirmala.ttc` + `NirmalaB.ttf` from Windows. Output stays
  byte-identical. But Nirmala UI is a Microsoft font — confirm the licence.
- **Option B:** Noto Sans Kannada (SIL OFL). Licence-clean, reproducible anywhere.
  Output shifts once, then local == server forever. Must be used on BOTH machines.

Either way the rule is one font file used on both machines.

**2. The skew bug (`DEPLOY.txt` §14A).** Pre-existing, affects local too. Line boxes
are detected in deskewed coordinates; `render()` computes the correction into
`b["orig_cx"]/b["orig_cy"]` and **nothing ever reads it** — `write_docx` uses the raw
`b["x"]/b["y"]`. So DOCX text sits rotated off the background, error growing toward
the page edges. Only `*_overlay.png` is correct. Deploying as-is reproduces this
faithfully; fixing it changes output, so it is a deliberate separate step.

**3. `ensemble.py` is not wired in.** See above — likely the cheapest accuracy gain.

---

## The target server — verified, and it is not what DEPLOY.txt assumes

`ssh ubuntu@103.148.1.182 -p 22` → hostname `LAB-PC1`

**It is an NVIDIA Jetson AGX Orin, not a cloud GPU server.**

| | Value |
|---|---|
| Board | `t186ref`, L4T R35.4.1 = **JetPack 5.1.2** |
| Arch | **aarch64** |
| OS | **Ubuntu 20.04** |
| Python | **3.8.10** |
| CUDA | 11.4 |
| RAM | 61 GB (~32 available) |
| Disk | **57.8 GB eMMC, 6.2 GB free (89% full)** |
| Second disk | **none** — no NVMe. `zram0-7` are RAM-backed swap, not storage |
| Ollama | not installed |

`nvidia-smi` does not exist — that is **normal on Jetson**, not a broken driver.

### What already runs on it

| Port | Process | Service |
|---|---|---|
| 8000 | `doc_engine/server.py` | **Multilingual Document Extraction Engine v4.0.0** — PaddleOCR + Qwen, GPU, 8 languages. **This is what the DMS calls.** |
| 8001 | `doc_engine/basha_scans/backend/main.py` | BHASHA SCANS 0.1.0 |

Both live under `~/doc_engine`. BHASHA SCANS is a **subproject inside it**, which is
why the shared folder mixed them together.

Note the engine on :8000 is a **different codebase** from this repo — it exposes
`/process`, `/process/text`, `/process_ai`, `/languages`; this repo exposes
`/extract`, `/formatted`, `/aligned`. They are not two versions of one thing.

### The gap

| | Current | Needed | Status |
|---|---|---|---|
| Python | 3.8.10 | ≥3.9 (Pillow 12.2, PyMuPDF 1.28) | ❌ hard blocker |
| OS | Ubuntu 20.04 | 22.04 / 24.04 | ❌ |
| Disk free | 6.2 GB | 20 GB+ | ❌ short ~14 GB |
| Arch | aarch64 | x86 assumed | ⚠️ some wheels build from source |
| CUDA | 11.4 | 12.x preferred by Ollama | ⚠️ |
| Ollama + model | absent | required | ❌ |
| RAM | 61 GB | 8 GB+ | ✅ |
| Port 8080 | free | free | ✅ |

Still unverified on the box — one command closes it:

```bash
tesseract --list-langs 2>/dev/null || echo "tesseract: MISSING"
gs --version 2>/dev/null || echo "ghostscript: MISSING"
dpkg -l | grep -c libraqm || echo "libraqm: MISSING"
```

`libraqm` matters disproportionately: without it Kannada conjuncts and matras render
wrong even with the correct font file.

---

## Two things worth doing regardless of which path is chosen

**1. Get `~/doc_engine` into git — this is the real risk.**

The OCR engine the DMS depends on exists in exactly one place: a 89%-full eMMC on a
lab device. It is not in any repository we have. If that disk fails, or the board is
re-flashed, **it is gone permanently**. The author shared `doc_engine1`, which is a
different application.

```bash
ls -d ~/doc_engine/.git 2>/dev/null && (cd ~/doc_engine && git remote -v) \
  || echo "NOT in git - only copy is on this disk"
```

**2. Free ~6.5 GB. No downtime, worth doing anyway.**

What is consuming the 20 GB of `doc_engine`:

| Size | Path |
|---|---|
| 3.8 G | `models/qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf` |
| 3.8 G | `models/qwen2.5-7b-instruct-q4_0-00001-of-00002.gguf` |
| 1.7 G | `venv/.../paddle/fluid/libpaddle.so` |
| 1.4 G | `models/got-ocr2/model.safetensors` |
| 1.3 G | `torchvision_build/.git/.../pack` |
| 658 M | `models/qwen...q4_k_m-00002-of-00002.gguf` |
| 526 M | `basha_scans/frontend/Paddle/.git/.../pack` |
| 428 M | `models/qwen...q4_0-00002-of-00002.gguf` |

**Qwen2.5-7B is present twice, in two quantisations** (`q4_k_m` ≈ 4.5 GB and `q4_0`
≈ 4.2 GB). Only one can be loaded. **Confirm which before deleting either:**

```bash
grep -rn "qwen\|gguf\|q4_" ~/doc_engine/server.py | head -20
```

Then the unused quantisation (~4.2 GB), `torchvision_build/.git` (1.3 GB),
`jetpack_backup_*.tar.gz` (689 M), the torch wheel (163 M), `code_arm64.deb`
(100 M) and `pytorch_build.log` (17 M) come to roughly 6.5 GB, taking free space
from 6.2 GB to about 12.7 GB.

---

## The three options

| | A. Fix in place | B. Re-flash JetPack 6 | C. x86 host |
|---|---|---|---|
| Python ≥3.9 | build from source (~1–2 h) | ✅ 3.10 included | ✅ 3.12 |
| Disk | free ~6.5 GB → 12.7 GB | ~40 GB after clean install | as provisioned |
| Downtime | none | **hours** | none |
| Physical access | no | **yes — USB + host PC running SDK Manager** | no |
| Risk to live services | low | **destroys both** | none |
| Rebuild v2 + BHASHA | no | **yes, from scratch** | no |
| aarch64 wheel pain | yes | reduced | none |
| Ollama | awkward on Tegra | better | native |

There is **no JetPack with Python 3.12** — 22.04 / 3.10 is the ceiling, which does
satisfy the requirements even though DEPLOY.txt asks for 3.12.

Option B cannot be done over SSH, and must not be attempted until `doc_engine` is
backed up.

**Recommendation: C.** The engine already runs on x86 (the author develops on
Windows). Register it as a second OCR server and point ONE tenant at it — the
per-tenant OCR routing in the DMS exists for exactly this. Everyone else stays on
:8000, untouched. It can even run on a laptop initially, since evaluating whether v3
is better should not require buying hardware.

---

## Connecting v3 to the DMS when it is running

The DMS calls `OCR_API_URL` → `/process/text`. **This engine has no such endpoint** —
it exposes `/extract`, `/extract/raw`, `/formatted`, `/download/{id}`,
`/aligned/{id}`. So it is not a drop-in replacement for :8000.

Use the OCR routing already built into the DMS instead:

- `DMS.ocr_servers` — registry, already seeded with the live `103.148.1.182:8000`
- `DMS.tenant_ocr_assignment` — which tenant uses which server

Register v3 as a second server and assign one tenant to it. Whatever calls it will
need to use `/extract` rather than `/process/text`, so the Operator backend's OCR
call needs a per-server endpoint path, or an adapter.

Verify a deployment with `/health` on both machines and diff the JSON —
`font_file`, `raqm` and `pillow` must match or alignment will differ.
