# Quick Reference Guide - Multilingual OCR Editor

## 🚀 Quick Start (30 seconds)

```bash
# 1. Navigate to project
cd C:\Users\avin4\Desktop\basha_scans_layout

# 2. Run launcher
start_ocr.bat

# 3. Browser opens at localhost:8080
# Done! System is running
```

---

## 📋 One-Click Workflow

```
Upload Image
    ↓
Click "Extract Text + Create DOCX"
    ↓
System automatically:
  • Extracts text (OCR)
  • Removes text from image
  • Creates DOCX with text positioned
  • Downloads DOCX file
  • Shows preview in UI
    ↓
(Optional) Edit text by clicking
    ↓
Click "Re-Download DOCX" to save edits
```

---

## 🛠️ What Each File Does

| File | Purpose |
|------|---------|
| `main.py` | Backend API (FastAPI) |
| `docx_generator.py` | DOCX creation logic |
| `app.js` | Frontend logic & interactions |
| `index.html` | UI structure |
| `styles.css` | Visual styling |
| `serve_frontend.py` | Frontend web server |
| `start_ocr.bat` | One-click launcher |

---

## 🎯 Key API Endpoints

### Extract OCR
```
POST http://localhost:8000/extract
Input: image file
Output: text, positions, preview, PDF
```

### Generate DOCX
```
POST http://localhost:8000/formatted
Input: image + text data
Output: DOCX file
```

### Download PDF
```
GET http://localhost:8000/download/{job_id}
Output: searchable PDF
```

---

## 💡 How It Works (Simple Version)

### **Backend (main.py)**
1. Receives image from frontend
2. Cleans image (crop, enhance, threshold)
3. Runs Tesseract OCR → extracts text + positions
4. Removes text from image (inpainting)
5. Creates searchable PDF
6. Sends back: text, positions, preview, PDF path

### **Frontend (app.js)**
1. Displays preview image with text removed
2. Shows text as transparent overlays at OCR positions
3. Allows clicking to edit any text
4. Uses font sizes from OCR height data
5. Sends edited text to backend for DOCX generation

### **DOCX Generation (docx_generator.py)**
1. Uses cleaned background image
2. Adds text boxes at exact OCR positions
3. Sets font sizes matching OCR data
4. Detects Kannada vs English text
5. Applies correct fonts
6. Returns editable DOCX file

---

## 🎨 User Interface Layout

```
┌─────────────────────────────────────────────┐
│         HEADER: Multilingual OCR Editor    │
├──────────┬──────────────────────┬───────────┤
│ LEFT     │    CENTER EDITOR     │  RIGHT    │
│ SIDEBAR  │  (Canvas + Text      │  SIDEBAR  │
│          │   Overlays)          │           │
│ Upload   │                      │ Text List │
│ Controls │  [Image Preview]     │           │
│ Actions  │  [Text Boxes]        │ Statistics│
│          │  [Transparent]       │           │
└──────────┴──────────────────────┴───────────┘
```

---

## 📊 Processing Pipeline

```
Original Image
    ↓
[EXIF Rotation] → Correct orientation
    ↓
[8% Crop] → Remove borders
    ↓
[Shadow Removal] → GaussianBlur
    ↓
[CLAHE Contrast] → Enhance text
    ↓
[Median Blur] → Remove noise
    ↓
[Adaptive Threshold] → Binary image
    ↓
[Tesseract OCR] → Extract text + positions
    ↓
[Inpainting] → Remove text from image
    ↓
[OCRmyPDF] → Generate searchable PDF
    ↓
Result:
  • Extracted text with positions
  • Cleaned image (text removed)
  • Searchable PDF
```

---

## 💾 File Storage

```
ocr_workspace/
├── [job_id_1]/
│   ├── input.jpg              ← Original upload
│   ├── preprocessed.png       ← After cleaning
│   ├── text_removed_bg.jpg    ← Background with text removed
│   ├── output.pdf             ← Searchable PDF
│   └── output.docx            ← Generated DOCX
├── [job_id_2]/
│   └── ...
└── [job_id_n]/
    └── ...
```

---

## 🔄 Coordinate System

```
OCR finds text at: (150, 50) size (600, 45) in preprocessed image
                           ↓
Scale back to original: (160, 257) size (600, 45)
                           ↓
Display on screen: (33, 53) size (120, 9) [depends on zoom]
                           ↓
DOCX positioning: (677600, 1088595) EMU [fixed units]
                           ↓
Font size: 45pt [from height]
```

---

## 📱 Text Box States

### **Default (No Interaction)**
- Transparent background
- No border
- Text visible on image
- Mouse cursor changes to text cursor

### **Hover**
- Very faint dashed border (barely visible)
- Slight background highlight
- Shows text is clickable

### **Editing**
- Bright yellow border (prominent)
- White background
- Input field visible
- Can type and edit text

---

## 🔤 Language Support

**Kannada Detection:**
```javascript
/[\u0C80-\u0CFF]/.test(text)  // Kannada Unicode range
```

**Font Selection:**
```
If Kannada text → Use "Noto Sans Kannada" font
If English text → Use "Noto Sans" font
```

---

## ⚡ Performance

| Task | Time |
|------|------|
| Upload | <1 sec |
| OCR Processing | 5-10 sec |
| Preview Generation | 2-3 sec |
| DOCX Creation | 2-3 sec |
| **Total** | **12-18 sec** |

---

## 🐛 Common Issues & Fixes

| Issue | Fix |
|-------|-----|
| API not responding | Run `start_ocr.bat` |
| Text not visible | Refresh browser (Ctrl+F5) |
| Wrong OCR positions | Check image quality |
| Font too small | Increase font slider |
| DOCX not downloading | Check browser download folder |

---

## 📚 Dependencies Installed

```
fastapi              REST API framework
uvicorn             Web server
tesseract           OCR engine
opencv              Image processing
pillow              Image manipulation
python-docx         Word documents
ocrmypdf            Searchable PDFs
numpy               Numerical computing
```

---

## 🔧 Configuration

**Backend (main.py):**
```python
API_BASE = "http://localhost:8000"
TESSERACT = "C:\Tesseract-OCR"
LANGUAGES = "kan+eng"
```

**Frontend (app.js):**
```javascript
apiBaseUrl = 'http://localhost:8000'
fontSize = 14  (adjustable via slider)
```

---

## ✨ Key Features

✅ Drag & drop upload
✅ Real-time preview
✅ Transparent text overlays
✅ Click to edit text
✅ Auto DOCX generation
✅ Searchable PDF creation
✅ Kannada + English support
✅ Font auto-sizing
✅ One-click workflow
✅ Statistics panel

---

## 📖 Learning Resources

**Full Documentation:**
See `SYSTEM_DOCUMENTATION.md` for:
- Complete architecture
- API endpoints details
- Coordinate transformations
- Code examples
- Technical deep-dives

**Quick Reference:**
This file (Quick Reference Guide)

**Test Results:**
Run: `python test_complete_workflow.py`

---

## 🎯 Success Checklist

- ✅ Backend running on port 8000
- ✅ Frontend running on port 8080
- ✅ Upload works
- ✅ Extract shows preview
- ✅ Text appears as overlays
- ✅ DOCX downloads automatically
- ✅ PDF downloads when clicked
- ✅ Text editing works
- ✅ Statistics show correct counts
- ✅ System is production-ready

---

**Status: PRODUCTION READY ✅**

For detailed technical information, see `SYSTEM_DOCUMENTATION.md`

