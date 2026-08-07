import fitz

pdf_path = "test_doc2.pdf"
doc = fitz.open(pdf_path)
for page in doc:
    # PyMuPDF cannot easily mutate the operator stream to change render mode, but it can extract TextPage
    text = page.get_text("dict")
    print("Found text blocks:", len(text['blocks']))
    
doc.close()
