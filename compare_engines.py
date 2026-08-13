"""Run one page through the v2 and v3 engines and compare what came back.

WHY THIS EXISTS

Switching a tenant to v3 costs real time: ~189s a page on a Quadro P600 against a
couple of seconds on the Jetson. That is only worth paying if the text is better, and
nobody has actually compared them on the same document -- v3's own DEPLOY.txt quotes
71.6% Kannada, but that figure is against v3's LEGACY Tesseract path, not against the
Jetson, which runs PaddleOCR with a Qwen stage and both `en` and `ka` loaded.

So this posts the same page to both and puts the answers next to each other.

WHAT IT CAN AND CANNOT TELL YOU

There is no ground truth here, so it does NOT declare a winner on accuracy. It reports
what is measurable without one:

  - how much text each produced, and how much of it is Kannada
  - hard tokens that are either right or wrong: emails, phone numbers, long digit
    runs, ALL-CAPS Latin phrases. These are objectively checkable against the scan
  - characters from scripts the document does not contain -- a Chinese glyph in a
    Kannada document is a hallucination, not a reading
  - repeated-unit runs, the signature of a model looping on a blank region
  - what each cost in seconds

Then it prints both texts, aligned, for you to judge the Kannada yourself. A script
cannot do that part, and pretending otherwise would be worse than not trying.

    ./venv/bin/python compare_engines.py                        # ocr/test_doc2.pdf
    ./venv/bin/python compare_engines.py --doc /tmp/scan.pdf
    ./venv/bin/python compare_engines.py --v2 http://host:8000/process/text
"""

import argparse
import os
import re
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BOLD, DIM, GREEN, YELL, RED, OFF = (
    "\033[1m", "\033[2m", "\033[32m", "\033[33m", "\033[31m", "\033[0m")
if not sys.stdout.isatty():
    BOLD = DIM = GREEN = YELL = RED = OFF = ""

KANNADA = range(0x0C80, 0x0D00)
DEVANAGARI = range(0x0900, 0x0980)
# Scripts a Kannada/English government document does not contain. Anything here is the
# model inventing, not reading -- v3 produced a lone CJK glyph on one run.
FOREIGN = {
    "CJK": range(0x4E00, 0xA000),
    "Hiragana/Katakana": range(0x3040, 0x3100),
    "Hangul": range(0xAC00, 0xD7A4),
    "Cyrillic": range(0x0400, 0x0500),
    "Arabic": range(0x0600, 0x0700),
}

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE_RE = re.compile(r"\b\d{5}-\d{5,7}\b|\b0\d{4}-\d{5,7}\b")
DIGITS_RE = re.compile(r"\b\d{4,}\b")
CAPS_RE = re.compile(r"\b[A-Z][A-Z&.\- ]{6,}[A-Z]\b")
# 1-6 characters repeated four or more times: a model looping rather than reading.
REPEAT_RE = re.compile(r"((?=[^\W_]*[^\W_])[\s\S]{1,6}?)\1{3,}")


def post(url: str, path: str, field: str = "file", timeout: int = 900):
    boundary = "----cmp" + os.urandom(8).hex()
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
        return e.read().decode("utf-8", "replace"), round(time.time() - t0, 1), \
            f"HTTP {e.code}"
    except Exception as e:
        return "", round(time.time() - t0, 1), f"{type(e).__name__}: {e}"


def unwrap(body: str) -> str:
    """Both engines are asked for text, but v2 may answer with JSON.

    DMS stores this body verbatim, so if an engine returns JSON the raw string is what
    would land in extracted_text. Unwrapping here compares the TEXT rather than the
    envelope -- but the envelope itself is reported separately, because it decides
    whether that engine can be pointed at DMS at all.
    """
    s = body.strip()
    if not s.startswith(("{", "[", '"')):
        return body
    try:
        import json
        data = json.loads(s)
    except Exception:
        return body
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        for k in ("extracted_text", "text", "result", "data", "output"):
            v = data.get(k)
            if isinstance(v, str):
                return v
        return "\n".join(str(v) for v in data.values() if isinstance(v, str))
    if isinstance(data, list):
        return "\n".join(str(x) for x in data)
    return body


def count_in(text: str, rng) -> int:
    return sum(1 for c in text if ord(c) in rng)


def profile(text: str) -> dict:
    foreign = {}
    for name, rng in FOREIGN.items():
        n = count_in(text, rng)
        if n:
            foreign[name] = n
    return {
        "chars": len(text),
        "lines": len([l for l in text.splitlines() if l.strip()]),
        "kannada": count_in(text, KANNADA),
        "devanagari": count_in(text, DEVANAGARI),
        "latin": sum(1 for c in text if c.isascii() and c.isalpha()),
        "digits": sum(1 for c in text if c.isdigit()),
        "emails": sorted(set(EMAIL_RE.findall(text))),
        "phones": sorted(set(PHONE_RE.findall(text))),
        "numbers": sorted(set(DIGITS_RE.findall(text))),
        "caps": sorted(set(m.strip() for m in CAPS_RE.findall(text))),
        "foreign": foreign,
        "loops": [m.group(0)[:40] for m in REPEAT_RE.finditer(text)][:5],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", default=os.path.join(HERE, "ocr", "test_doc2.pdf"))
    ap.add_argument("--v2", default="http://103.148.1.182:8000/process/text",
                    help="the Jetson, in production today")
    ap.add_argument("--v3", default="http://localhost:8080/process/text")
    ap.add_argument("--timeout", type=int, default=900)
    args = ap.parse_args()

    if not os.path.exists(args.doc):
        sys.exit(f"no such document: {args.doc}")
    print(f"{BOLD}document{OFF}  {args.doc} "
          f"({os.path.getsize(args.doc) / 1024:.0f} KB)")

    results = {}
    for label, url in (("v2 (Jetson)", args.v2), ("v3 (GPU)", args.v3)):
        print(f"\n{BOLD}{label}{OFF}  {url}")
        # v3 can take minutes on a small card; say so before the silence starts, but
        # only for v3 -- claiming the Jetson will take minutes is just wrong.
        if "v3" in label:
            print(f"  {DIM}posting… ~3.9s per detected line on a P600, so a dense "
                  f"page is minutes. not stuck.{OFF}")
        else:
            print(f"  {DIM}posting…{OFF}")
        body, secs, err = post(url, args.doc, timeout=args.timeout)
        if err:
            print(f"  {RED}{err}{OFF}  {body[:200]}")
            results[label] = None
            continue
        text = unwrap(body)
        envelope = "JSON" if body.strip().startswith(("{", "[")) else "plain text"
        p = profile(text)
        p["secs"], p["envelope"], p["text"] = secs, envelope, text
        results[label] = p
        print(f"  {GREEN}{secs}s{OFF}, {envelope}, {p['chars']} chars, "
              f"{p['lines']} lines")

    live = {k: v for k, v in results.items() if v}
    if len(live) < 2:
        print(f"\n{YELL}only one engine answered, so there is nothing to compare.{OFF}")
        sys.exit(1)

    a, b = list(live)
    A, B = live[a], live[b]

    print(f"\n{BOLD}{'':<26}{a:>20}{b:>20}{OFF}")
    print("-" * 66)
    for label, key in (("seconds", "secs"), ("characters", "chars"),
                       ("non-empty lines", "lines"),
                       ("Kannada characters", "kannada"),
                       ("Devanagari characters", "devanagari"),
                       ("Latin letters", "latin"), ("digits", "digits")):
        av, bv = A[key], B[key]
        mark = ""
        if isinstance(av, (int, float)) and av != bv and key != "secs":
            mark = f"  {GREEN}<--{OFF}" if av > bv else f"  {GREEN}-->{OFF}"
        print(f"{label:<26}{av:>20}{bv:>20}{mark}")
    print(f"{'reply format':<26}{A['envelope']:>20}{B['envelope']:>20}")

    # More text is not better text. The arrow marks which produced more, and that is
    # all it means -- one engine may simply be inventing more.
    print(f"\n{DIM}the arrow marks which produced MORE, not which is more accurate.{OFF}")

    print(f"\n{BOLD}hard tokens — these are checkable against the scan by eye{OFF}")
    for label, key in (("emails", "emails"), ("phone numbers", "phones"),
                       ("ALL-CAPS phrases", "caps"), ("4+ digit numbers", "numbers")):
        both = sorted(set(A[key]) & set(B[key]))
        only_a = sorted(set(A[key]) - set(B[key]))
        only_b = sorted(set(B[key]) - set(A[key]))
        print(f"\n  {label}")
        if both:
            print(f"    {GREEN}both agree{OFF}: {', '.join(both)[:150]}")
        if only_a:
            print(f"    {YELL}only {a}{OFF}: {', '.join(only_a)[:150]}")
        if only_b:
            print(f"    {YELL}only {b}{OFF}: {', '.join(only_b)[:150]}")
        if not (both or only_a or only_b):
            print(f"    {DIM}neither found any{OFF}")

    print(f"\n{BOLD}signs of invention{OFF}")
    for label, p in ((a, A), (b, B)):
        notes = []
        if p["foreign"]:
            notes.append("characters from " + ", ".join(
                f"{k} ({v})" for k, v in p["foreign"].items())
                + " — scripts this document does not contain")
        if p["loops"]:
            notes.append(f"{len(p['loops'])} repeated-unit run(s), e.g. "
                         + repr(p["loops"][0]))
        if notes:
            for n in notes:
                print(f"  {YELL}{label}{OFF}: {n}")
        else:
            print(f"  {GREEN}{label}{OFF}: none detected")

    print(f"\n{BOLD}both texts, for you to judge the Kannada{OFF}")
    for label, p in ((a, A), (b, B)):
        print(f"\n{BOLD}--- {label} ---{OFF}")
        lines = [l for l in p["text"].splitlines() if l.strip()]
        for i, l in enumerate(lines[:45], 1):
            print(f"  {DIM}{i:>3}{OFF} {l[:110]}")
        if len(lines) > 45:
            print(f"  {DIM}… {len(lines) - 45} more line(s){OFF}")

    print(f"\n{BOLD}what to look for{OFF}")
    print("  A script cannot score Kannada accuracy without ground truth, so read the")
    print("  two above against the actual scan. The questions that decide it:")
    print("   - are Kannada words readable words, or plausible-looking nonsense?")
    print("   - are the numbers right? A wrong figure in a financial document is")
    print("     worse than a missing one, because nothing flags it.")
    print("   - is reading order sane, or are columns interleaved?")
    print(f"   - is {b if B['secs'] > A['secs'] else a}'s extra time "
          f"({abs(A['secs'] - B['secs']):.0f}s a page) worth the difference you see?")


if __name__ == "__main__":
    main()
