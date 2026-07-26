import os
import shutil
from pathlib import Path

import pytesseract


def configure_tesseract() -> None:
    """Ensure Tesseract is discoverable by pytesseract and PassportEye (PATH)."""
    candidates = [
        Path(os.environ.get("TESSERACT_CMD", "")),
        Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
        Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
    ]

    tess_exe = None
    existing = shutil.which("tesseract")
    if existing:
        tess_exe = Path(existing)
    else:
        for candidate in candidates:
            if candidate and candidate.is_file():
                tess_exe = candidate
                break

    if tess_exe is None:
        return

    pytesseract.pytesseract.tesseract_cmd = str(tess_exe)
    tess_dir = str(tess_exe.parent)
    path = os.environ.get("PATH", "")
    if tess_dir.lower() not in path.lower():
        os.environ["PATH"] = tess_dir + os.pathsep + path
