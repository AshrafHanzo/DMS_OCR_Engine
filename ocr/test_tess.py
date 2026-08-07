import os
import cv2
import numpy as np
from PIL import Image, ImageOps
import pytesseract
import time

img_path = os.environ.get("OCR_TEST_IMAGE", "test_page.jpg")

def test_preprocess():
    pimg = Image.open(img_path)
    pimg = ImageOps.exif_transpose(pimg)
    img = cv2.cvtColor(np.array(pimg), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape

    # Crop
    dark_thresh = 80
    top, bottom, left, right = 0, h, 0, w
    for r in range(h):
        if np.mean(gray[r, :]) > dark_thresh: top = r; break
    for r in range(h-1, -1, -1):
        if np.mean(gray[r, :]) > dark_thresh: bottom = r+1; break
    for c in range(w):
        if np.mean(gray[:, c]) > dark_thresh: left = c; break
    for c in range(w-1, -1, -1):
        if np.mean(gray[:, c]) > dark_thresh: right = c+1; break
    if (bottom - top) > h * 0.4 and (right - left) > w * 0.4:
        gray = gray[top:bottom, left:right]

    # Shadow removal
    blurred_bg = cv2.GaussianBlur(gray, (0, 0), sigmaX=80)
    blurred_bg = np.where(blurred_bg == 0, 1, blurred_bg).astype(np.float32)
    normalized = (gray.astype(np.float32) / blurred_bg * 240)
    gray = np.clip(normalized, 0, 255).astype(np.uint8)

    # Median Blur to kill salt-and-pepper dirt
    gray = cv2.medianBlur(gray, 3)

    # Otsu thresholding instead of adaptive
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # Denoise with morphological closing (fills in broken characters)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

    cv2.imwrite("test_otsu.png", binary)

    # Run Tesseract
    config = r'-l kan+eng --oem 1 --psm 3 -c preserve_interword_spaces=1'
    text = pytesseract.image_to_string(binary, config=config)
    
    with open("test_output.txt", "w", encoding="utf-8") as f:
        f.write(text)
    print("Done testing Otsu")
        
test_preprocess()
