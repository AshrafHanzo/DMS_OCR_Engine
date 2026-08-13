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
    --just-restarted
             assert that the engine was restarted immediately before this ran, so its
             in-memory cache is empty. Needed because --cold cannot restart the service
             when running as the service's own user, and deleting the cache FILE does
             not clear what a running process already holds.
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
import threading
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


def post_file(url, field, path, timeout=900, heartbeat=None):
    """Multipart POST with no third-party dependency, so this script runs even if
    the venv is half-installed -- which is exactly when you need it most.

    Prints elapsed seconds while it waits. A page can take five minutes on a small card
    -- longer than that after an Ollama restart, because the model reloads before any
    recognition begins -- and five minutes of silence is indistinguishable from a hung
    script. It got a run cancelled, and then a second one queried as stuck when it was
    working correctly.
    """
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
    done = threading.Event()

    def tick():
        # Deliberately on stderr: stdout is what a caller might parse, and this is
        # progress for a human, not part of the report.
        while not done.wait(15):
            secs = int(time.time() - t0)
            sys.stderr.write(f"\r  {DIM}  … still working, {secs}s elapsed "
                             f"(a dense page is 200-300s on a small card){OFF}   ")
            sys.stderr.flush()

    # Only on a terminal. The ticks redraw a single line using a carriage return, which
    # is live progress for a person watching and litter in a log file or a CI capture.
    if heartbeat is None:
        heartbeat = sys.stderr.isatty()
    beat = None
    if heartbeat:
        beat = threading.Thread(target=tick, daemon=True)
        beat.start()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace"), round(time.time() - t0, 1), None
    except urllib.error.HTTPError as e:
        return e.read().decode("utf-8", "replace"), round(time.time() - t0, 1), e.code
    except Exception as e:
        # A timeout here is the answer, not a crash: the engine took longer than DMS
        # itself would wait, which is exactly what the caller needs to know.
        return "", round(time.time() - t0, 1), f"{type(e).__name__}: {e}"
    finally:
        done.set()
        if beat:
            beat.join(timeout=1)
            sys.stderr.write("\r" + " " * 78 + "\r")
            sys.stderr.flush()


def _restart_engine():
    """Restart dms-ocr so it drops its in-memory recognition cache.

    Returns (ok, explanation). Tried without sudo first, then with sudo -n: this script
    normally runs as the service's own user, which cannot restart it, and -n means a
    missing sudo right fails immediately instead of blocking on a password prompt in
    something meant to run unattended.
    """
    for cmd, label in ((["systemctl", "restart", "dms-ocr"], "systemctl"),
                       (["sudo", "-n", "systemctl", "restart", "dms-ocr"], "sudo -n")):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if r.returncode == 0:
                return True, label
            last = (r.stderr or r.stdout or "").strip().splitlines()
        except FileNotFoundError:
            last = ["systemctl not found -- is this a systemd host?"]
        except Exception as error:
            last = [f"{type(error).__name__}: {error}"]
    return False, (last[-1] if last else "restart failed") + \
        " (run this with sudo, or restart the service yourself first)"


def make_selftest_page(font_file, out_path):
    """Render a test page instead of shipping one.

    The document this script used by default, ocr/test_doc2.pdf, is a REAL client
    document -- a Karnataka government letter. It cannot go into a bundle handed to
    another customer, and the repository holding it cannot be made public for the same
    reason. So when it is absent, a page is drawn here using the Kannada font the engine
    itself reported, which also proves that font renders the script correctly.

    A rendered page is an EASIER test than a scan: no skew, no noise, no faint strokes.
    It proves the pipeline works end to end and that Kannada is recognised at all. It
    does not measure accuracy on real documents, and the output says so rather than
    letting a green result imply more than it should.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception as e:
        return None, f"Pillow unavailable: {e}"
    if not font_file or not os.path.exists(font_file):
        return None, "no Kannada font on this host, so a Kannada test cannot be drawn"

    lines = [
        ("ಕರ್ನಾಟಕ ಸರ್ಕಾರ", 54),      # Government of Karnataka
        ("GOVERNMENT OF KARNATAKA", 44),
        ("ದಾಖಲೆ ನಿರ್ವಹಣಾ ವ್ಯವಸ್ಥೆ", 40),  # Document Management System
        ("", 20),
        ("ಸಂಖ್ಯೆ: DMS/OCR/2026/0113", 36),                    # Number:
        ("ದಿನಾಂಕ: 13/08/2026", 36),                          # Date:
        ("", 20),
        ("Item                     Qty        Rate       Amount", 36),
        ("Scanning                 250       12.00      3000.00", 36),
        ("Recognition              250        8.50      2125.00", 36),
        ("Archival                   1     4500.00      4500.00", 36),
        ("Total                                         9625.00", 36),
        ("", 20),
        ("ಸಹಿ: ವ್ಯವಸ್ಥಾಪಕ ನಿರ್ದೇಶಕರು", 38),  # Sd/- Managing Director
        ("Email: dms@example.gov.in   Ph: 080-25710501", 34),
    ]
    img = Image.new("RGB", (1654, 2339), "white")
    d = ImageDraw.Draw(img)
    y = 150
    for text, size in lines:
        if text:
            try:
                f = ImageFont.truetype(font_file, size)
            except Exception as e:
                return None, f"cannot load {font_file}: {e}"
            d.text((130, y), text, fill=(15, 15, 15), font=f)
        y += size + 26
    d.line([(120, 128), (1534, 128)], fill=(15, 15, 15), width=3)
    try:
        img.save(out_path, dpi=(200, 200))
    except Exception as e:
        return None, f"cannot write {out_path}: {e}"
    return out_path, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8080")
    ap.add_argument("--doc", default=os.path.join(HERE, "ocr", "test_doc2.pdf"))
    ap.add_argument("--cold", action="store_true")
    # Long enough to cover a cold start of the engine's imports on this hardware,
    # short enough that a genuinely dead service is reported promptly.
    ap.add_argument("--wait", type=int, default=60,
                    help="seconds to wait for the engine to answer (default 60)")
    # For a caller that has ALREADY restarted the engine and knows nothing has been
    # processed since -- install.sh restarts it two steps before calling this. Without
    # it, that run would disclaim its own perfectly cold measurement, because this
    # script runs as the service user and cannot restart the service itself.
    ap.add_argument("--just-restarted", action="store_true",
                    help="the engine was restarted just before this ran, so its "
                         "in-memory cache is already empty")
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
    # Take these from /health, which the ENGINE answers, not from this script's own
    # environment. Run from an interactive shell the environment variables set in the
    # systemd unit are not present here, so the previous version reported the
    # in-repo defaults and warned about a root-disk problem that had been fixed at
    # deploy time. The engine is the only process that knows where it writes.
    engine_reported = bool(h.get("work_dir"))
    work = h.get("work_dir") or os.environ.get("OCR_WORK_DIR") or os.path.join(
        HERE, "ocr", "ocr_workspace")
    cache = h.get("cache_dir") or os.environ.get("OCR_CACHE_DIR") or os.path.join(
        HERE, "ocr", "ocr_workspace")
    if not engine_reported:
        print(f"  {YELL}this engine predates work_dir in /health, so these paths are "
              f"this shell's guess, not the service's. git pull on the engine.{OFF}")
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

    really_cold = False
    if args.cold:
        # DELETING THE FILE IS NOT ENOUGH.
        #
        # aligned_pipeline loads the cache once per process and guards it with
        # _CACHE_LOADED, so a running engine never re-reads the file. Removing it changes
        # nothing for the process that is about to serve this request -- which made
        # --cold report 8.5s and "10,165 pages/day" for a page that genuinely takes
        # minutes. A verification tool inventing a number 50x too good is worse than no
        # tool. The engine has to be restarted to forget.
        if os.path.exists(cache_file):
            os.remove(cache_file)
        if args.just_restarted:
            restarted, how = True, "caller restarted it"
        else:
            restarted, how = _restart_engine()
        if restarted:
            really_cold = True
            print(f"  {YELL}--cold: cache removed and the engine restarted ({how}), "
                  f"so it has forgotten what it had in memory{OFF}")
            # It has to bind again before section 4 posts to it.
            deadline2 = time.time() + args.wait
            while time.time() < deadline2:
                try:
                    get_json(f"{base}/health", timeout=5)
                    break
                except Exception:
                    time.sleep(2)
        else:
            print(f"  {RED}--cold could NOT make this measurement cold.{OFF} "
                  f"{how}\n"
                  f"  {YELL}The cache FILE was removed, but the running engine keeps it "
                  f"in memory, so the time below is a cache hit and not a throughput "
                  f"number. Restart the engine and re-run:{OFF}\n"
                  f"      sudo systemctl restart dms-ocr && sleep 20 && "
                  f"{sys.argv[0]} --cold")

    # ── 4. the endpoint DMS will actually call ───────────────────────────────
    section("4. /process/text -- the endpoint DMS calls")
    if os.path.exists(args.doc):
        # No fixed estimate: cost scales with how many lines the page has, and
        # each is a separate model call. A dense A4 scan is minutes, not seconds.
        print(f"  {DIM}pushing a real page through the model. every detected line is"
              f" a separate call, so a dense scan takes MINUTES on a small card —"
              f" test_doc2.pdf has 49 of them. leave it be.{OFF}")
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
            # Only a run that restarted the engine may call itself cold, and only a cold
            # run may be turned into a pages-per-day figure. A cache hit extrapolated to
            # a day is a fabricated capacity, and somebody will plan against it.
            label = "cold" if really_cold else (
                "CACHE HIT (not cold)" if secs < 30 else "possibly cached")
            print(f"\n  {label} time: {GREEN}{secs}s{OFF} per page"
                  + (f"   -> {3600/secs:.0f} pages/hour, ~{86400/secs:.0f}/day flat out"
                     if really_cold and secs > 0 else ""))
            if not really_cold:
                print(f"  {YELL}no throughput figure from this run{OFF} — the engine had "
                      f"the page's crops cached. For a real number:\n"
                      f"      sudo systemctl restart dms-ocr && sleep 20 && "
                      f"./venv/bin/python verify_deploy.py --cold")
            elif secs < 30:
                # Cold, restarted, and still fast enough to be suspicious. Say so rather
                # than reporting a flattering number without comment.
                print(f"  {YELL}that is unexpectedly fast for a cold run. Check the page "
                      f"really has as much text as you think.{OFF}")

    # ── 5. detection diagnostics, now nearly free from the cache ─────────────
    # /extract saves every upload as input.jpg, so it cannot read a PDF. Render
    # page 1 first. This is also how DMS should feed it if it ever wants positions.
    section("5. detection diagnostics (crops already cached)")
    generated = False
    if not os.path.exists(args.doc):
        # Absent in any bundle that excludes client documents, which is every bundle
        # given to a customer.
        import tempfile
        made, why = make_selftest_page(
            h.get("font_file"),
            os.path.join(tempfile.gettempdir(), "dms_ocr_selftest.png"))
        if made:
            args.doc, generated = made, True
            print(f"  {DIM}{os.path.basename(args.doc)} not present, so a Kannada test "
                  f"page was drawn with the engine's own font.{OFF}")
            print(f"  {YELL}a rendered page is an EASIER test than a scan -- it proves "
                  f"the pipeline and the font, not accuracy on real documents.{OFF}")
        else:
            check("a test document is available", False, why,
                  fail_detail=f"pass --doc /path/to/a/scan")
    if not os.path.exists(args.doc):
        pass
    else:
        png = args.doc
        if args.doc.lower().endswith(".pdf"):
            # A temp dir, NOT the engine's work_dir. Those paths now come from
            # /health, so with --url they describe the ENGINE's filesystem, which
            # this script may not share or be able to write to. Rendering there
            # worked only by accident when both ran on the same box.
            import tempfile
            png = os.path.join(tempfile.gettempdir(), "verify_page1.png")
            try:
                import fitz
                d = fitz.open(args.doc)
                page = d[0]
                # MIRROR aligned_pipeline.load_page EXACTLY, or the cache-reuse this
                # section depends on does not happen. load_page prefers the PDF's
                # EMBEDDED scan at its native resolution and only renders when there
                # is none. Rendering at some other dpi produces different pixels,
                # therefore different crops, therefore different cache keys -- and
                # this step would silently pay the full model cost a second time.
                imgs = page.get_images(full=True)
                if imgs:
                    info = d.extract_image(imgs[0][0])
                    tmp = os.path.join(tempfile.gettempdir(),
                                       "verify_page1." + (info.get("ext") or "png"))
                    with open(tmp, "wb") as f:
                        f.write(info["image"])
                    png = tmp
                else:
                    page.get_pixmap(dpi=300).save(png)   # load_page's own fallback
                d.close()
            except Exception as e:
                check("render page 1 for the diagnostics", False,
                      f"{type(e).__name__}: {e}")
                png = None
        if png:
            # Cheap now: the step above already recognised every crop on this
            # page, and the cache is keyed by crop content, so this re-reads them
            # rather than paying the model again. It still builds a DOCX, which is
            # CPU-only and a few seconds.
            print(f"  {DIM}reusing the cached crops from the step above — seconds,"
                  f" not minutes.{OFF}")
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

    # ── 6. placement again, now that a real request has run ──────────────────
    section("6. model placement after real work")
    try:
        ps = get_json(h.get("ollama_url", "http://localhost:11434") + "/api/ps")
        for m in ps.get("models") or []:
            size, vram = m.get("size") or 0, m.get("size_vram") or 0
            pct = round(100 * vram / size) if size else 0
            check(f"{m.get('name')} on GPU: {pct}%", pct >= 99,
                  f"{vram/1e9:.2f}GB of {size/1e9:.2f}GB in VRAM", warn_only=True)
            # OLLAMA_KEEP_ALIVE=-1 does not report a sentinel: Ollama returns a
            # real timestamp centuries out (observed 2318-11-23). Matching on "9999"
            # therefore reported a correctly configured server as misconfigured.
            # Anything more than a year ahead means resident.
            expires = str(m.get("expires_at", "") or "")
            try:
                resident = int(expires[:4]) > time.gmtime().tm_year + 1
            except ValueError:
                resident = not expires
            check("model stays resident between pages", resident,
                  expires[:19] or "no expiry reported",
                  fail_detail="set OLLAMA_KEEP_ALIVE=-1, or every page re-pays the "
                              "model load -- most of a minute on this card",
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
