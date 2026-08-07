import cv2
import numpy as np
from PIL import Image, ImageOps
import pytesseract

img_path = r"c:\Users\avin4\Desktop\AGENDA 424TH B M DT 23-03-2022 H G M L\Resim000006.jpg"

def paper_crop_and_test():
    pimg = Image.open(img_path)
    pimg = ImageOps.exif_transpose(pimg)
    img = cv2.cvtColor(np.array(pimg), cv2.COLOR_RGB2BGR)
    
    # 1. Edge detection to find the paper
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edged = cv2.Canny(blurred, 50, 150)
    
    # Dilate to connect edges
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    edged = cv2.dilate(edged, kernel, iterations=3)
    
    contours, _ = cv2.findContours(edged.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours:
        # Get largest contour (the paper)
        c = max(contours, key=cv2.contourArea)
        x, y, w, h = cv2.boundingRect(c)
        
        # Crop to the actual paper, skipping 15px to avoid the colored edge itself
        img = img[y+15:y+h-15, x+15:x+w-15]
        gray = gray[y+15:y+h-15, x+15:x+w-15]
        print(f"Cropped to document contour: {x},{y} {w}x{h}")
    
    # Now that we cropped strictly to the paper, adaptive thresholding won't see blue folder ridges
    blurred_bg = cv2.GaussianBlur(gray, (0, 0), sigmaX=60)
    blurred_bg = np.where(blurred_bg == 0, 1, blurred_bg).astype(np.float32)
    normalized = (gray.astype(np.float32) / blurred_bg * 220)
    gray = np.clip(normalized, 0, 255).astype(np.uint8)

    gray = cv2.medianBlur(gray, 3)
    
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    
    # Gentler adaptive thresholding
    binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 41, 15)
    
    # Run Tesseract with strict configuration to avoid mixed language noise
    config = r'-l kan+eng --oem 1 --psm 6'
    text = pytesseract.image_to_string(binary, config=config)
    
    with open("test_output_contour.txt", "w", encoding="utf-8") as f:
        f.write(text)
    print("Done")

paper_crop_and_test()
