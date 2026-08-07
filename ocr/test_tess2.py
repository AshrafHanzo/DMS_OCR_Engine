import cv2
import numpy as np
from PIL import Image, ImageOps
import pytesseract
import time

img_path = r"c:\Users\avin4\Desktop\AGENDA 424TH B M DT 23-03-2022 H G M L\Resim000006.jpg"

def test_preprocess():
    pimg = Image.open(img_path)
    pimg = ImageOps.exif_transpose(pimg)
    img = cv2.cvtColor(np.array(pimg), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape

    # Crop dark borders heavily
    gray = gray[100:h-100, 100:w-100]

    # Shadow removal
    blurred_bg = cv2.GaussianBlur(gray, (0, 0), sigmaX=60)
    blurred_bg = np.where(blurred_bg == 0, 1, blurred_bg).astype(np.float32)
    normalized = (gray.astype(np.float32) / blurred_bg * 220)
    gray = np.clip(normalized, 0, 255).astype(np.uint8)

    # Median Blur to remove salt/pepper (preserves edges)
    gray = cv2.medianBlur(gray, 3)

    # CLAHE
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)

    # Adaptive thresholding (Gentler block size)
    binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 41, 15)

    # Despeckle the binary image (remove tiny black dots on white background)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel) # Open removes small noise

    cv2.imwrite("test_adaptive_gentle.png", binary)

    # Run Tesseract with --psm 6 (Assume a single uniform block of text)
    config = r'-l kan+eng --oem 1 --psm 6 -c preserve_interword_spaces=1'
    text = pytesseract.image_to_string(binary, config=config)
    
    with open("test_output_gentle.txt", "w", encoding="utf-8") as f:
        f.write(text)
    print("Done testing Gentle Adaptive")
        
test_preprocess()
