# Deploying OCR v3 on a GPU server

Written against the box this was first deployed on: Ubuntu 24.04, Quadro P600
(2048 MiB), driver 550.135 / CUDA 12.4, 8 cores, 15 GB RAM, `/sdb-disk` as the data
disk. Paths below assume the repo is cloned at `/home/administrator/dms_engine`.

Every step is idempotent — re-running it is safe.

---

## 1. System packages

```bash
sudo apt update
sudo apt install -y python3-venv \
    tesseract-ocr tesseract-ocr-eng tesseract-ocr-kan \
    ghostscript fonts-lohit-knda fonts-noto-core
tesseract --version && gs --version
```

Why each of these, because none of them is optional and all of them fail late:

| Package | Fails how, if missing |
|---|---|
| `tesseract-ocr` + `-eng` + `-kan` | `/health` reports `tesseract: false`; the legacy engine and the searchable-PDF download break. `ocrmypdf` is called with `language=["kan","eng"]`, so the Kannada pack is required, not optional |
| `ghostscript` | `/health` reports `ghostscript: false`; searchable PDFs cannot be built |
| `fonts-lohit-knda` / `fonts-noto-core` | **The cruel one.** Recognition succeeds, then rendering raises `no Kannada-capable font found` — so the page has already paid its full recognition cost before failing |

## 2. Python dependencies

```bash
cd /home/administrator/dms_engine
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

`requirements.txt` came from a `pip freeze` on a Windows machine and needed two
corrections, both already committed:

- `opencv-python` **removed**. It is the desktop build and needs `libGL`, which a
  server does not have, so it would fail at import even if pip accepted it. The code
  makes no `cv2` GUI calls, so `opencv-python-headless` is correct and sufficient.
  Having both pinned alongside `numpy==1.26.4` also made the file unresolvable, since
  headless 4.13 requires numpy ≥ 2.
- `python-multipart` **added**. FastAPI needs it for every `UploadFile` endpoint and
  it was absent. Without it the engine does not start at all — the import raises at
  the `@app.post("/extract/raw")` decorator, before uvicorn binds a port. It is
  invisible to any scan of the engine's own imports because FastAPI imports it
  internally.

## 3. Ollama and the model

```bash
curl -fsSL https://ollama.com/install.sh | sh     # should print "NVIDIA GPU installed"
ollama pull AuditAid/PaddleOCR-VL-1.6-0.9B
```

Then apply the tuning in [`ollama-override.conf`](ollama-override.conf):

```bash
sudo systemctl edit ollama.service      # paste the [Service] block from that file
sudo systemctl daemon-reload && sudo systemctl restart ollama
systemctl show ollama.service -p Environment      # confirm all five took
```

**Do not smoke-test with `ollama run <model> "hi"`.** PaddleOCR-VL is
image-in/text-out; given a bare text prompt it has nothing to read and emits pages
of garbage that look like a corrupt download. Use `verify_deploy.py` below, which
sends a real document.

## 4. Workspace directories

```bash
sudo mkdir -p /sdb-disk/ocr-workspace /sdb-disk/ocr-cache
sudo chown -R administrator:administrator /sdb-disk/ocr-workspace /sdb-disk/ocr-cache
```

Both default to a path inside the git working tree. Left alone, per-page scratch
files and an unbounded recognition cache accumulate on the root disk until the
machine stops — not just the engine.

## 5. The service

```bash
sudo cp /home/administrator/dms_engine/deploy/dms-ocr.service \
        /etc/systemd/system/dms-ocr.service
sudo systemctl daemon-reload
sudo systemctl enable --now dms-ocr
systemctl status dms-ocr --no-pager
journalctl -u dms-ocr -n 30 --no-pager
```

## 6. Lock the port down — do not skip this

The engine has **no authentication**. Bound on `0.0.0.0`, anyone who finds port 8080
can queue work on your GPU and read whatever they upload back out of it.

```bash
sudo ufw allow OpenSSH
sudo ufw allow from 38.247.130.64 to any port 8080 proto tcp   # the DMS app server
sudo ufw --force enable
sudo ufw status numbered
```

`38.247.130.64` is the DMS application server, the only host that needs to reach
this. Ollama on 11434 is left alone: it listens on localhost only, and the engine
talks to it there.

## 7. Verify

```bash
cd /home/administrator/dms_engine
./venv/bin/python verify_deploy.py --cold
```

One command, and it exits non-zero if anything is actually wrong. It checks the
health flags individually, reports where the model is really running, confirms the
workspace is off the root disk, sends `ocr/test_doc2.pdf` (a real Kannada scan)
through the endpoint DMS will call, and prints the per-page cost.

`--cold` clears the recognition cache first. Without it a repeat run returns in
about 1.6 seconds and looks 50× faster than reality — the cache is keyed by crop
content and shared across jobs, so the same document is nearly free the second time.

**Cost scales with the number of detected lines, not with "a page".** Every detected
line or block is a separate model call, so a sparse page and a dense one differ by
several times. Measured on this hardware: a 15-line synthetic invoice took **83s**,
about 5.5s per line. `ocr/test_doc2.pdf` detects 49 lines, so expect it to take
**minutes**, not 80 seconds — quoting a flat per-page figure got two verification runs
cancelled in the belief they had hung.

For planning, use the per-line figure against your own documents rather than a
pages-per-day number taken from someone else's page.

A warning about GPU placement being ~41% is expected and explained in
`ollama-override.conf`.

## 8. Point a tenant at it

Nothing routes here until you say so. In the super admin portal, **Setting → OCR**:

1. **Register engine** → `http://<this-server>:8080/process/text`
2. **Test** — confirms the engine answers and has everything it needs
3. Assign one tenant to it and leave everyone else on the default

To roll back, set that tenant to *Follow the default*, or disable the engine, which
diverts every tenant pinned to it on their next page without unpicking assignments.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| `ModuleNotFoundError: docx_generator` | Started from the repo root. `WorkingDirectory` must be `ocr/` — `main.py` imports its siblings flat |
| `RuntimeError: Form data requires "python-multipart"` | Dependencies not reinstalled after the requirements fix |
| `no Kannada-capable font found`, after a long pause | Font packages missing. `/health` shows `font_file: null`, and would have told you before you spent the recognition time |
| Every page returns empty text | Ollama down. `/health` shows `ollama_up: false` |
| A page returns in ~1.6s | Cache hit, not real work. Run `verify_deploy.py --cold` |
| Pages fail after ~300s in DMS | **The real risk on this hardware.** The Operator backend posts with `timeout=300`, chosen when v2 answered in seconds. At ~5.5s per detected line a 55-line page reaches 300s, so dense scans can time out in DMS while succeeding here. Measure a representative page before cutting a tenant over; if it lands near 300s the timeout has to become per-engine |
| Disk filling | `OCR_WORK_DIR` / `OCR_CACHE_DIR` not set, so both are inside the repo on `/` |
