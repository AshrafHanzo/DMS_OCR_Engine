import sys
import subprocess

# use generic python since global pip installed pdf2docx
code = """
import os
import ocrmypdf
from pdf2docx import Converter

img_path = r'c:\\Users\\avin4\\Desktop\\AGENDA 424TH B M DT 23-03-2022 H G M L\\Resim000004.jpg'
pdf_path = 'test_doc2.pdf'
docx_path = 'test_doc2.docx'

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
try:
    cv = Converter(pdf_path)
    cv.convert(docx_path)
    cv.close()
    print(f"Done! Created {docx_path}")
except Exception as e:
    print(f"pdf2docx error: {e}")
"""

with open("test_global_docx.py", "w") as f:
    f.write(code)

subprocess.check_call([sys.executable, "test_global_docx.py"])
