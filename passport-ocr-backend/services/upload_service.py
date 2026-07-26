import os
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF
from fastapi import HTTPException, UploadFile

UPLOAD_DIR = "uploads"
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".pdf"}
MAX_FILE_SIZE_BYTES = 15 * 1024 * 1024  # 15 MB
PDF_RENDER_DPI = 300


@dataclass
class UploadResult:
    primary_path: str
    variant_paths: list[str] = field(default_factory=list)
    pdf_text: str | None = None
    source_ext: str = ""


class UploadService:
    def __init__(self, upload_dir: str = UPLOAD_DIR):
        self.upload_dir = upload_dir
        os.makedirs(self.upload_dir, exist_ok=True)

    def save(self, file: UploadFile) -> UploadResult:
        if not file.filename:
            raise HTTPException(status_code=400, detail="Filename is required.")

        ext = Path(file.filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type '{ext}'. Allowed: JPG, PNG, PDF.",
            )

        safe_stem = re.sub(r"[^a-zA-Z0-9_-]", "_", Path(file.filename).stem)[:80]
        unique_name = f"{safe_stem}_{uuid.uuid4().hex[:8]}{ext}"
        path = os.path.join(self.upload_dir, unique_name)

        size = 0
        with open(path, "wb") as buffer:
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_FILE_SIZE_BYTES:
                    buffer.close()
                    os.remove(path)
                    raise HTTPException(
                        status_code=400,
                        detail="File too large. Maximum size is 15 MB.",
                    )
                buffer.write(chunk)

        if ext == ".pdf":
            return self._pdf_to_images(path)

        return UploadResult(primary_path=path, variant_paths=[path], source_ext=ext)

    def _pdf_to_images(self, pdf_path: str) -> UploadResult:
        try:
            doc = fitz.open(pdf_path)
            if doc.page_count < 1:
                raise HTTPException(status_code=400, detail="PDF has no pages.")

            page = doc.load_page(0)
            base = os.path.splitext(pdf_path)[0]
            variants: list[str] = []

            pdf_text = (page.get_text("text") or "").strip() or None

            embedded_path = f"{base}_embedded.jpg"
            embedded = self._extract_largest_embedded_image(doc, page, embedded_path)
            if embedded:
                variants.append(embedded)
                try:
                    import cv2

                    emb_img = cv2.imread(embedded)
                    if emb_img is not None and emb_img.shape[1] < 1600:
                        scale = 1600 / emb_img.shape[1]
                        up = cv2.resize(
                            emb_img,
                            None,
                            fx=scale,
                            fy=scale,
                            interpolation=cv2.INTER_CUBIC,
                        )
                        up_path = f"{base}_embedded_up.jpg"
                        cv2.imwrite(up_path, up)
                        variants.append(up_path)
                except Exception:
                    pass

            raster_path = f"{base}_page0.jpg"
            zoom = PDF_RENDER_DPI / 72.0
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            if pix.width > 3500 or pix.height > 3500:
                scale = min(3500 / pix.width, 3500 / pix.height)
                pix = page.get_pixmap(
                    matrix=fitz.Matrix(zoom * scale, zoom * scale),
                    alpha=False,
                )
            pix.save(raster_path)
            variants.append(raster_path)

            if pix.width >= 2000:
                mid_path = f"{base}_page0_200dpi.jpg"
                mid_zoom = 200 / 72.0
                mid = page.get_pixmap(matrix=fitz.Matrix(mid_zoom, mid_zoom), alpha=False)
                mid.save(mid_path)
                variants.append(mid_path)

            doc.close()

            if not variants:
                raise HTTPException(status_code=400, detail="Failed to convert PDF to image.")

            primary = variants[0]
            return UploadResult(
                primary_path=primary,
                variant_paths=variants,
                pdf_text=pdf_text,
                source_ext=".pdf",
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to convert PDF to image: {exc}",
            ) from exc

    def _extract_largest_embedded_image(
        self,
        doc: fitz.Document,
        page: fitz.Page,
        out_path: str,
    ) -> str | None:
        try:
            images = page.get_images(full=True)
        except Exception:
            return None

        if not images:
            return None

        best_xref = None
        best_area = 0
        for img in images:
            xref = img[0]
            try:
                width = int(img[2]) if len(img) > 2 and img[2] else 0
                height = int(img[3]) if len(img) > 3 and img[3] else 0
            except (TypeError, ValueError):
                width, height = 0, 0
            area = width * height
            if area > best_area:
                best_area = area
                best_xref = xref

        if best_xref is None or best_area < 200_000:
            return None

        try:
            pix = fitz.Pixmap(doc, best_xref)
            if pix.n >= 5:
                pix = fitz.Pixmap(fitz.csRGB, pix)

            if pix.width < 1200:
                scale = 1200 / max(pix.width, 1)
                pil_img = pix.pil_image()
                new_size = (int(pil_img.width * scale), int(pil_img.height * scale))
                pil_img = pil_img.resize(new_size)
                pil_img.convert("RGB").save(out_path, quality=95)
            else:
                pix.save(out_path)
            return out_path
        except Exception:
            return None
