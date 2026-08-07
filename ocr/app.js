// ===== GLOBAL STATE =====
let state = {
    image: null,
    canvas: null,
    ctx: null,
    imagePath: null,
    jobId: null,
    ocrData: [],
    textBoxes: [],
    backgroundColor: '#ffffff',
    fontSize: 14,
    editingBoxId: null,
    // Same origin: the API serves this page (see the StaticFiles mount in
    // main.py). Hardcoding localhost:8000 broke every remote browser, because
    // "localhost" resolved to the visitor's own machine.
    apiBaseUrl: '',
    canvasScale: 1,  // Track scaling factor for text box positioning
    canvasOffsetX: 0,  // Offset due to centering
    canvasOffsetY: 0
};

// ===== INITIALIZATION =====
document.addEventListener('DOMContentLoaded', () => {
    initializeCanvas();
    initializeUpload();
    initializeEventListeners();
    
    // Recalculate scale on window resize
    window.addEventListener('resize', () => {
        if (state.image) {
            displayImageOnCanvas();
            renderTextBoxes(true);
        }
    });
});

function initializeCanvas() {
    state.canvas = document.getElementById('canvas');
    state.ctx = state.canvas.getContext('2d');
}

function initializeUpload() {
    const uploadArea = document.getElementById('uploadArea');
    const imageInput = document.getElementById('imageInput');

    // Click to upload
    uploadArea.addEventListener('click', () => imageInput.click());

    // File input change
    imageInput.addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (file) handleImageUpload(file);
    });

    // Drag and drop
    uploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadArea.classList.add('dragover');
    });

    uploadArea.addEventListener('dragleave', () => {
        uploadArea.classList.remove('dragover');
    });

    uploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadArea.classList.remove('dragover');
        const file = e.dataTransfer.files[0];
        if (file && file.type.startsWith('image/')) handleImageUpload(file);
    });
}

function initializeEventListeners() {
    document.getElementById('autoBackgroundColor').addEventListener('change', (e) => {
        if (e.target.checked && state.image) {
            detectBackgroundColor();
        }
    });

    document.getElementById('fontSizeSlider').addEventListener('input', (e) => {
        state.fontSize = parseInt(e.target.value);
        document.getElementById('fontSizeValue').textContent = e.target.value;
        renderTextBoxes(true);
    });
}

// ===== IMAGE UPLOAD & PROCESSING =====
function handleImageUpload(file) {
    const reader = new FileReader();
    reader.onload = (e) => {
        const img = new Image();
        img.onload = () => {
            state.image = img;
            state.jobId = generateJobId();
            
            // Use requestAnimationFrame to ensure layout is ready
            requestAnimationFrame(() => {
                displayImageOnCanvas();
                updateImageInfo();
                document.getElementById('extractBtn').disabled = false;
                showStatus('Image loaded successfully!', 'success');
                
                // Auto-detect background color if enabled
                if (document.getElementById('autoBackgroundColor').checked) {
                    detectBackgroundColor();
                }
            });
        };
        img.src = e.target.result;
    };
    reader.readAsDataURL(file);
    showStatus('Loading image...', 'loading');
}

function displayImageOnCanvas() {
    state.canvas.width = state.image.width;
    state.canvas.height = state.image.height;
    state.ctx.fillStyle = state.backgroundColor;
    state.ctx.fillRect(0, 0, state.canvas.width, state.canvas.height);
    state.ctx.drawImage(state.image, 0, 0);
    
    // Calculate scale factor for text box positioning
    const container = document.querySelector('.canvas-container');
    const containerRect = container.getBoundingClientRect();
    
    const scaleX = containerRect.width / state.canvas.width;
    const scaleY = containerRect.height / state.canvas.height;
    state.canvasScale = Math.min(scaleX, scaleY);
    
    // Calculate offset for centered canvas
    const scaledWidth = state.canvas.width * state.canvasScale;
    const scaledHeight = state.canvas.height * state.canvasScale;
    state.canvasOffsetX = (containerRect.width - scaledWidth) / 2;
    state.canvasOffsetY = (containerRect.height - scaledHeight) / 2;
}

function updateImageInfo() {
    const info = `
        <strong>Dimensions:</strong> ${state.image.width} × ${state.image.height}px<br>
        <strong>Size:</strong> ${(state.image.src.length / 1024).toFixed(1)} KB<br>
        <strong>Job ID:</strong> ${state.jobId}<br>
        <strong>Status:</strong> Ready for OCR
    `;
    document.getElementById('imageInfo').innerHTML = info;
}

// ===== BACKGROUND COLOR DETECTION =====
function detectBackgroundColor() {
    if (!state.image) return;

    const offCanvas = document.createElement('canvas');
    const offCtx = offCanvas.getContext('2d');
    offCanvas.width = state.image.width;
    offCanvas.height = state.image.height;
    offCtx.drawImage(state.image, 0, 0);

    const imageData = offCtx.getImageData(0, 0, offCanvas.width, offCanvas.height);
    const data = imageData.data;

    // Sample pixels from corners and edges (typically background)
    const samples = [];
    const sampleSize = 50;

    // Top-left corner
    for (let i = 0; i < sampleSize * sampleSize * 4; i += 4) {
        samples.push({
            r: data[i],
            g: data[i + 1],
            b: data[i + 2]
        });
    }

    // Average the samples
    const avgColor = samples.reduce((acc, color) => ({
        r: acc.r + color.r,
        g: acc.g + color.g,
        b: acc.b + color.b
    }), { r: 0, g: 0, b: 0 });

    avgColor.r = Math.round(avgColor.r / samples.length);
    avgColor.g = Math.round(avgColor.g / samples.length);
    avgColor.b = Math.round(avgColor.b / samples.length);

    const bgColor = rgbToHex(avgColor.r, avgColor.g, avgColor.b);
    state.backgroundColor = bgColor;
    
    document.getElementById('customBgColor').value = bgColor;
    document.getElementById('statBgColor').textContent = bgColor;
    
    displayImageOnCanvas();
    renderTextBoxes(true);
    showStatus(`Background color detected: ${bgColor}`, 'success');
}

function rgbToHex(r, g, b) {
    return "#" + ((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1).toUpperCase();
}

function updateBackgroundColor() {
    state.backgroundColor = document.getElementById('customBgColor').value;
    document.getElementById('statBgColor').textContent = state.backgroundColor;
    displayImageOnCanvas();
    renderTextBoxes(true);
}

function updateFontSize(value) {
    state.fontSize = parseInt(value);
    document.getElementById('fontSizeValue').textContent = value;
    renderTextBoxes(true);
}

// ===== OCR EXTRACTION USING /extract ENDPOINT =====
async function extractOCR() {
    if (!state.image) {
        showStatus('Please upload an image first', 'error');
        return;
    }

    showStatus('Extracting text with OCR...', 'loading');
    document.getElementById('loadingSpinner').classList.remove('hidden');
    document.getElementById('extractBtn').disabled = true;

    try {
        // Convert canvas to blob and send to /extract endpoint
        state.canvas.toBlob(async (blob) => {
            const formData = new FormData();
            formData.append('image', blob, 'image.png');

            // Call /extract endpoint to get structured response with job_id
            const response = await fetch(`${state.apiBaseUrl}/extract`, {
                method: 'POST',
                body: formData
            });

            if (!response.ok) {
                throw new Error(`API error: ${response.status}`);
            }

            const result = await response.json();
            
            // Update job ID from response
            state.jobId = result.job_id;
            // The aligned pipeline already built the DOCX during /extract,
            // so downloading it is just a GET - no second pipeline run.
            state.alignedDocxUrl = result.aligned_docx
                ? `${state.apiBaseUrl}${result.aligned_docx}` : null;
            state.diagnostics = result.diagnostics || null;
            state.engine = result.engine || 'unknown';
            
            // Load the text-removed preview image if available
            if (result.preview_image) {
                const previewImg = new Image();
                previewImg.onload = () => {
                    state.image = previewImg;
                    requestAnimationFrame(() => {
                        displayImageOnCanvas();
                        renderTextBoxes(true);
                    });
                };
                previewImg.src = result.preview_image;
            }
            
            // Extract text from response
            state.ocrData = result.extracted_text.split('\n').filter(line => line.trim());
            
            // Create editable text boxes from position data
            if (result.text_data && result.text_data.length > 0) {
                createTextBoxesFromPositions(result.text_data);
            } else {
                createTextBoxes();
            }
            
            // Always render text
            renderTextBoxes(true);
            updateStats();
            updateTextList();
            
            document.getElementById('downloadDocxBtn').disabled = false;
            document.getElementById('downloadPdfBtn').disabled = false;
            
            // The DOCX is already built by /extract - do NOT kick off a second
            // pipeline run here (that used to double the work per click).
            const d = state.diagnostics;
            showStatus(
                d ? `✓ ${state.textBoxes.length} lines · skew ${d.skew_deg}° · `
                    + `alignment ${d.alignment_median_pct}% · engine ${state.engine}`
                  : `✓ Extracted ${state.ocrData.length} text lines`,
                'success');
            updateDiagnostics();
        });
    } catch (error) {
        console.error('OCR Error:', error);
        showStatus(`Error: ${error.message}`, 'error');
    } finally {
        document.getElementById('loadingSpinner').classList.add('hidden');
        document.getElementById('extractBtn').disabled = false;
    }
}

function createTextBoxes() {
    state.textBoxes = [];
    
    // Create text boxes from OCR data with automatic positioning
    let yOffset = 50;
    const margin = 20;
    
    state.ocrData.forEach((line, index) => {
        if (line.trim()) {
            state.textBoxes.push({
                id: index,
                text: line.trim(),
                x: margin,
                y: yOffset,
                width: state.canvas.width - (margin * 2),
                height: state.fontSize + 8,
                kannada: hasKannada(line),
                original: line.trim()
            });
            yOffset += state.fontSize + 12;
        }
    });
}

function createTextBoxesFromPositions(textData) {
    state.textBoxes = [];
    
    // Create text boxes from OCR position data
    // IMPORTANT: Use ACTUAL height from OCR as the font size (don't calculate/predict)
    textData.forEach((item, index) => {
        if (item.text.trim()) {
            // Font size in pixels = height of the OCR bounding box
            const fontSizePixels = Math.max(8, item.height);
            
            state.textBoxes.push({
                id: index,
                text: item.text.trim(),
                x: item.left,
                y: item.top,
                width: Math.max(item.width, 50),
                height: item.height,
                fontSize: fontSizePixels,  // Store actual font size
                kannada: hasKannada(item.text),
                original: item.text.trim()
            });
        }
    });
}

function hasKannada(text) {
    return /[\u0C80-\u0CFF]/.test(text);
}

// ===== TEXT BOX RENDERING & EDITING =====
function getFontSizeForBox(box, containerWidth, containerHeight) {
    return calculateOptimalFontSize(box.text, containerWidth, containerHeight, box.kannada, box.fontSize);
}

function calculateOptimalFontSize(text, containerWidth, containerHeight, isKannada, baseSize = 14) {
    if (!text || containerWidth <= 0 || containerHeight <= 0) {
        return 12;
    }

    const tempCanvas = document.createElement('canvas');
    const tempCtx = tempCanvas.getContext('2d');
    const fontFamily = isKannada ? "'Noto Sans Kannada'" : "'Noto Sans'";
    
    // Start with the OCR-provided height or baseSize
    let fontSize = Math.max(8, baseSize);
    
    // Ensure height fits
    if (fontSize > containerHeight * 0.9) {
        fontSize = containerHeight * 0.9;
    }
    
    // Binary search for width fit
    let min = 6;
    let max = fontSize;
    let optimalSize = min;
    
    for (let i = 0; i < 10; i++) { // 10 iterations for better precision
        const mid = (min + max) / 2;
        tempCtx.font = `${mid}px ${fontFamily}`;
        const metrics = tempCtx.measureText(text);
        
        if (metrics.width <= containerWidth * 0.99) {
            optimalSize = mid;
            min = mid;
        } else {
            max = mid;
        }
    }
    
    return Math.max(8, Math.min(optimalSize, 64));
}

function renderTextBoxes(show = true) {
    const container = document.getElementById('textBoxesContainer');
    container.innerHTML = '';

    if (!show) return;

    state.textBoxes.forEach((box) => {
        const boxEl = document.createElement('div');
        boxEl.className = 'text-box';
        boxEl.id = `box-${box.id}`;
        
        // Scale and position coordinates
        const scaledX = box.x * state.canvasScale + state.canvasOffsetX;
        const scaledY = box.y * state.canvasScale + state.canvasOffsetY;
        const scaledWidth = box.width * state.canvasScale;
        const scaledHeight = box.height * state.canvasScale;
        
        boxEl.style.left = `${scaledX}px`;
        boxEl.style.top = `${scaledY}px`;
        boxEl.style.width = `${scaledWidth}px`;
        boxEl.style.height = `${scaledHeight}px`;
        
        // Use robust font size calculation (scaled for screen)
        const fontSize = calculateOptimalFontSize(
            box.text, 
            scaledWidth, 
            scaledHeight, 
            box.kannada, 
            (box.fontSize || 14) * state.canvasScale
        );
        boxEl.style.fontSize = `${fontSize}px`;
        boxEl.style.fontFamily = box.kannada ? "'Noto Sans Kannada'" : "'Noto Sans'";
        boxEl.dataset.boxId = box.id;
        boxEl.innerHTML = `<span>${escapeHtml(box.text)}</span>`;

        boxEl.addEventListener('click', (e) => {
            e.stopPropagation();
            makeBoxEditable(box.id);
        });

        container.appendChild(boxEl);
    });
}

function makeBoxEditable(boxId) {
    // Clear previous editing
    if (state.editingBoxId !== null) {
        saveBoxEdit(state.editingBoxId);
    }

    const box = state.textBoxes.find(b => b.id === boxId);
    const boxEl = document.getElementById(`box-${boxId}`);

    if (!box || !boxEl) return;

    boxEl.classList.add('editing');
    
    const input = document.createElement('input');
    input.type = 'text';
    input.value = box.text;
    input.style.fontFamily = box.kannada ? "'Noto Sans Kannada'" : "'Noto Sans'";
    
    boxEl.innerHTML = '';
    boxEl.appendChild(input);
    input.focus();
    input.select();

    state.editingBoxId = boxId;

    // Recalculate font size for new text
    const newFontSize = calculateOptimalFontSize(input.value, boxEl.offsetWidth, boxEl.offsetHeight, box.kannada);
    input.style.fontSize = `${newFontSize}px`;
    
    // Save on blur or Enter
    input.addEventListener('blur', () => saveBoxEdit(boxId));
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') saveBoxEdit(boxId);
        if (e.key === 'Escape') cancelBoxEdit(boxId);
    });
}

function saveBoxEdit(boxId) {
    const box = state.textBoxes.find(b => b.id === boxId);
    const boxEl = document.getElementById(`box-${boxId}`);
    const input = boxEl.querySelector('input');

    if (input) {
        const newText = input.value.trim();
        if (newText && newText !== box.text) {
            box.text = newText;
            state.edited = true;   // forces a rebuild so edits reach the DOCX
        }
    }

    boxEl.classList.remove('editing');
    
    // Use actual font size from OCR after edit
    const fontSize = getFontSizeForBox(box, boxEl.offsetWidth, boxEl.offsetHeight);
    boxEl.style.fontSize = `${fontSize}px`;
    
    boxEl.innerHTML = `<span>${escapeHtml(box.text)}</span>`;
    state.editingBoxId = null;

    boxEl.addEventListener('click', (e) => {
        e.stopPropagation();
        makeBoxEditable(boxId);
    });
}

function cancelBoxEdit(boxId) {
    const boxEl = document.getElementById(`box-${boxId}`);
    if (boxEl) {
        boxEl.classList.remove('editing');
        renderTextBoxes(true);
        state.editingBoxId = null;
    }
}

// ===== DOWNLOAD & EXPORT =====
function updateDiagnostics() {
    const el = document.getElementById('imageInfo');
    if (!el || !state.diagnostics) return;
    const d = state.diagnostics;
    el.innerHTML = `
        <strong>Engine:</strong> ${state.engine}<br>
        <strong>Lines detected:</strong> ${d.lines_detected} (${d.lines_rendered} kept)<br>
        <strong>Skew corrected:</strong> ${d.skew_deg}&deg;<br>
        <strong>Page area:</strong> ${(d.page_fraction * 100).toFixed(1)}% of frame<br>
        <strong>Alignment:</strong> ${d.alignment_median_pct}% median<br>
        <strong>Job ID:</strong> ${state.jobId}
    `;
}

async function downloadDocx() {
    // /extract already produced the aligned DOCX - just fetch it.
    if (state.alignedDocxUrl && !state.edited) {
        showStatus('Downloading aligned DOCX...', 'loading');
        try {
            const r = await fetch(state.alignedDocxUrl);
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            downloadFile(await r.blob(), `ocr_${state.jobId}_aligned.docx`,
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document');
            showStatus('✓ Aligned DOCX downloaded', 'success');
            return;
        } catch (e) {
            showStatus(`Falling back to regenerate: ${e.message}`, 'loading');
        }
    }
    // Text was edited (or no cached docx) -> rebuild with the user's edits.
    return regenerateDocx();
}

async function regenerateDocx() {
    if (!state.image || !state.textBoxes.length) {
        showStatus('No OCR data to export', 'error');
        return;
    }

    showStatus('Generating DOCX with your edits...', 'loading');

    try {
        state.canvas.toBlob(async (blob) => {
            const formData = new FormData();
            formData.append('image', blob, 'image.png');
            
            // Send edited text data to backend
            formData.append('text_data', JSON.stringify(state.textBoxes));

            // Call /formatted endpoint to get DOCX with edited overlaid text
            const response = await fetch(`${state.apiBaseUrl}/formatted`, {
                method: 'POST',
                body: formData
            });

            if (!response.ok) {
                throw new Error(`API error: ${response.status}`);
            }

            const docxBlob = await response.blob();
            downloadFile(docxBlob, `ocr_${state.jobId}.docx`, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document');
            showStatus('✓ DOCX downloaded successfully!', 'success');
        });
    } catch (error) {
        console.error('Download Error:', error);
        showStatus(`Error: ${error.message}`, 'error');
    }
}

async function createDocxPreview() {
    if (!state.image || !state.textBoxes.length) {
        showStatus('No OCR data to export', 'error');
        return;
    }

    showStatus('Generating DOCX preview...', 'loading');

    try {
        state.canvas.toBlob(async (blob) => {
            const formData = new FormData();
            formData.append('image', blob, 'image.png');
            
            // Send text data with font sizes to backend
            formData.append('text_data', JSON.stringify(state.textBoxes));

            const response = await fetch(`${state.apiBaseUrl}/formatted`, {
                method: 'POST',
                body: formData
            });

            if (!response.ok) {
                throw new Error(`API error: ${response.status}`);
            }

            const docxBlob = await response.blob();
            const docxUrl = window.URL.createObjectURL(docxBlob);
            
            // Store DOCX for download
            state.docxUrl = docxUrl;
            state.docxFilename = `ocr_${state.jobId}.docx`;
            
            // Auto-download
            const link = document.createElement('a');
            link.href = docxUrl;
            link.download = state.docxFilename;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            
            showStatus('✓ DOCX created and downloaded! Preview shows exact layout.', 'success');
        });
    } catch (error) {
        console.error('DOCX Creation Error:', error);
        showStatus(`Error: ${error.message}`, 'error');
    }
}

async function createDocxAfterExtraction() {
    // Called automatically after extractOCR completes
    // Creates DOCX with same exact layout as preview
    try {
        if (!state.image || !state.textBoxes.length) {
            showStatus('No OCR data to export', 'error');
            return;
        }

        state.canvas.toBlob(async (blob) => {
            const formData = new FormData();
            formData.append('image', blob, 'image.png');
            
            // Send text data with font sizes to backend
            formData.append('text_data', JSON.stringify(state.textBoxes));

            const response = await fetch(`${state.apiBaseUrl}/formatted`, {
                method: 'POST',
                body: formData
            });

            if (!response.ok) {
                throw new Error(`API error: ${response.status}`);
            }

            const docxBlob = await response.blob();
            
            // Auto-download DOCX
            const link = document.createElement('a');
            link.href = window.URL.createObjectURL(docxBlob);
            link.download = `ocr_${state.jobId}.docx`;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            window.URL.revokeObjectURL(link.href);
            
            showStatus('✓ DOCX created and downloaded! Preview shows exact layout above.', 'success');
        });
    } catch (error) {
        console.error('DOCX Creation Error:', error);
        showStatus(`DOCX creation failed: ${error.message}`, 'error');
    }
}

async function downloadPdf() {
    if (!state.image || !state.jobId) {
        showStatus('No OCR data to export', 'error');
        return;
    }

    showStatus('Downloading PDF...', 'loading');

    try {
        // Use /download endpoint to retrieve the searchable PDF generated during OCR
        const response = await fetch(`${state.apiBaseUrl}/download/${state.jobId}`);

        if (!response.ok) {
            throw new Error(`PDF not found: ${response.status}`);
        }

        const pdfBlob = await response.blob();
        downloadFile(pdfBlob, `ocr_${state.jobId}.pdf`, 'application/pdf');
        showStatus('✓ PDF downloaded successfully!', 'success');
    } catch (error) {
        console.error('PDF Download Error:', error);
        showStatus(`Error: ${error.message}`, 'error');
    }
}

function downloadFile(blob, filename, mimeType) {
    const url = window.URL.createObjectURL(new Blob([blob], { type: mimeType }));
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.parentNode.removeChild(link);
    window.URL.revokeObjectURL(url);
}

// ===== STATISTICS & TEXT LIST =====
function updateStats() {
    let kannadaCount = 0;
    let englishCount = 0;

    state.textBoxes.forEach(box => {
        const text = box.text;
        kannadaCount += (text.match(/[\u0C80-\u0CFF]/g) || []).length;
        englishCount += (text.match(/[a-zA-Z]/g) || []).length;
    });

    document.getElementById('statKannada').textContent = kannadaCount;
    document.getElementById('statEnglish').textContent = englishCount;
    document.getElementById('statLines').textContent = state.textBoxes.length;
}

function updateTextList() {
    const list = document.getElementById('textList');
    list.innerHTML = '';

    if (state.textBoxes.length === 0) {
        list.innerHTML = '<p class="empty-state">No text extracted yet</p>';
        return;
    }

    state.textBoxes.forEach((box, index) => {
        const item = document.createElement('div');
        item.className = 'text-item';
        item.innerHTML = `
            <strong>Line ${index + 1}:</strong><br>
            ${escapeHtml(box.text.substring(0, 50))}${box.text.length > 50 ? '...' : ''}
        `;
        item.addEventListener('click', () => makeBoxEditable(box.id));
        list.appendChild(item);
    });
}

// ===== UTILITY FUNCTIONS =====
function generateJobId() {
    return Math.random().toString(36).substring(2, 14);
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function showStatus(message, type = 'info') {
    const statusEl = document.getElementById('uploadStatus');
    statusEl.textContent = message;
    statusEl.className = `upload-status ${type}`;
    
    if (type !== 'loading') {
        setTimeout(() => {
            statusEl.textContent = '';
            statusEl.className = 'upload-status';
        }, 4000);
    }
}

function clearAll() {
    if (confirm('Clear all data? This cannot be undone.')) {
        state = {
            image: null,
            canvas: state.canvas,
            ctx: state.ctx,
            imagePath: null,
            jobId: null,
            ocrData: [],
            textBoxes: [],
            backgroundColor: '#ffffff',
            fontSize: 14,
            editingBoxId: null,
            apiBaseUrl: state.apiBaseUrl
        };

        document.getElementById('imageInput').value = '';
        document.getElementById('textBoxesContainer').innerHTML = '';
        document.getElementById('textList').innerHTML = '<p class="empty-state">No text extracted yet</p>';
        document.getElementById('imageInfo').innerHTML = '<p>No image loaded</p>';
        document.getElementById('extractBtn').disabled = true;
        document.getElementById('downloadDocxBtn').disabled = true;
        document.getElementById('downloadPdfBtn').disabled = true;
        document.getElementById('fontSizeSlider').value = 14;
        document.getElementById('fontSizeValue').textContent = 14;

        state.canvas.width = 800;
        state.canvas.height = 600;
        state.ctx.fillStyle = '#ffffff';
        state.ctx.fillRect(0, 0, 800, 600);

        showStatus('All data cleared', 'success');
    }
}

// ===== DOCUMENT CLICK HANDLER =====
document.addEventListener('click', () => {
    if (state.editingBoxId !== null) {
        saveBoxEdit(state.editingBoxId);
    }
});
