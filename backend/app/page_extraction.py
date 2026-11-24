import shutil
import subprocess
import tempfile
from pathlib import Path

from pypdf import PdfReader


MIN_USEFUL_TEXT_CHARS = 20


def extract_pdf_pages(pdf_path: str, start_page: int = 1, limit: int = 10) -> dict:
    """Extract selectable text and OCR scanned pages using Urdu Tesseract."""
    if start_page < 1:
        raise ValueError("start_page must be at least 1")
    if limit < 1 or limit > 20:
        raise ValueError("limit must be between 1 and 20")

    if not shutil.which("pdftoppm") or not shutil.which("tesseract"):
        raise ValueError("PDF rendering or OCR tools are not installed")
    if not Path("/usr/share/tesseract-ocr").exists():
        raise ValueError("Tesseract language data is not installed")

    reader = PdfReader(pdf_path, strict=False)
    if reader.is_encrypted and not reader.decrypt(""):
        raise ValueError("PDF requires a password")

    page_count = len(reader.pages)
    if start_page > page_count:
        raise ValueError("start_page exceeds the PDF page count")

    end_page = min(start_page + limit - 1, page_count)
    results = []

    with tempfile.TemporaryDirectory(prefix="naatify-ocr-") as temp_dir:
        temp = Path(temp_dir)

        for page_number in range(start_page, end_page + 1):
            text = (reader.pages[page_number - 1].extract_text() or "").strip()
            ocr_text = ""
            method = "pdf_text"

            if len(text) < MIN_USEFUL_TEXT_CHARS:
                prefix = temp / f"page-{page_number}"
                try:
                    subprocess.run(
                        [
                            "pdftoppm", "-f", str(page_number), "-l", str(page_number),
                            "-r", "180", "-png", "-singlefile",
                            pdf_path, str(prefix),
                        ],
                        check=True,
                        capture_output=True,
                        timeout=45,
                    )
                    image_path = prefix.with_suffix(".png")
                    result = subprocess.run(
                        ["tesseract", str(image_path), "stdout", "-l", "urd"],
                        check=True,
                        capture_output=True,
                        text=True,
                        timeout=45,
                    )
                    ocr_text = result.stdout.strip()
                    method = "urdu_ocr"
                except subprocess.TimeoutExpired as exc:
                    raise ValueError(
                        f"OCR timed out on PDF page {page_number}; try a smaller range"
                    ) from exc
                except subprocess.CalledProcessError as exc:
                    detail = (exc.stderr or b"") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
                    if isinstance(detail, bytes):
                        detail = detail.decode("utf-8", errors="replace")
                    raise ValueError(
                        f"OCR failed on PDF page {page_number}: {detail[:200]}"
                    ) from exc

            final_text = text if len(text) >= MIN_USEFUL_TEXT_CHARS else ocr_text
            results.append({
                "page_number": page_number,
                "extracted_text": text,
                "ocr_text": ocr_text,
                "text_characters": len(final_text),
                "processing_status": (
                    "extracted" if len(text) >= MIN_USEFUL_TEXT_CHARS
                    else "needs_review" if ocr_text
                    else "needs_ocr"
                ),
                "page_type": "text" if len(text) >= MIN_USEFUL_TEXT_CHARS else "scanned",
                "review_status": "pending",
                "extraction_method": method,
            })

    return {
        "page_count": page_count,
        "start_page": start_page,
        "end_page": end_page,
        "pages": results,
    }
