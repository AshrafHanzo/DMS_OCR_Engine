# 🎨 Multilingual OCR Editor - Frontend & Backend Setup

## Overview
Complete OCR system with:
- ✅ Backend API (FastAPI) for OCR processing
- ✅ Interactive Frontend UI with live editing
- ✅ Background color detection
- ✅ Editable text boxes (like MS Word)
- ✅ DOCX & PDF export

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    User Browser                         │
│  ┌──────────────────────────────────────────────────┐  │
│  │  Frontend (index.html, styles.css, app.js)      │  │
│  │  - Image upload                                  │  │
│  │  - Real-time text editing                        │  │
│  │  - Background color detection                    │  │
│  └──────────────────────────────────────────────────┘  │
└────────────────┬────────────────────────────────────────┘
                 │ HTTP API Calls
                 ↓
┌─────────────────────────────────────────────────────────┐
│          FastAPI Backend (main.py)                      │
│  ┌──────────────────────────────────────────────────┐  │
│  │  POST /extract                                   │  │
│  │  - Image preprocessing (OpenCV)                  │  │
│  │  - OCR via OCRmyPDF + Tesseract                  │  │
│  │  - Returns extracted text + job_id               │  │
│  └──────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────┐  │
│  │  POST /formatted                                 │  │
│  │  - Generates DOCX with background + overlaid    │  │
│  │    editable text boxes                           │  │
│  └──────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────┐  │
│  │  GET /download/{job_id}                          │  │
│  │  - Downloads searchable PDF                      │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

## 🚀 Quick Start

### Prerequisites
- Python 3.8+
- Tesseract OCR installed (see SETUP_GUIDE.md)
- All Python dependencies installed

### Step 1: Start the Backend API Server

In terminal 1:
```bash
cd c:\Users\avin4\Desktop\basha_scans_layout\ocr
python main.py
```

Output should show:
```
INFO:     Started server process
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

### Step 2: Start the Frontend Server

In terminal 2:
```bash
cd c:\Users\avin4\Desktop\basha_scans_layout\ocr
python serve_frontend.py
```

Output should show:
```
╔════════════════════════════════════════════════════════════════╗
║           🌐 Frontend Server Started                           ║
╠════════════════════════════════════════════════════════════════╣
║  URL: http://localhost:8080                                    ║
```

### Step 3: Open Browser

Navigate to: **http://localhost:8080**

## 📋 Frontend Features

### 1. Image Upload
- Drag & drop image or click to select
- Supports: JPG, PNG, GIF, WebP
- Auto-detects image dimensions

### 2. Background Color Detection
- Automatically samples image corners
- Converts RGB to Hex color
- Can be manually adjusted with color picker

### 3. Extract Text (OCR)
- Click "Extract Text" button
- Uses `/extract` endpoint
- Displays extracted text as editable boxes
- Shows progress spinner

### 4. Edit Text Inline
- Click any text box to edit
- Type new text or modify existing
- Press Enter to save, Escape to cancel
- Font automatically switches between Kannada/English

### 5. View Statistics
- Kannada character count
- English character count
- Total text lines
- Background color value

### 6. Download Options
- **Download DOCX**: Word document with original image as background + text boxes
- **Download PDF**: Searchable PDF with OCR layer

## 🎮 Usage Workflow

```
1. Open http://localhost:8080
   ↓
2. Upload image (drag & drop or click)
   ↓
3. [Optional] Adjust background color or enable auto-detection
   ↓
4. Click "Extract Text" button
   ↓
5. View extracted text in editable boxes
   ↓
6. Click any text box to edit
   ↓
7. Type new text or modify (just like MS Word)
   ↓
8. Click outside to save changes
   ↓
9. Download as DOCX or PDF
```

## 🔧 API Endpoints Reference

### POST /extract
**Request:**
```
Form Data:
  - image: <binary file>
```

**Response:**
```json
{
  "status": "success",
  "job_id": "abc123def456",
  "languages_used": ["kan", "eng"],
  "extracted_text": "Line 1\nLine 2\nLine 3...",
  "searchable_pdf": "/download/abc123def456"
}
```

**Usage in Frontend:**
```javascript
const response = await fetch('http://localhost:8000/extract', {
    method: 'POST',
    body: formData
});
const result = await response.json();
```

### POST /formatted
**Request:**
```
Form Data:
  - image: <binary file>
```

**Response:**
```
Binary DOCX file
Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document
```

### GET /download/{job_id}
**Request:**
```
GET /download/abc123def456
```

**Response:**
```
Binary PDF file
Content-Type: application/pdf
```

## 📁 File Structure

```
ocr/
├── main.py                  # FastAPI backend (runs on 8000)
├── serve_frontend.py        # Frontend server (runs on 8080)
├── index.html               # Main frontend UI
├── styles.css               # Styling
├── app.js                   # JavaScript logic
├── docx_generator.py        # DOCX generation
├── requirements.txt         # Python dependencies
└── ocr_workspace/           # Temporary job files
    └── {job_id}/
        ├── input.jpg
        ├── preprocessed.png
        ├── output.pdf
        └── sidecar.txt
```

## 🎯 Key Frontend Functions

### extractOCR()
Calls `/extract` endpoint with canvas blob
```javascript
async function extractOCR() {
    state.canvas.toBlob(async (blob) => {
        const formData = new FormData();
        formData.append('image', blob, 'image.png');
        
        const response = await fetch(`${state.apiBaseUrl}/extract`, {
            method: 'POST',
            body: formData
        });
        
        const result = await response.json();
        state.jobId = result.job_id;
        state.ocrData = result.extracted_text.split('\n');
        // ... create editable boxes
    });
}
```

### makeBoxEditable(boxId)
Converts text box to inline editor
```javascript
function makeBoxEditable(boxId) {
    // Creates input field, allows live editing
    // Supports Kannada fonts automatically
}
```

### detectBackgroundColor()
Samples image corners and detects dominant color
```javascript
function detectBackgroundColor() {
    // Gets RGB from corner pixels
    // Converts to Hex
    // Updates canvas background
}
```

## 🐛 Troubleshooting

### "Cannot find module ocrmypdf"
```bash
pip install ocrmypdf
```

### "Tesseract not found"
Install Tesseract from: https://github.com/UB-Mannheim/tesseract/wiki
Then set path in Python

### "Connection refused on port 8000"
Make sure main.py is running in terminal 1

### "Port 8080 already in use"
Change PORT in serve_frontend.py:
```python
PORT = 8081  # or any other free port
```

### Frontend shows "Loading..." forever
Check browser console (F12) for API errors
Verify main.py is running and accessible

### Text boxes not appearing
Enable "Show Text Boxes" in Controls section

## 📊 Configuration

### Change API URL (if backend is on different machine)
Edit app.js:
```javascript
apiBaseUrl: 'http://192.168.1.100:8000'  // Change this IP
```

### Change Frontend Port
Edit serve_frontend.py:
```python
PORT = 8090  # Change this number
```

### Adjust Font Size
Use the Font Size slider (8-32px)

## 🎓 Advanced Usage

### Custom Background Color
1. Click color picker in Controls
2. Select desired color
3. Click "Apply"
4. Canvas updates immediately

### Export Workflow
```
OCR Extract → Review/Edit Text → Download DOCX/PDF
                    ↑
              Edit inline like Word
```

### Multi-language Support
- Automatically detects Kannada (0xC80-0xCFF)
- Switches font to "Noto Sans Kannada" for Kannada text
- Keeps "Noto Sans" for English text

## 📝 Notes

- All files in `ocr_workspace/` can be safely deleted (temporary job files)
- Frontend caches work locally in browser state
- API runs on 0.0.0.0 (accessible from any machine on network)
- CORS is enabled for frontend communication

## ✅ Testing

### Test /extract endpoint
```bash
curl -F "image=@test.jpg" http://localhost:8000/extract
```

### Test frontend locally
```bash
python -m http.server 8080 --directory c:\Users\avin4\Desktop\basha_scans_layout\ocr
```

Then open: http://localhost:8080

---

**Happy OCRing! 🎉**
