"""
Recognition tuning: sweep input preprocessing variants for PaddleOCR-VL and
score each against ground truth, to find the best crop treatment.

The model is fixed (no Kannada support, so output is transliterated from Telugu).
What we CAN control is what we feed it and how we map the output back.
"""
import base64, json, os, time, unicodedata, urllib.request
import cv2, numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OLLAMA = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL = "AuditAid/PaddleOCR-VL-1.6-0.9B"
OUTD = os.path.join(HERE, "aligned_out")

GT = {
 "title":   "ಮಾನ್ಯ ವ್ಯವಸ್ಥಾಪಕ ನಿರ್ದೇಶಕರು, ಹಟ್ಟಿ ಚಿನ್ನದ ಗಣಿ ಕಂಪನಿ ನಿಯಮಿತ ಹಟ್ಟಿ ಇವರ ನಡವಳಿಗಳು",
 "ref3":    "3) ರಿಟ್ ಅರ್ಜಿದಾರರ ಮನವಿ ದಿನಾಂಕ 08-08-2019.",
 "ref4":    "4) ನಮ್ಮ ಪತ್ರ ದಿನಾಂಕ: 17/10/2019.",
 "contact": "Ph : 08537 - 275034 Tele Fax - 275054 - Email : hgmlsrmhr@gmail.com",
}
REGIONS = {
 "title":   (0.10, 0.95, 0.2480, 0.2790),
 "ref3":    (0.14, 0.50, 0.3660, 0.3810),
 "ref4":    (0.14, 0.42, 0.3830, 0.3990),
 "contact": (0.18, 0.78, 0.2160, 0.2330),
}


def norm(s):
    return unicodedata.normalize("NFC", " ".join(s.split()))


def cer(ref, hyp):
    r, h = list(norm(ref)), list(norm(hyp))
    prev = list(range(len(h) + 1))
    for i, rc in enumerate(r, 1):
        cur = [i] + [0] * len(h)
        for j, hc in enumerate(h, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rc != hc))
        prev = cur
    return prev[-1] / max(len(r), 1)


# ---------------------------------------------------------- transliteration
# Telugu and Kannada blocks are +0x80 aligned, but a few slots differ.
# These are corrections applied after the block shift.
POST = {
    "ಳ": "ಳ",      # LLA is valid in Kannada
}
# frequent visual confusions seen in this corpus (Kannada targets)
CONFUSE = [
    ("ೊ", "ೋ"), ("ೆ", "ೇ"),          # short/long vowel signs
    ("ಣ", "ನ"), ("ಳ", "ಲ"),          # retroflex/dental confusion
    ("ಜ", "ಚ"), ("ಡ", "ದ"),
    ("ಶ", "ಸ"), ("ಷ", "ಸ"),
    ("ಬ", "ವ"), ("ಭ", "ಬ"),
]


def te_to_kn(s, aggressive=False):
    out = "".join(chr(ord(c) + 0x80) if 0x0C00 <= ord(c) <= 0x0C7F else c for c in s)
    out = unicodedata.normalize("NFC", out)
    for a, b in POST.items():
        out = out.replace(a, b)
    return out


# ------------------------------------------------------------- preprocessing
def pre_plain(c, scale):
    return cv2.resize(c, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)


def pre_sharp(c, scale):
    up = cv2.resize(c, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    blur = cv2.GaussianBlur(up, (0, 0), 1.2)
    return cv2.addWeighted(up, 1.6, blur, -0.6, 0)


def pre_clahe(c, scale):
    up = cv2.resize(c, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    lab = cv2.cvtColor(up, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    l = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(l)
    return cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)


def pre_gray_flat(c, scale):
    g = cv2.cvtColor(c, cv2.COLOR_BGR2GRAY)
    bg = cv2.GaussianBlur(g, (0, 0), sigmaX=25)
    flat = np.clip(g.astype(np.float32) / np.maximum(bg, 1) * 210, 0, 255).astype(np.uint8)
    up = cv2.resize(flat, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    return cv2.cvtColor(up, cv2.COLOR_GRAY2BGR)


def pre_lanczos(c, scale):
    return cv2.resize(c, None, fx=scale, fy=scale, interpolation=cv2.INTER_LANCZOS4)


VARIANTS = [
    ("cubic x2",      lambda c: pre_plain(c, 2)),
    ("cubic x3",      lambda c: pre_plain(c, 3)),
    ("cubic x4",      lambda c: pre_plain(c, 4)),
    ("lanczos x3",    lambda c: pre_lanczos(c, 3)),
    ("sharpen x3",    lambda c: pre_sharp(c, 3)),
    ("sharpen x4",    lambda c: pre_sharp(c, 4)),
    ("clahe x3",      lambda c: pre_clahe(c, 3)),
    ("grayflat x3",   lambda c: pre_gray_flat(c, 3)),
    ("grayflat x4",   lambda c: pre_gray_flat(c, 4)),
]

_cache = {}
CPATH = os.path.join(OUTD, ".tune_cache.json")
if os.path.exists(CPATH):
    _cache = json.load(open(CPATH, encoding="utf-8"))


def ocr(img):
    import hashlib
    ok, buf = cv2.imencode(".png", img)
    raw = buf.tobytes()
    k = hashlib.sha1(raw).hexdigest()
    if k in _cache:
        return _cache[k]
    body = json.dumps({"model": MODEL, "prompt": "Text Recognition:",
                       "images": [base64.b64encode(raw).decode()], "stream": False,
                       "options": {"temperature": 0, "num_predict": 512}}).encode()
    req = urllib.request.Request(f"{OLLAMA}/api/generate", data=body,
                                headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        out = json.loads(r.read()).get("response", "").strip().replace("\n", " ")
    _cache[k] = out
    return out


def main():
    img = cv2.imread(os.path.join(OUTD, "test_doc2_deskewed.png"))
    H, W = img.shape[:2]
    crops = {}
    for name, (x0, x1, y0, y1) in REGIONS.items():
        crops[name] = img[int(H*y0):int(H*y1), int(W*x0):int(W*x1)]

    rows = []
    for label, fn in VARIANTS:
        accs, kn_accs = {}, []
        for name, c in crops.items():
            t0 = time.time()
            hyp = te_to_kn(ocr(fn(c)))
            a = max(0.0, 1 - cer(GT[name], hyp)) * 100
            accs[name] = a
            if name != "contact":
                kn_accs.append(a)
        kn = float(np.mean(kn_accs))
        rows.append((label, kn, accs["contact"], accs))
        print(f"{label:14s} kannada={kn:5.1f}%  latin={accs['contact']:5.1f}%   "
              + "  ".join(f"{k}={v:.0f}" for k, v in accs.items()))

    json.dump(_cache, open(CPATH, "w", encoding="utf-8"), ensure_ascii=False)
    print("\n" + "="*74)
    print(f"{'variant':16s} {'Kannada':>9s} {'Latin':>8s}")
    print("="*74)
    for label, kn, la, _ in sorted(rows, key=lambda r: -r[1]):
        print(f"{label:16s} {kn:8.1f}% {la:7.1f}%")
    best = max(rows, key=lambda r: r[1])
    print(f"\nBEST for Kannada: {best[0]}  ({best[1]:.1f}%)")


if __name__ == "__main__":
    main()
