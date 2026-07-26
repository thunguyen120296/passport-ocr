import re
from datetime import datetime
from typing import Optional

import cv2
import pytesseract
from dateutil import parser as date_parser

from utils.tesseract_config import configure_tesseract

configure_tesseract()


class OCRService:
    """Extract Date of Issue from the visual zone using Tesseract OCR."""

    ISSUE_LABEL_PATTERNS = [
        r"date\s*of\s*issue",
        r"date\s*of\s*iss",
        r"\bissue\b",
        r"issued?\s*on",
        r"date\s*d['’]?\s*emission",
        r"ngay\s*cap",
        r"ngày\s*cấp",
        r"issue\s*date",
    ]

    EXPIRY_LABEL_PATTERNS = [
        r"date\s*of\s*expir",
        r"\bexpir",
        r"valid\s*until",
        r"ngày\s*h[eế]t",
    ]

    DATE_PATTERNS = [
        re.compile(r"\b(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4})\b", re.I),
        re.compile(r"\b(\d{1,2}\s+[A-Za-z]{3,9}\.?\s+\d{2,4})\b", re.I),
        re.compile(r"\b(\d{4}[/.\-]\d{1,2}[/.\-]\d{1,2})\b", re.I),
    ]

    def extract_issue_date(self, image_path: str) -> Optional[str]:
        texts: list[str] = []
        for text in self._ocr_variants(image_path):
            if text:
                texts.append(text)

        for text in texts:
            issue = self._parse_issue_from_text(text)
            if issue:
                return issue
        return None

    def _ocr_variants(self, image_path: str) -> list[str]:
        image = cv2.imread(image_path)
        if image is None:
            return []

        h = image.shape[0]
        visual = image[0 : int(h * 0.78), :]
        variants = [visual]

        mid = image[int(h * 0.28) : int(h * 0.72), :]
        if mid.size:
            variants.append(mid)

        gray = cv2.cvtColor(visual, cv2.COLOR_BGR2GRAY) if len(visual.shape) == 3 else visual
        variants.append(gray)

        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        variants.append(thresh)

        results: list[str] = []
        for variant in variants:
            try:
                text = pytesseract.image_to_string(variant, config="--psm 6")
                if text and text.strip():
                    results.append(text)
                # Sparse layout alternative
                text2 = pytesseract.image_to_string(variant, config="--psm 4")
                if text2 and text2.strip() and text2 != text:
                    results.append(text2)
            except Exception:
                continue
        return results

    def _parse_issue_from_text(self, text: str) -> Optional[str]:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if not lines:
            return None

        for idx, line in enumerate(lines):
            if self._matches_any(line, self.ISSUE_LABEL_PATTERNS):
                window_lines = lines[max(0, idx - 1) : idx + 4]
                window = " ".join(window_lines)
                issue_date = self._date_after_label(window_lines, issue_idx=min(1, len(window_lines) - 1))
                if issue_date:
                    return issue_date
                parsed = self._find_date_in_text(window)
                if parsed and not self._looks_like_expiry_context(window, parsed):
                    return parsed

        joined = " ".join(lines)
        for pattern in self.ISSUE_LABEL_PATTERNS:
            m = re.search(
                pattern + r".{0,40}?" + r"(\d{1,2}\s+[A-Za-z]{3,9}\.?\s+\d{2,4}|\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4})",
                joined,
                flags=re.I,
            )
            if m:
                iso = self._to_iso(m.group(1))
                if iso:
                    return iso

        return None

    def _date_after_label(self, window_lines: list[str], issue_idx: int) -> Optional[str]:
        """Pick the first date after issue label that is not clearly the expiry date."""
        expiry_idxs = {
            i
            for i, ln in enumerate(window_lines)
            if self._matches_any(ln, self.EXPIRY_LABEL_PATTERNS)
        }

        for i, ln in enumerate(window_lines):
            if i < issue_idx:
                continue
            if i in expiry_idxs and not self._matches_any(ln, self.ISSUE_LABEL_PATTERNS):
                continue
            parsed = self._find_date_in_text(ln)
            if parsed:
                if self._matches_any(ln, self.EXPIRY_LABEL_PATTERNS) and not self._matches_any(
                    ln, self.ISSUE_LABEL_PATTERNS
                ):
                    continue
                return parsed
        return None

    def _looks_like_expiry_context(self, window: str, _date: str) -> bool:
        lower = window.lower()
        has_issue = any(re.search(p, lower) for p in self.ISSUE_LABEL_PATTERNS)
        has_expiry = any(re.search(p, lower) for p in self.EXPIRY_LABEL_PATTERNS)
        if has_issue and has_expiry:
            return False
        return has_expiry and not has_issue

    def _matches_any(self, text: str, patterns: list[str]) -> bool:
        normalized = text.lower().strip()
        return any(re.search(p, normalized) for p in patterns)

    def _find_date_in_text(self, text: str) -> Optional[str]:
        for match in self._iter_date_matches(text):
            iso = self._to_iso(match)
            if iso:
                return iso
        return None

    def _iter_date_matches(self, text: str):
        for pattern in self.DATE_PATTERNS:
            for m in pattern.finditer(text):
                yield m.group(1)

    def _to_iso(self, raw: str) -> Optional[str]:
        raw = raw.strip().replace(".", " ")
        try:
            dt = date_parser.parse(raw, dayfirst=True, fuzzy=True)
            if dt.year < 1950 or dt.year > 2100:
                return None
            return dt.strftime("%Y-%m-%d")
        except (ValueError, OverflowError, TypeError):
            return None
