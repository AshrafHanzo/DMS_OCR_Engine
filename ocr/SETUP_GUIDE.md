# OCRmyPDF Setup Guide for Windows

## Installation

### 1. System Prerequisites
- Python 3.8+
- Tesseract OCR Engine

### 2. Install Tesseract
Download from: https://github.com/UB-Mannheim/tesseract/wiki
Choose the latest installer (e.g., `tesseract-ocr-w64-setup-v5.x.x.exe`)

After installation, set the path in Python:
```python
import pytesseract
pytesseract.pytesseract.pytesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
```

### 3. Install Python Dependencies
```bash
pip install -r requirements.txt
```

## Optional Dependencies

### jbig2 and pngquant
These tools optimize PDF compression and are **optional**:
- **jbig2**: Lossless image compression (JBIG2 format)
- **pngquant**: PNG color palette optimization

#### Why the warnings appear:
OCRmyPDF tries to use these tools but they're not available on Windows by default. The warnings are harmless - the OCR and PDF generation still work perfectly fine without them.

#### Configuration:
Currently set to `optimize=0` (disabled) in `main.py` to avoid these warnings.

#### If you want to enable optimization on Windows:
You would need to:
1. Download pre-compiled binaries from:
   - jbig2: https://github.com/agl/jbig2enc
   - pngquant: https://pngquant.org/

2. Add them to your system PATH

3. Change `optimize=0` to `optimize=1` in `main.py` line 140

### On Linux/macOS:
```bash
# Ubuntu/Debian
apt-get install jbig2enc pngquant

# macOS
brew install jbig2enc pngquant
```

Then set `optimize=1` in main.py

## Running the API

```bash
python main.py
```

Server runs on: `http://localhost:8000`

### API Endpoints:
- `POST /extract` - Extract text and get structured response
- `POST /extract/raw` - Extract raw text only
- `POST /formatted` - Generate Word document with overlaid text
- `GET /download/{job_id}` - Download searchable PDF

## Troubleshooting

**Q: I see "jbig2 not found" warning**
A: This is normal on Windows. The OCR still works fine. If you want to suppress it, it's already disabled in the code.

**Q: Can I still use OCR without these tools?**
A: Yes! These are optimization-only. OCR works perfectly without them.

**Q: What's the difference in file size?**
A: With optimization enabled, PDFs are 10-30% smaller. Without optimization, they're slightly larger but fully functional and searchable.
