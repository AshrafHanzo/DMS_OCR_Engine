"""
Recognition bake-off: score several engines on the SAME line crops against
hand-transcribed ground truth, so engine choice is measured not guessed.

Usage:
    python bakeoff.py                # run all available engines
    python bakeoff.py --engines vl,qwen4b,tess
"""
import argparse, base64, json, os, re, subprocess, sys, time, unicodedata, urllib.request
import cv2, numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OLLAMA = os.environ.get("OLLAMA_URL", "http://localhost:11434")
SRC = os.path.join(HERE, "aligned_out", "_bakeoff_crops")

# ---- hand-transcribed ground truth, read from full-resolution crops ----------
GT = {
 "title":   "ಮಾನ್ಯ ವ್ಯವಸ್ಥಾಪಕ ನಿರ್ದೇಶಕರು, ಹಟ್ಟಿ ಚಿನ್ನದ ಗಣಿ ಕಂಪನಿ ನಿಯಮಿತ ಹಟ್ಟಿ ಇವರ ನಡವಳಿಗಳು",
 "company": "ಹಟ್ಟಿ ಚಿನ್ನದ ಗಣಿ ಕಂಪನಿ ನಿಯಮಿತ",
 "ref3":    "3) ರಿಟ್ ಅರ್ಜಿದಾರರ ಮನವಿ ದಿನಾಂಕ 08-08-2019.",
 "ref4":    "4) ನಮ್ಮ ಪತ್ರ ದಿನಾಂಕ: 17/10/2019.",
 "contact": "Ph : 08537 - 275034 Tele Fax - 275054 - Email : hgmlsrmhr@gmail.com",
 "govt":    "( A Govt. of Karnataka Undertaking)",
}
# region boxes as fractions of the page (x0,x1,y0,y1)
REGIONS = {
 "title":   (0.10, 0.95, 0.2480, 0.2790),
 "company": (0.22, 0.72, 0.1000, 0.1250),
 "ref3":    (0.14, 0.50, 0.3660, 0.3810),
 "ref4":    (0.14, 0.42, 0.3830, 0.3990),
 "contact": (0.18, 0.78, 0.2160, 0.2330),
 "govt":    (0.26, 0.62, 0.1830, 0.1990),
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


def te_to_kn(s):
    return "".join(chr(ord(c) + 0x80) if 0x0C00 <= ord(c) <= 0x0C7F else c for c in s)


def make_crops():
    os.makedirs(SRC, exist_ok=True)
    img = cv2.imread(os.path.join(HERE, "aligned_out", "test_doc2_deskewed.png"))
    if img is None:                     # fall back to the raw embedded scan
        import fitz
        d = fitz.open(os.path.join(HERE, "test_doc2.pdf"))
        info = d.extract_image(d[0].get_images(full=True)[0][0])
        img = cv2.imdecode(np.frombuffer(info["image"], np.uint8), cv2.IMREAD_COLOR)
    H, W = img.shape[:2]
    out = {}
    for name, (x0, x1, y0, y1) in REGIONS.items():
        c = img[int(H * y0):int(H * y1), int(W * x0):int(W * x1)]
        c = cv2.resize(c, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        p = os.path.join(SRC, f"{name}.png")
        cv2.imwrite(p, c)
        out[name] = p
    return out


# ------------------------------------------------------------------- engines
def ollama_ocr(model, path, prompt):
    b64 = base64.b64encode(open(path, "rb").read()).decode()
    body = json.dumps({"model": model, "prompt": prompt, "images": [b64],
                       "stream": False,
                       "options": {"temperature": 0, "num_predict": 512}}).encode()
    req = urllib.request.Request(f"{OLLAMA}/api/generate", data=body,
                                headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.loads(r.read()).get("response", "").strip().replace("\n", " ")


INDIC_TESSDATA = os.environ.get(
    "INDIC_TESSDATA",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "indic_tessdata"))


def tesseract(path, langs="kan+eng", tessdata=None, psm="7"):
    exe = os.environ.get("TESSERACT_EXE", r"C:\Tesseract-OCR	esseract.exe")
    if not os.path.exists(exe):
        exe = "tesseract"
    cmd = [exe, path, "stdout", "-l", langs, "--oem", "1", "--psm", psm]
    if tessdata:
        cmd += ["--tessdata-dir", tessdata]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=300)
        out = r.stdout.decode("utf-8", "replace").strip().replace("\n", " ")
        if not out and r.stderr:
            return "__ERR__ " + r.stderr.decode("utf-8", "replace")[:160]
        return out
    except Exception as e:
        return f"__ERR__ {e}"


ENGINES = {
 "vl":     dict(label="PaddleOCR-VL-1.6-0.9B (+te→kn)",
                fn=lambda p: te_to_kn(ollama_ocr("AuditAid/PaddleOCR-VL-1.6-0.9B", p,
                                                 "Text Recognition:"))),
 "vl_raw": dict(label="PaddleOCR-VL-1.6-0.9B (raw)",
                fn=lambda p: ollama_ocr("AuditAid/PaddleOCR-VL-1.6-0.9B", p,
                                        "Text Recognition:")),
 "qwen4b": dict(label="Qwen3-VL 4B",
                fn=lambda p: ollama_ocr("qwen3-vl:4b", p,
                                        "Read the text in this image exactly as printed. "
                                        "Output only the text, no commentary.")),
 "tess":   dict(label="Tesseract 5.5 kan+eng (current 3.6MB)",
                fn=lambda p: tesseract(p, "kan+eng")),
 "indic":  dict(label="Tesseract + Indic-OCR kan (52MB)",
                fn=lambda p: tesseract(p, "kan+eng", INDIC_TESSDATA)),
 "indic_k": dict(label="Tesseract + Indic-OCR kan only",
                fn=lambda p: tesseract(p, "kan", INDIC_TESSDATA)),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engines", default="vl,vl_raw,qwen4b,tess")
    args = ap.parse_args()
    names = [e.strip() for e in args.engines.split(",") if e.strip() in ENGINES]

    crops = make_crops()
    print(f"crops: {', '.join(crops)}\n")

    results, table = {}, {}
    for en in names:
        spec = ENGINES[en]
        print(f"=== {spec['label']} ===")
        per = {}
        for region, path in crops.items():
            t0 = time.time()
            try:
                hyp = spec["fn"](path)
            except Exception as e:
                hyp = f"__ERR__ {e}"
            score = cer(GT[region], hyp)
            per[region] = dict(hyp=hyp, cer=round(score * 100, 1),
                               acc=round(max(0.0, 1 - score) * 100, 1),
                               secs=round(time.time() - t0, 1))
            print(f"  {region:8s} acc={per[region]['acc']:5.1f}%  {hyp[:76]}")
        results[en] = per
        kn = [r for k, r in per.items() if k not in ("contact", "govt")]
        la = [r for k, r in per.items() if k in ("contact", "govt")]
        table[en] = dict(label=spec["label"],
                         kannada=round(float(np.mean([x["acc"] for x in kn])), 1),
                         latin=round(float(np.mean([x["acc"] for x in la])), 1),
                         secs=round(float(np.mean([x["secs"] for x in per.values()])), 1))
        print()

    print("=" * 78)
    print(f"{'engine':38s} {'Kannada':>9s} {'Latin':>8s} {'s/line':>8s}")
    print("=" * 78)
    for en in sorted(table, key=lambda k: -table[k]["kannada"]):
        t = table[en]
        print(f"{t['label']:38s} {t['kannada']:8.1f}% {t['latin']:7.1f}% {t['secs']:7.1f}")

    with open(os.path.join(HERE, "aligned_out", "bakeoff.json"), "w", encoding="utf-8") as f:
        json.dump({"summary": table, "detail": results, "gt": GT}, f,
                  ensure_ascii=False, indent=1)
    print("\nwrote aligned_out/bakeoff.json")


if __name__ == "__main__":
    main()
