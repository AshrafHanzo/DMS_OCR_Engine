"""
Multilingual OCR API - Kannada + English
Combines OpenCV Preprocessing + OCRmyPDF Engine

1. OpenCV: Aggressive scan cleaning (Shadow removal, CLAHE, Thresholding)
2. OCRmyPDF: Deskew, Rotate, Tesseract LSTM OCR, and Searchable PDF generation
3. Clean Filter: Removes garbage characters from final output
"""
import warnings
import logging

# Suppress OCRmyPDF warnings about missing optional dependencies (jbig2, pngquant)
# These are optional tools for PDF optimization but not required for core OCR functionality
warnings.filterwarnings("ignore", category=UserWarning, module="ocrmypdf")
logging.getLogger("ocrmypdf").setLevel(logging.ERROR)

from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.responses import PlainTextResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
# process_page and run_ocrmypdf are heavy blocking calls (ocrmypdf alone is
# ~140s) sitting inside async handlers. Without this, one upload freezes every
# other client on the server.
from starlette.concurrency import run_in_threadpool
import ocrmypdf
from ocrmypdf.exceptions import ExitCode
from PIL import Image, ImageOps
import tempfile
import os
import uuid
import uvicorn
import cv2
import numpy as np
import base64
from io import BytesIO

app = FastAPI(
    title="OCRmyPDF Multilingual API",
    description="Kannada + English OCR with custom OpenCV preprocessing",
    version="1.0.1"
)

# Enable CORS for frontend communication
# allow_origins=["*"] together with allow_credentials=True is a combination
# browsers reject outright, so the old setting was both wide open and broken. The
# UI is served from this same app (see the StaticFiles mount at the bottom of this
# file), so same-origin is the normal case and CORS_ORIGINS stays empty unless
# something external needs to call in — the DMS operation portal, for instance.
_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

WORK_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ocr_workspace")
os.makedirs(WORK_DIR, exist_ok=True)


def create_text_removed_preview(original_image_path: str, job_dir: str) -> str:
    """
    Create preview image with text removed for UI display.
    Uses inpainting to intelligently fill text regions with background.
    Returns base64 encoded image string.
    """
    try:
        # Load original image
        pimg = Image.open(original_image_path)
        pimg = ImageOps.exif_transpose(pimg)
        orig_img = cv2.cvtColor(np.array(pimg), cv2.COLOR_RGB2BGR)
        
        # Preprocess to get binary mask
        preprocessed_path = os.path.join(job_dir, "preprocess_preview.png")
        preprocess_for_ocr(original_image_path, preprocessed_path)
        
        # Load preprocessed binary
        binary = cv2.imread(preprocessed_path, cv2.IMREAD_GRAYSCALE)
        
        h, w = orig_img.shape[:2]
        margin_y = int(h * 0.08)
        margin_x = int(w * 0.08)
        
        # Create text mask
        binary_cropped = np.full((h, w), 255, dtype=np.uint8)
        if binary is not None:
            binary_cropped[margin_y:h-margin_y, margin_x:w-margin_x] = binary
        
        text_mask = cv2.bitwise_not(binary_cropped)
        
        # Dilate mask to ensure full coverage
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        text_mask = cv2.dilate(text_mask, kernel, iterations=2)
        
        # Inpaint to remove text
        result = cv2.inpaint(orig_img, text_mask, 5, cv2.INPAINT_TELEA)
        
        # Save and encode as base64
        _, buffer = cv2.imencode('.jpg', result, [cv2.IMWRITE_JPEG_QUALITY, 85])
        img_base64 = base64.b64encode(buffer).decode('utf-8')
        
        return img_base64
    except Exception as e:
        print(f"  Warning: Could not create text-removed preview: {e}")
        # Fallback to original image
        with open(original_image_path, "rb") as f:
            img_base64 = base64.b64encode(f.read()).decode('utf-8')
        return img_base64


def preprocess_for_ocr(input_path: str, output_path: str):
    """
    Apply heavy-duty image processing so Tesseract inside OCRmyPDF can actually read the Kannada.
    These scans are on dark blue folders with low contrast, which breaks OCRmyPDF by default.
    """
    # 1. Read
    pimg = Image.open(input_path)
    pimg = ImageOps.exif_transpose(pimg)
    img = cv2.cvtColor(np.array(pimg), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape

    # 2. Crop 8% of the edges (destroys the blue folder border entirely)
    margin_y = int(h * 0.08)
    margin_x = int(w * 0.08)
    gray = gray[margin_y:h-margin_y, margin_x:w-margin_x]

    # 3. Shadow removal
    blurred_bg = cv2.GaussianBlur(gray, (0, 0), sigmaX=60)
    blurred_bg = np.where(blurred_bg == 0, 1, blurred_bg).astype(np.float32)
    normalized = (gray.astype(np.float32) / blurred_bg * 220)
    gray = np.clip(normalized, 0, 255).astype(np.uint8)

    # 4. CLAHE contrast enhancement
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    gray = clahe.apply(gray)

    # 5. Despeckle before thresholding
    gray = cv2.medianBlur(gray, 3)

    # 6. Adaptive thresholding to pure black and white
    binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 41, 15)

    # 7. Save as PNG for OCRmyPDF
    cv2.imwrite(output_path, binary)


def clean_output(text: str) -> str:
    """Filter out noise lines hallucinated by Tesseract on borders or logos."""
    cleaned_lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            if cleaned_lines and cleaned_lines[-1] != "":
                cleaned_lines.append("")
            continue
            
        kan_chars = sum(1 for c in stripped if 0x0C80 <= ord(c) <= 0x0CFF)
        eng_chars = sum(1 for c in stripped if 'a' <= c.lower() <= 'z')
        symbols = sum(1 for c in stripped if not c.isalnum() and not (0x0C80 <= ord(c) <= 0x0CFF) and c not in ' .-,/()&:;\'"')
        
        total = max(len(stripped), 1)
        
        # Reject highly symbolic noisy border lines
        if symbols / total > 0.15: 
            continue
            
        # Reject tiny gibberish lines 
        if len(stripped) < 5 and kan_chars == 0 and eng_chars == 0: 
            continue
            
        # Reject corrupted English/Kannada mixed gibberish (e.g. email parsing failure)
        if eng_chars > 0 and kan_chars > 0 and (kan_chars + eng_chars) < 15 and symbols > 2:
            continue
            
        # Specific overrides for known Tesseract hallucinations on empty spaces
        if stripped.lower().startswith('ut 584'):
            continue
            
        cleaned_lines.append(stripped)
        
    while cleaned_lines and cleaned_lines[-1] == "":
        cleaned_lines.pop()
    
    return "\n".join(cleaned_lines)


def run_ocrmypdf(input_path: str, job_id: str):
    job_dir = os.path.join(WORK_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)
    
    preprocessed_img = os.path.join(job_dir, "preprocessed.png")
    output_pdf = os.path.join(job_dir, "output.pdf")
    sidecar_txt = os.path.join(job_dir, "sidecar.txt")
    
    # Apply our custom heavy preprocessing first!
    preprocess_for_ocr(input_path, preprocessed_img)
    
    # NOW pass the pristine B&W image to OCRmyPDF
    exit_code = ocrmypdf.ocr(
        preprocessed_img,           # Use cleaned image
        output_pdf,
        language=["kan", "eng"],
        image_dpi=300,
        rotate_pages=True,
        deskew=True,
        clean=False,                # Disabled since we did it manually using OpenCV now
        force_ocr=True,
        sidecar=sidecar_txt,
        tesseract_oem=1,
        tesseract_pagesegmode=3,
        output_type="pdf",
        optimize=0,                 # Disabled: jbig2 and pngquant not available on Windows
        jobs=1,
    )
    
    return exit_code, output_pdf, sidecar_txt


def get_ocr_text_with_positions(input_path: str, original_image_path: str) -> list:
    """
    Extract text WITH POSITION DATA using pytesseract.
    Returns list of dicts: {text, left, top, width, height}
    Positions are scaled to match the ORIGINAL image size (not preprocessed).
    """
    import pytesseract
    
    img = cv2.imread(input_path)
    if img is None:
        return []
    
    try:
        # Get original image dimensions
        pimg = Image.open(original_image_path)
        pimg = ImageOps.exif_transpose(pimg)
        orig_img = cv2.cvtColor(np.array(pimg), cv2.COLOR_RGB2BGR)
        orig_h, orig_w = orig_img.shape[:2]
        
        # Calculate margins (8% crop)
        margin_y = int(orig_h * 0.08)
        margin_x = int(orig_w * 0.08)
        
        # Get word-level data with positions from preprocessed image
        data = pytesseract.image_to_data(
            img,
            config=r'-l kan+eng --oem 1 --psm 3 -c preserve_interword_spaces=1',
            output_type=pytesseract.Output.DICT
        )
        
        # Group words into lines and extract positions
        lines = {}
        n = len(data['text'])
        
        for i in range(n):
            text = data['text'][i].strip()
            if not text:
                continue
            
            conf = int(data['conf'][i])
            if conf < 0:  # Low confidence / block marker - skip
                continue
            
            # Reject purely noisy hallucinated symbols that stretch bounding boxes
            kan_chars = sum(1 for c in text if 0x0C80 <= ord(c) <= 0x0CFF)
            eng_chars = sum(1 for c in text if c.lower() in 'abcdefghijklmnopqrstuvwxyz0123456789')
            if kan_chars == 0 and eng_chars == 0:
                continue
            
            # Group by line
            line_key = (data['block_num'][i], data['par_num'][i], data['line_num'][i])
            
            if line_key not in lines:
                lines[line_key] = {
                    'words': [],
                    'left': data['left'][i],
                    'right': data['left'][i] + data['width'][i],
                    'tops': [],
                    'heights': []
                }
            
            lines[line_key]['words'].append(text)
            
            # Expand horizontal bounding box
            lines[line_key]['left'] = min(lines[line_key]['left'], data['left'][i])
            lines[line_key]['right'] = max(lines[line_key]['right'], data['left'][i] + data['width'][i])
            
            # Keep track of tops and heights to find median
            lines[line_key]['tops'].append(data['top'][i])
            lines[line_key]['heights'].append(data['height'][i])
        
        import statistics
        
        # Convert to list of position data and SCALE back to original image coordinates
        result = []
        for key in sorted(lines.keys()):
            line = lines[key]
            
            # Scale coordinates: preprocessed image → original image
            scaled_left = line['left'] + margin_x
            scaled_width = line['right'] - line['left']
            
            # For vertical positioning (top and height), use IQR to filter outliers
            def get_robust_metric(values):
                if not values:
                    return 0
                if len(values) < 3:
                    return statistics.median(values)
                
                v_sorted = sorted(values)
                q1 = v_sorted[len(v_sorted)//4]
                q3 = v_sorted[3*len(v_sorted)//4]
                iqr = q3 - q1
                
                # Keep only values within 1.5 * IQR
                valid_values = [v for v in values if (q1 - 1.5 * iqr) <= v <= (q3 + 1.5 * iqr)]
                return statistics.median(valid_values if valid_values else values)
            
            robust_top = get_robust_metric(line['tops'])
            robust_height = get_robust_metric(line['heights'])
            
            # Apply vertical offset (2px) to prevent overlap and better align baseline
            scaled_top = int(robust_top) + margin_y + 2
            # Apply 0.8x safety factor to prevent font line-height from causing overlaps
            scaled_height = int(robust_height * 0.8)
            
            result.append({
                'text': ' '.join(line['words']),
                'left': scaled_left,
                'top': scaled_top,
                'width': scaled_width,
                'height': scaled_height,
                'kannada': any(0x0C80 <= ord(c) <= 0x0CFF for c in ' '.join(line['words']))
            })
        
        # Sort and Resolve Vertical Collisions
        result.sort(key=lambda x: x['top'])
        last_bottom = 0
        for item in result:
            # Increase gap to 4 for better vertical spacing
            if item['top'] < last_bottom + 4:
                item['top'] = last_bottom + 4
            last_bottom = item['top'] + item['height']
            
        return result
    except Exception as e:
        import traceback
        with open("error_log.txt", "w") as f:
            f.write(traceback.format_exc())
        print(f"Error extracting text with positions: {e}")
        return []


@app.post("/extract/raw")
async def extract_raw_text(image: UploadFile = File(...)):
    job_id = uuid.uuid4().hex[:12]
    job_dir = os.path.join(WORK_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)
    
    ext = os.path.splitext(image.filename or "upload")[1] or ".jpg"
    input_path = os.path.join(job_dir, f"input{ext}")
    contents = await image.read()
    with open(input_path, "wb") as f:
        f.write(contents)
    
    try:
        exit_code, _, sidecar_txt = await run_in_threadpool(run_ocrmypdf, input_path, job_id)
        
        text = ""
        if os.path.exists(sidecar_txt):
            with open(sidecar_txt, "r", encoding="utf-8") as f:
                text = f.read()
                
        # Clean garbage lines from sidecar output
        text = clean_output(text)
        return PlainTextResponse(content=text)
    except Exception as e:
        raise HTTPException(500, f"OCR processing failed: {str(e)}")


@app.post("/extract")
async def extract_text(image: UploadFile = File(...), engine: str = Form("aligned")):
    """Extract text with positions.

    engine="aligned" (default) -> the layout-faithful pipeline: page detection,
        deskew, per-line boxes, PaddleOCR-VL recognition. Measured on
        test_doc2.pdf at 71.6% Kannada / 100% Latin, alignment median 75%.
    engine="legacy"            -> the original Tesseract path (~8% Kannada).
        Kept so results can be compared, not because it is recommended.
    """
    job_id = uuid.uuid4().hex[:12]
    job_dir = os.path.join(WORK_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    input_path = os.path.join(job_dir, "input.jpg")
    contents = await image.read()
    with open(input_path, "wb") as f:
        f.write(contents)

    if engine == "aligned":
        try:
            from aligned_pipeline import process_page
            r = await run_in_threadpool(process_page, input_path, job_dir, want_docx=True)
            # NOTE: the searchable PDF is NOT built here. It costs ~140s of
            # ocrmypdf/Tesseract and doubles the upload wait for something most
            # requests never fetch. /download builds it lazily on first use.
            return {
                "status": "success",
                "engine": "aligned",
                "job_id": job_id,
                "languages_used": ["kan", "eng"],
                "extracted_text": r["extracted_text"],
                "text_data": r["text_data"],
                "preview_image": f"data:{r['preview_mime']};base64,{r['preview_image']}",
                "searchable_pdf": f"/download/{job_id}",
                "aligned_docx": f"/aligned/{job_id}",
                "diagnostics": {
                    "skew_deg": r["skew"],
                    "page_fraction": r["page_frac"],
                    "lines_detected": r["lines"],
                    "lines_rendered": r["rendered"],
                    "alignment_median_pct": r["align_median"],
                    "image_size": [r["width"], r["height"]],
                },
            }
        except Exception as e:
            import traceback
            traceback.print_exc()
            raise HTTPException(500, f"aligned pipeline failed: {e}")

    # ---- legacy path (original behaviour) ----
    try:
        preview_image_base64 = create_text_removed_preview(input_path, job_dir)
        preprocessed_path = os.path.join(job_dir, "preprocessed.png")
        preprocess_for_ocr(input_path, preprocessed_path)
        text_with_positions = get_ocr_text_with_positions(preprocessed_path, input_path)
        exit_code, _, sidecar_txt = await run_in_threadpool(run_ocrmypdf, input_path, job_id)
        text = ""
        if os.path.exists(sidecar_txt):
            with open(sidecar_txt, "r", encoding="utf-8") as f:
                text = f.read()
        text = clean_output(text)
        return {
            "status": "success",
            "engine": "legacy",
            "job_id": job_id,
            "languages_used": ["kan", "eng"],
            "extracted_text": text,
            "text_data": text_with_positions,
            "preview_image": f"data:image/jpeg;base64,{preview_image_base64}",
            "searchable_pdf": f"/download/{job_id}"
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/aligned/{job_id}")
async def download_aligned_docx(job_id: str):
    """The layout-faithful .docx produced by the aligned pipeline."""
    job_dir = os.path.join(WORK_DIR, job_id)
    if not os.path.isdir(job_dir):
        raise HTTPException(404, "job not found")
    for f in os.listdir(job_dir):
        if f.endswith("_aligned.docx"):
            return FileResponse(
                os.path.join(job_dir, f),
                media_type="application/vnd.openxmlformats-officedocument."
                           "wordprocessingml.document",
                filename=f"{job_id}_aligned.docx")
    raise HTTPException(404, "aligned docx not found")


from docx_generator import generate_formatted_docx

@app.post("/formatted")
async def get_formatted_docx(image: UploadFile = File(...), text_data: str = Form(None)):
    """
    Upload an image and optionally edited text data, get a perfectly overlaid .docx back.
    The .docx contains the image as background, with OCR text boxes overlaying at exact positions.
    If text_data is provided, uses that instead of running OCR.
    """
    import json
    
    job_id = uuid.uuid4().hex[:12]
    job_dir = os.path.join(WORK_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)
    
    ext = os.path.splitext(image.filename or "upload")[1] or ".jpg"
    input_path = os.path.join(job_dir, f"input{ext}")
    output_docx_path = os.path.join(job_dir, f"output.docx")
    
    contents = await image.read()
    with open(input_path, "wb") as f:
        f.write(contents)
        
    try:
        edited_text_data = None
        if text_data:
            try:
                edited_text_data = json.loads(text_data)
            except Exception:
                pass

        if edited_text_data:
            # The frontend sent edited boxes. Honour them EXACTLY as given:
            # detect nothing, shift nothing, just place the user's text at the
            # user's coordinates on a text-removed background.
            import cv2
            from aligned_pipeline import (normalise, render, Fitter, pick_font,
                                          write_docx)
            img = cv2.imread(input_path)
            if img is None:
                raise HTTPException(400, "cannot read uploaded image")
            H, W = img.shape[:2]
            # normalise() returns 6 values (rot, ink, skew, frac, ink_sensitive, M).
            # This unpacked 4, so every "edit the text then download the DOCX"
            # request raised ValueError and returned a 500.
            rot, ink, _, _, _, _ = normalise(img)
            boxes = []
            for i, it in enumerate(edited_text_data):
                t = (it.get("text") or "").strip()
                if not t:
                    continue
                boxes.append({
                    "id": i, "text": t, "noise": False,
                    "x": int(it.get("x", it.get("left", 0))),
                    "y": int(it.get("y", it.get("top", 0))),
                    "w": int(it.get("width", 10)),
                    "h": int(it.get("height", 10)),
                })
            fp = pick_font()
            if not fp:
                raise HTTPException(500, "no Kannada-capable font installed")
            clean, _pil = render(rot, ink, boxes, Fitter(fp))
            bg = os.path.join(job_dir, "clean_bg.png")
            cv2.imwrite(bg, clean)
            write_docx(output_docx_path, bg, boxes, W, H)
        else:
            # No edits supplied -> run the full aligned pipeline
            from aligned_pipeline import process_page
            r = await run_in_threadpool(process_page, input_path, job_dir, want_docx=True)
            if r.get("docx") and os.path.exists(r["docx"]):
                output_docx_path = r["docx"]

        if not os.path.exists(output_docx_path):
            raise HTTPException(500, "DOCX generation failed")

        return FileResponse(
            output_docx_path,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=f"{job_id}_aligned.docx"
        )
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Formatted DOCX generation failed: {str(e)}")


@app.get("/download/{job_id}")
async def download_searchable_pdf(job_id: str):
    """Searchable PDF, built lazily.

    Generating it costs ~140s of ocrmypdf/Tesseract, so /extract no longer does
    it up front. It is produced here on first request and cached on disk.
    """
    job_dir = os.path.join(WORK_DIR, job_id)
    pdf_path = os.path.join(job_dir, "output.pdf")
    if not os.path.exists(pdf_path):
        if not os.path.isdir(job_dir):
            raise HTTPException(404, "job not found")
        src = next((os.path.join(job_dir, f) for f in os.listdir(job_dir)
                    if f.startswith("input.")), None)
        if not src:
            raise HTTPException(404, "source image for job not found")
        try:
            await run_in_threadpool(run_ocrmypdf, src, job_id)
        except Exception as e:
            raise HTTPException(500, f"searchable PDF generation failed: {e}")
    if not os.path.exists(pdf_path):
        raise HTTPException(404, "PDF not found")
    return FileResponse(pdf_path, media_type="application/pdf", filename=f"{job_id}_searchable.pdf")


@app.get("/health")
def health():
    """
    Prove this host is configured the same as the one the output was tuned on.

    Font metrics decide layout: assign_font_sizes() shrinks the size until the text
    fits its detected box, so a different font file gives different font_px and a
    different DOCX. Compare this JSON between machines — font_file, raqm and pillow
    must match or the output will drift.
    """
    import shutil
    import urllib.request
    import PIL
    from PIL import features
    from aligned_pipeline import pick_font, OLLAMA, DEFAULT_MODEL
    try:
        urllib.request.urlopen(f"{OLLAMA}/api/tags", timeout=3)
        ollama_up = True
    except Exception:
        ollama_up = False
    return {
        "status": "ok",
        "font_file": pick_font(),
        # libraqm shapes complex Indic scripts. Without it Kannada conjuncts and
        # matras render wrong even with the right font file.
        "raqm": features.check("raqm"),
        "pillow": PIL.__version__,
        "ollama_url": OLLAMA,
        "ollama_up": ollama_up,
        "model": DEFAULT_MODEL,
        "tesseract": bool(shutil.which("tesseract")),
        "ghostscript": bool(shutil.which("gs")),
    }


# The UI is served by this same app so there is one port and no CORS. app.js used
# to hardcode http://localhost:8000, which only works when the browser is on the
# same machine as the API — a remote user's "localhost" is their own PC.
#
# MUST be mounted after every @app route: a mount at "/" shadows anything declared
# after it.
from fastapi.staticfiles import StaticFiles  # noqa: E402

app.mount("/", StaticFiles(directory=os.path.dirname(os.path.abspath(__file__)),
                           html=True), name="ui")


if __name__ == "__main__":
    # Port comes from the environment: on the GPU server 8000 and 8001 are already
    # taken by other services, so this deployment runs on 8080.
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("OCR_PORT", "8080")))
