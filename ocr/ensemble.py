"""
Per-line ensemble: run several engines on the same crop, then pick the most
plausible candidate WITHOUT ground truth, using Kannada structural validity.

Measured on test_doc2: PaddleOCR-VL(+te->kn) 52.6% and Tesseract 41.8% win on
DIFFERENT lines, so a correct chooser should beat both.

The plausibility score is the interesting part. Kannada is an abugida with hard
structural rules, so malformed output is detectable without knowing the answer:
  * a vowel sign / matra must attach to a consonant
  * a virama must sit between consonants
  * Latin letters scattered inside Kannada words are OCR noise
  * long runs of the same character are hallucination
"""
import re, unicodedata

KN_LO, KN_HI = 0x0C80, 0x0CFF
KN_CONS = set(chr(c) for c in range(0x0C95, 0x0CBA))          # ka..ha
KN_INDEP_V = set(chr(c) for c in range(0x0C85, 0x0C95))       # a..au
KN_MATRA = set(chr(c) for c in range(0x0CBE, 0x0CD7))         # dependent signs
KN_VIRAMA = "್"
KN_ANUSVARA = set("ಂಃ")
KN_DIGIT = set(chr(c) for c in range(0x0CE6, 0x0CF0))


def is_kn(ch):
    return KN_LO <= ord(ch) <= KN_HI


def plausibility(s):
    """0..1 - higher means structurally better-formed. No ground truth needed."""
    s = unicodedata.normalize("NFC", s or "")
    if not s.strip():
        return 0.0
    chars = [c for c in s if not c.isspace()]
    if not chars:
        return 0.0

    kn = [c for c in chars if is_kn(c)]
    lat = [c for c in chars if c.isascii() and c.isalpha()]
    dig = [c for c in chars if c.isdigit()]
    other = [c for c in chars if not is_kn(c) and not c.isalnum()]

    score = 1.0

    # 1. orphan matras: a dependent sign with no consonant before it
    orphans = 0
    for i, c in enumerate(s):
        if c in KN_MATRA or c == KN_VIRAMA:
            prev = s[i - 1] if i else ""
            if prev not in KN_CONS and prev not in KN_MATRA and prev != KN_VIRAMA:
                orphans += 1
    if kn:
        score *= max(0.0, 1 - 2.5 * orphans / max(len(kn), 1))

    # 2. a virama should be followed by a consonant (conjunct) or end a word
    bad_virama = sum(1 for i, c in enumerate(s)
                     if c == KN_VIRAMA and i + 1 < len(s)
                     and s[i + 1] not in KN_CONS and not s[i + 1].isspace())
    if kn:
        score *= max(0.0, 1 - 1.5 * bad_virama / max(len(kn), 1))

    # 3. Latin letters mixed inside a mostly-Kannada string = noise
    if kn and lat:
        frac = len(lat) / (len(kn) + len(lat))
        if frac < 0.5:                        # minority Latin => contamination
            score *= max(0.0, 1 - 1.8 * frac)

    # 4. junk punctuation density
    score *= max(0.0, 1 - 1.2 * len(other) / len(chars))

    # 5. absurd repeats ("or/ or/ or/", "aaaa")
    if re.search(r"(.)\1{4,}", s):
        score *= 0.3
    toks = s.split()
    if len(toks) > 4 and len(set(toks)) <= max(2, len(toks) // 4):
        score *= 0.2

    # 6. mixed Indic scripts is always wrong (Telugu leaking through)
    te = sum(1 for c in chars if 0x0C00 <= ord(c) <= 0x0C7F)
    if te:
        score *= 0.25

    # 7. reward having real content
    if len(chars) < 3:
        score *= 0.5

    return max(0.0, min(1.0, score))


def choose(candidates, prefer_script=None):
    """candidates: list of (engine_name, text). Returns (engine, text, score, table)."""
    table = []
    for name, txt in candidates:
        p = plausibility(txt)
        kn = sum(1 for c in (txt or "") if is_kn(c))
        lat = sum(1 for c in (txt or "") if c.isascii() and c.isalpha())
        # if the region is known to be Kannada, require Kannada content
        if prefer_script == "kn" and kn == 0 and lat > 2:
            p *= 0.35
        if prefer_script == "lat" and lat == 0 and kn > 2:
            p *= 0.35
        table.append((name, txt, round(p, 3), kn, lat))
    table.sort(key=lambda r: -r[2])
    best = table[0]
    return best[0], best[1], best[2], table


def guess_script(box_texts):
    """Majority script across a page, used to set per-line expectations."""
    kn = sum(sum(1 for c in t if is_kn(c)) for t in box_texts)
    lat = sum(sum(1 for c in t if c.isascii() and c.isalpha()) for t in box_texts)
    return "kn" if kn > lat else "lat"


if __name__ == "__main__":
    # quick self-check on real outputs captured from the bake-off
    cases = [
        ("ref4", "kn", [
            ("tess", "4) ನಮ್ಮ ಪತ್ರ ದಿನಾಂಕ: 17/10/2019."),          # correct
            ("vl",   "4) ನಮ್ಮಿ ಐತ್ರ ದಿನಾಂಕ: 17/10/2019."),          # near
            ("qwen", "4) సంబంధిత కార్యక్రమాలు తేదీ: 17/10/2019."),   # Telugu -> must lose
        ]),
        ("title", "kn", [
            ("tess", ", = aul ee ಹಲ್ಲ ಗ MES ಕಂಪಣ ನಯಿಖುತ ಹಲ್ಬ ಇವರ pc aa"),
            ("vl",   "ಮೌನ್ಯ, ವ್ಯವಸ್ಥಾಲು - ನೀದೇಣೀಶ್ವರು, ವೆಟ್ಟಿ ಜಿನ್ನದೇಣು ಗಣ ಸಂಜನ್ಮನಿ ನೀಯಮಿತ್ತ ವಿಟ್ರ"),
        ]),
        ("contact", "lat", [
            ("tess", "ಗ: 08537 - 275034 Tele Fax - 275054 - Email : hgmisrmhr@gmail.com"),
            ("vl",   "Ph : 08537 - 275034 Tele Fax - 275054 - Email : hgmlsrmhr@gmail.com"),
        ]),
        ("noise", "kn", [
            ("vl", "/m/ or/ or/ or/ or/ or/ or/ or/ or/ or/ or/"),
            ("tess", ""),
        ]),
    ]
    for name, script, cands in cases:
        eng, txt, sc, tbl = choose(cands, script)
        print(f"\n=== {name} (expect {script}) -> picked '{eng}' score={sc}")
        for n, t, p, kn, la in tbl:
            print(f"   {p:5.3f} {n:5s} kn={kn:3d} lat={la:3d} | {t[:70]}")
