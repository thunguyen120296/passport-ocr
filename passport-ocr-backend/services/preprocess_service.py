import os

import cv2
import numpy as np
from fastapi import HTTPException


class PreprocessService:
    """Basic image cleanup for passport photos: lighting, skew, light noise."""

    def process(self, path: str) -> str:
        image = cv2.imread(path)
        if image is None:
            raise HTTPException(
                status_code=400,
                detail="Cannot read image. File may be corrupted or unsupported.",
            )

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)

        deskewed = self._deskew(enhanced)

        denoised = cv2.fastNlMeansDenoising(deskewed, None, h=7, templateWindowSize=7, searchWindowSize=21)

        out_path = f"{os.path.splitext(path)[0]}_preprocessed.jpg"
        cv2.imwrite(out_path, denoised)
        return out_path

    def _deskew(self, gray: np.ndarray) -> np.ndarray:
        """Estimate skew via minAreaRect on edges and rotate if needed."""
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blur, 50, 150, apertureSize=3)

        coords = np.column_stack(np.where(edges > 0))
        if coords.size == 0:
            return gray

        points = np.fliplr(coords).astype(np.float32)
        angle = cv2.minAreaRect(points)[-1]

        if angle < -45:
            angle = 90 + angle

        if abs(angle) < 0.5 or abs(angle) > 15:
            return gray

        (h, w) = gray.shape[:2]
        center = (w // 2, h // 2)
        matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(
            gray,
            matrix,
            (w, h),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REPLICATE,
        )
        return rotated
