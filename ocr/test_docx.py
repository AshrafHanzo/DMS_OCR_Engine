import ocrmypdf
from pdf2docx import Converter
import os

img_path = os.environ.get("OCR_TEST_IMAGE", "test_page.jpg")
pdf_path = "test_doc.pdf"
docx_path = "test_doc.docx"

if not os.path.exists(pdf_path):
    print("Running OCRmyPDF...")
    ocrmypdf.ocr(
        img_path,
        pdf_path,
        language=["eng", "kan"],
        image_dpi=300,
        force_ocr=True,
        tesseract_oem=1,
        tesseract_pagesegmode=3,
        jobs=1
    )

print("Converting to DOCX...")
cv = Converter(pdf_path)
cv.convert(docx_path)
cv.close()
print(f"Done! Created {docx_path}")
