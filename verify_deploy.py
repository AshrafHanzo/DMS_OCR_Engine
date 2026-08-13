"""Verify an OCR v3 deployment end to end, and print a verdict.

Run this ON the engine server after deploying. It replaces the handful of separate
curl / ollama ps / nvidia-smi checks that are easy to run in the wrong order or
misread, and it fails loudly on the things that are quietly wrong rather than
obviously broken -- a model that silently fell back to CPU, a missing Kannada font
that only surfaces at render time, a workspace filling the root disk.

    cd /home/administrator/dms_engine
    ./venv/bin/python verify_deploy.py

    --url    engine base URL          (default http://localhost:8080)
    --doc    document to test with    (default ocr/test_doc2.pdf, a real Kannada scan)
    --cold   clear the recognition cache first, so the timing is a true cold cost
             rather than a cache hit. Use this when you want the number that
             decides throughput.
    --wait   seconds to wait for the engine to answer, default 60. It is safe to
             run this immediately after "systemctl start dms-ocr": the engine
             imports cv2, fitz and ocrmypdf before uvicorn binds the port, which
             takes several seconds on this hardware.

Exit status is 0 only if every check passed, so it is safe to chain.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))

# This script prints recognised Kannada. Under a non-UTF-8 stdout -- a bare cron
# environment, a pipe on some systems, PowerShell's default codepage -- printing it
# raises UnicodeEncodeError and the whole verification dies at the last step, after
# every check has already passed. Degrade the unprintable characters instead.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

GREEN, RED, YELL, DIM, OFF = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"
if not sys.stdout.isatty():
    GREEN = RED = YELL = DIM = OFF = ""

results = []


def check(label, ok, detail="", fail_detail="", warn_only=False):
    """Record one check.

    detail      is always shown -- the measured value.
    fail_detail is shown only when the check fails -- what it means and what to do.

    Kept separate because a single field ends up printing "PASS  Kannada recognised
    (96 chars)   0 Kannada characters -- the model is not reading the script it was
    chosen for", which is both alarming and false.

    warn_only=True means 'worth knowing', not 'deployment broken'.
    """
    if ok:
        mark, colour = "PASS", GREEN
    elif warn_only:
        mark, colour = "WARN", YELL
    else:
        mark, colour = "FAIL", RED
    note = detail if ok else "   ".join(x for x in (detail, fail_detail) if x)
    print(f"  {colour}{mark}{OFF}  {label}" + (f"   {DIM}{note}{OFF}" if note else ""))
    results.append((label, ok, warn_only))


def section(title):
    print(f"\n{title}")
    print("-" * len(title))


def get_json(url, timeout=10):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def post_file(url, field, path, timeout=900):
    """Multipart POST with no third-party dependency, so this script runs even if
    the venv is half-installed -- which is exactly when you need it most."""
    boundary = "----verify" + os.urandom(8).hex()
    with open(path, "rb") as f:
        payload = f.read()
    body = b"".join([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="{field}"; '
        f'filename="{os.path.basename(path)}"\r\n'.encode(),
        b"Content-Type: application/octet-stream\r\n\r\n",
        payload, b"\r\n", f"--{boundary}--\r\n".encode(),
    ])
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace"), round(time.time() - t0, 1), None
    except urllib.error.HTTPError as e:
        return e.read().decode("utf-8", "replace"), round(time.time() - t0, 1), e.code


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8080")
    ap.add_argument("--doc", default=os.path.join(HERE, "ocr", "test_doc2.pdf"))
    ap.add_argument("--cold", action="store_true")
    # Long enough to cover a cold start of the engine's imports on this hardware,
    # short enough that a genuinely dead service is reported promptly.
    ap.add_argument("--wait", type=int, default=60,
                    help="seconds to wait for the engine to answer (default 60)")
    args = ap.parse_args()
    base = args.url.rstrip("/")

    print(f"verifying {base}")
    print(f"document  {args.doc}")

    # ── 1. the engine answers, and its own self-report is clean ──────────────
    section("1. engine health")
    # Wait rather than fail instantly. `systemctl enable --now` returns as soon as
    # systemd has forked the process, but this engine imports cv2, fitz and ocrmypdf
    # before uvicorn binds the port -- several seconds. Checking immediately after a
    # start reports "the engine is not running" about an engine that is starting
    # perfectly well, which sends you off reading journals for no reason.
    h, deadline, waited = None, time.time() + args.wait, False
    while True:
        try:
            h = get_json(f"{base}/health")
            break
        except Exception as e:
            if time.time() >= deadline:
                print(f"  {RED}FAIL{OFF}  cannot reach {base}/health   "
                      f"{type(e).__name__}: {e}")
                print(f"\n{RED}no answer after {args.wait}s.{OFF} Check it with:")
                print("  systemctl status dms-ocr --no-pager")
                print("  journalctl -u dms-ocr -n 40 --no-pager")
                sys.exit(1)
            if not waited:
                print(f"  {DIM}waiting for the engine to bind "
                      f"(up to {args.wait}s)…{OFF}")
                waited = True
            time.sleep(2)
    if waited:
        check("engine came up while waiting", True,
              f"took a moment to import; that is normal")

    check("engine responds", h.get("status") == "ok", str(h.get("status")))
    # Each of these fails at a DIFFERENT point in the pipeline, which is why they
    # are checked separately rather than as one "is it healthy" boolean.
    check("Ollama reachable", bool(h.get("ollama_up")), h.get("ollama_url", ""),
          fail_detail="recognition returns empty text for every page without it")
    check("Kannada font present", bool(h.get("font_file")),
          os.path.basename(h.get("font_file") or ""),
          fail_detail="render raises 'no Kannada-capable font found' AFTER paying "
                      "the full OCR cost. apt install fonts-lohit-knda")
    check("tesseract on PATH", bool(h.get("tesseract")), "",
          fail_detail="apt install tesseract-ocr tesseract-ocr-eng tesseract-ocr-kan")
    check("ghostscript on PATH", bool(h.get("ghostscript")), "",
          fail_detail="apt install ghostscript -- needed for the searchable PDF")
    print(f"  {DIM}model: {h.get('model')}   pillow {h.get('pillow')}"
          f"   raqm {h.get('raqm')}{OFF}")

    # ── 2. where the model is actually running ───────────────────────────────
    # Ollama falls back to CPU silently. On a small card this is the difference
    # between usable and not, and nothing in the engine's own health reveals it.
    section("2. model placement")
    try:
        ps = get_json(h.get("ollama_url", "http://localhost:11434") + "/api/ps")
        loaded = ps.get("models") or []
        if not loaded:
            check("model resident", False,
                  "nothing loaded yet -- placement is only visible after a request; "
                  "this is re-checked at the end", warn_only=True)
        for m in loaded:
            size = m.get("size") or 0
            vram = m.get("size_vram") or 0
            pct = round(100 * vram / size) if size else 0
            check(f"{m.get('name')} on GPU: {pct}%", pct >= 99,
                  f"{vram/1e9:.2f}GB of {size/1e9:.2f}GB in VRAM",
                  fail_detail="the remainder runs on CPU, which is the dominant "
                              "cost per page on a small card",
                  warn_only=True)
            print(f"  {DIM}context {m.get('context_length') or '?'}"
                  f"   expires {m.get('expires_at', '?')}{OFF}")
    except Exception as e:
        check("Ollama /api/ps readable", False, f"{type(e).__name__}: {e}",
              warn_only=True)

    # ── 3. the workspace is bounded and not on the root disk ─────────────────
    section("3. storage")
    work = os.environ.get("OCR_WORK_DIR") or os.path.join(HERE, "ocr", "ocr_workspace")
    cache = os.environ.get("OCR_CACHE_DIR") or os.path.join(HERE, "ocr", "ocr_workspace")
    for label, path in (("work dir", work), ("cache dir", cache)):
        exists = os.path.isdir(path)
        free = shutil.disk_usage(path).free / 1e9 if exists else 0
        check(f"{label} usable", exists and free > 5,
              f"{path}  {free:.0f}GB free" if exists else f"{path}  does not exist")
        # A workspace on / will eventually stop the whole box, not just the engine.
        # Only meaningful on the deployment target. On Windows st_dev does not
        # describe mount points, so reporting PASS here would be a false assurance.
        if exists and os.name != "nt":
            same_as_root = os.stat(path).st_dev == os.stat("/").st_dev
            check(f"{label} is off the root disk", not same_as_root, "",
                  fail_detail="a filling workspace will stop the whole machine, not "
                              "just the engine. point OCR_WORK_DIR / OCR_CACHE_DIR "
                              "at a data disk",
                  warn_only=True)
    cache_file = os.path.join(cache, ".ocr_cache.json")
    if os.path.exists(cache_file):
        mb = os.path.getsize(cache_file) / 1e6
        try:
            n = len(json.load(open(cache_file, encoding="utf-8")))
        except Exception:
            n = "?"
        print(f"  {DIM}recognition cache: {n} entries, {mb:.1f}MB{OFF}")
        if args.cold:
            os.remove(cache_file)
            print(f"  {YELL}--cold: removed the cache so the timing below is a "
                  f"true cold cost{OFF}")

    # ── 4. detection diagnostics on a real page ──────────────────────────────
    # /extract saves every upload as input.jpg, so it cannot read a PDF. Render
    # page 1 first. This is also how DMS should feed it if it ever wants positions.
    section("4. detection on a real page")
    if not os.path.exists(args.doc):
        check("test document present", False, args.doc)
    else:
        png = args.doc
        if args.doc.lower().endswith(".pdf"):
            png = os.path.join(work, "verify_page1.png")
            try:
                import fitz
                d = fitz.open(args.doc)
                d[0].get_pixmap(dpi=200).save(png)
                d.close()
            except Exception as e:
                check("render page 1 for /extract", False, f"{type(e).__name__}: {e}")
                png = None
        if png:
            body, secs, code = post_file(f"{base}/extract", "image", png)
            if code:
                check("/extract", False, f"HTTP {code}: {body[:180]}")
            else:
                d = json.loads(body).get("diagnostics", {})
                det = d.get("lines_detected") or 0
                ren = d.get("lines_rendered") or 0
                lost = det - ren
                check("/extract returns diagnostics", det > 0, f"in {secs}s")
                # Some loss is correct: the ink guard drops handwriting and specks
                # that the model would otherwise invent text for. A large fraction
                # means printed content is going missing with nothing to signal it.
                check(f"lines kept {ren}/{det}", bool(det) and lost / det <= 0.25,
                      f"{lost} dropped ({100*lost/max(det,1):.0f}%)",
                      fail_detail="the ink guard should drop only handwriting and "
                                  "specks. this much loss means printed text is "
                                  "going missing with nothing to signal it",
                      warn_only=True)
                print(f"  {DIM}skew {d.get('skew_deg')}deg   "
                      f"alignment median {d.get('alignment_median_pct')}%   "
                      f"page {d.get('image_size')}{OFF}")

    # ── 5. the endpoint DMS will actually call ───────────────────────────────
    section("5. /process/text -- the endpoint DMS calls")
    if os.path.exists(args.doc):
        text, secs, code = post_file(f"{base}/process/text", "file", args.doc)
        if code:
            check("/process/text", False, f"HTTP {code}: {text[:200]}")
        else:
            check("returns plain text, not JSON",
                  not text.lstrip().startswith(("{", "[")), "",
                  fail_detail="DMS stores this body verbatim, so a JSON envelope "
                              "would land in extracted_text as-is")
            check("text is not empty", len(text.strip()) > 20,
                  f"{len(text)} chars, {len(text.splitlines())} lines")
            kan = sum(1 for c in text if 0x0C80 <= ord(c) <= 0x0CFF)
            check(f"Kannada recognised ({kan} chars)", kan > 0, "",
                  fail_detail="no Kannada at all -- either this page has none, or "
                              "the model is not reading the script it was chosen for",
                  warn_only=True)
            print(f"\n  {DIM}--- first 12 lines ---{OFF}")
            for ln in text.splitlines()[:12]:
                print(f"  {DIM}| {ln[:96]}{OFF}")
            print(f"\n  {'cold' if args.cold else 'possibly cached'} "
                  f"time: {GREEN}{secs}s{OFF} per page"
                  + (f"   -> {3600/secs:.0f} pages/hour, ~{86400/secs:.0f}/day flat out"
                     if secs > 0 else ""))
            if not args.cold and secs < 10:
                print(f"  {YELL}that was a cache hit, not real work. re-run with "
                      f"--cold for the throughput number.{OFF}")

    # ── 6. placement again, now that a real request has run ──────────────────
    section("6. model placement after real work")
    try:
        ps = get_json(h.get("ollama_url", "http://localhost:11434") + "/api/ps")
        for m in ps.get("models") or []:
            size, vram = m.get("size") or 0, m.get("size_vram") or 0
            pct = round(100 * vram / size) if size else 0
            check(f"{m.get('name')} on GPU: {pct}%", pct >= 99,
                  f"{vram/1e9:.2f}GB of {size/1e9:.2f}GB in VRAM", warn_only=True)
            check("model stays resident between pages",
                  str(m.get("expires_at", "")).startswith("9999")
                  or m.get("expires_at") in (None, ""),
                  str(m.get("expires_at", "")),
                  fail_detail="set OLLAMA_KEEP_ALIVE=-1, or every page re-pays the "
                              "model load",
                  warn_only=True)
    except Exception:
        pass
    try:
        smi = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader"], capture_output=True, text=True, timeout=15)
        if smi.returncode == 0:
            print(f"  {DIM}{smi.stdout.strip()}{OFF}")
    except Exception:
        pass

    # ── verdict ─────────────────────────────────────────────────────────────
    # Deduped: GPU placement is deliberately checked twice, before and after real
    # work, because the answer differs. Listing it twice in the verdict just reads
    # like two separate problems.
    def uniq(seq):
        seen, out = set(), []
        for x in seq:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out

    fails = uniq([l for l, ok, w in results if not ok and not w])
    warns = uniq([l for l, ok, w in results if not ok and w])
    print("\n" + "=" * 68)
    if fails:
        print(f"{RED}{len(fails)} CHECK(S) FAILED{OFF}")
        for l in fails:
            print(f"  - {l}")
    if warns:
        print(f"{YELL}{len(warns)} warning(s){OFF} -- deployment works, worth knowing:")
        for l in warns:
            print(f"  - {l}")
    if not fails:
        print(f"{GREEN}deployment is good{OFF}"
              + (" (with the warnings above)" if warns else ""))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
