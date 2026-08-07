
import os
import ocrmypdf
import fitz
from pdf2docx import Converter
import pdf2docx.font.Font as FontExt

# Monkey-patch pdf2docx to allow invisible text (render_mode = 3) which OCRmyPDF uses
import pdf2docx.page.RawPage as RawPage
original_get_text = RawPage.RawPage.restore
def patched_restore(self, **kwargs):
    # Modify fitz output dict to set render_mode=0 for everything so pdf2docx doesn't ignore it
    return original_get_text(self, **kwargs)

# Wait, pdf2docx does the filtering in TextSpan.py or TextRenderer.py
# Actually, pdf2docx filters render_mode in pdf2docx/page/RawPage.py in extract_raw_dict:
# if block['type'] == 0: for line in block['lines']: for span in line['spans']: if not self._is_valid_text(span): ...
# Let's just open the pdf with fitz, and modify the dictionary before passing it to pdf2docx? No, pdf2docx opens the file itself.

# Best way might be to rewrite the PDF with PyMuPDF rendering the text visible before feeding to pdf2docx?
# We can't easily change render_mode in PyMuPDF.

print("Patching pdf2docx...")
import pdf2docx.page.TextSpan as TextSpan
# Override the flags so pdf2docx doesn't crash or ignore
original_store = TextSpan.TextSpan.store
def patched_store(self, raw_span):
    # force render mode 0
    raw_span['flags'] = 0 
    # wait, 'render_mode' is not in raw_span, it's 'flags'? Fitz returns simple dict.
    return original_store(self, raw_span)
TextSpan.TextSpan.store = patched_store

pdf_path = 'test_doc2.pdf'
docx_path = 'test_patch.docx'

print("Converting to DOCX...")
cv = Converter(pdf_path)
cv.convert(docx_path)
cv.close()
