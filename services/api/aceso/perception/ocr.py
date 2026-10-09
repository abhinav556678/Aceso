import os
import logging

try:
    from pdf2image import convert_from_path
    import pytesseract
except ImportError:
    convert_from_path = None
    pytesseract = None

logger = logging.getLogger(__name__)

def process_document(payload: dict) -> dict:
    file_path = payload.get("file_path")
    if not file_path or not os.path.exists(file_path):
        raise FileNotFoundError(f"Document file not found: {file_path}")
    
    if convert_from_path is None or pytesseract is None:
        logger.warning("OCR libraries not available. Returning mock data.")
        return {
            "text": "Mock document text.",
            "pages": [{"page_number": 1, "text": "Mock document text.", "blocks": []}]
        }
        
    # Convert PDF to images
    # NOTE: requires poppler installed on system for pdf2image to work
    try:
        pages = convert_from_path(file_path)
    except Exception as e:
        raise RuntimeError(f"Failed to convert PDF: {str(e)}. (Is poppler installed?)")

    result_pages = []
    full_text = []

    for i, page_image in enumerate(pages):
        # Extract dictionary with bounding boxes
        ocr_data = pytesseract.image_to_data(page_image, output_type=pytesseract.Output.DICT)
        
        page_text = pytesseract.image_to_string(page_image)
        full_text.append(page_text)
        
        blocks = []
        n_boxes = len(ocr_data['level'])
        for j in range(n_boxes):
            text = ocr_data['text'][j].strip()
            if text:
                blocks.append({
                    "text": text,
                    "x": ocr_data['left'][j],
                    "y": ocr_data['top'][j],
                    "w": ocr_data['width'][j],
                    "h": ocr_data['height'][j],
                    "confidence": ocr_data['conf'][j]
                })
                
        result_pages.append({
            "page_number": i + 1,
            "text": page_text,
            "blocks": blocks
        })
        
    return {
        "text": "\n\n".join(full_text),
        "pages": result_pages
    }
