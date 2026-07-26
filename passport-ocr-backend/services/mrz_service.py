import os
import re
from datetime import datetime
from typing import Any, Optional

import cv2
from fastapi import HTTPException
from passporteye import read_mrz
from passporteye.mrz.text import MRZ, MRZOCRCleaner


class MRZService:
    """Extract passport fields from the Machine-Readable Zone via PassportEye."""

    def extract(
        self,
        image_path: str,
        fallback_path: Optional[str] = None,
        extra_paths: Optional[list[str]] = None,
        pdf_text: Optional[str] = None,
    ) -> dict[str, Any]:
        """Try PDF text layer, PassportEye, then Tesseract MRZ fallback."""
        best: Optional[dict[str, Any]] = None
        best_score = -1
        last_error: Optional[Exception] = None

        if pdf_text:
            from_text = self._parse_from_plain_text(pdf_text)
            if from_text:
                score = self._score(from_text)
                if score > best_score:
                    best = from_text
                    best_score = score
                if best_score >= 100 and best and best.get("checksum_valid"):
                    return best

        candidates: list[str] = []
        for path in (image_path, fallback_path, *(extra_paths or [])):
            if path and os.path.isfile(path) and path not in candidates:
                candidates.append(path)

        for path in candidates:
            for attempt_path in self._attempt_paths(path):
                try:
                    mrz = read_mrz(attempt_path, extra_cmdline_params="--psm 6")
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    continue

                if mrz is None:
                    continue

                for parsed in self._candidates_from_mrz(mrz):
                    score = self._score(parsed)
                    if score > best_score:
                        best = parsed
                        best_score = score

                if best_score >= 100 and best and best.get("checksum_valid"):
                    return best

        for path in candidates:
            ocr_parsed = self._ocr_mrz_fallback(path)
            if not ocr_parsed:
                continue
            score = self._score(ocr_parsed)
            if score > best_score:
                best = ocr_parsed
                best_score = score

        if best is not None and best_score > 0:
            return best

        if last_error is not None:
            raise HTTPException(
                status_code=422,
                detail=f"MRZ_PARSE_FAILED: {last_error}",
            ) from last_error

        raise HTTPException(
            status_code=422,
            detail="MRZ_NOT_FOUND: Could not detect MRZ. "
            "Ensure Tesseract OCR is installed, then retry with a clear "
            "JPG/PNG or a 300 DPI PDF of the passport biodata page.",
        )

    def _parse_from_plain_text(self, text: str) -> Optional[dict[str, Any]]:
        lines = self._lines_from_raw_text(text)
        if len(lines) < 2:
            compact = re.sub(r"[^A-Z0-9<\n]", "", text.upper())
            lines = self._lines_from_raw_text(compact)
        if len(lines) < 2:
            return None

        cleaned = [
            self._pad44(self._pre_clean_line(lines[0], True)),
            self._pad44(self._pre_clean_line(lines[1], False)),
        ]

        candidates: list[dict[str, Any]] = []
        try:
            exact = self._normalize(MRZ(MRZOCRCleaner.apply("\n".join(cleaned))))
            raw = exact.get("raw") or {}
            raw["raw_text"] = "\n".join(cleaned)
            raw["from_pdf_text"] = True
            exact["raw"] = raw
            candidates.append(exact)
        except Exception:
            pass

        repaired = self._repair_and_parse(lines[:2])
        for item in repaired:
            raw = item.get("raw") or {}
            raw["from_pdf_text"] = True
            item["raw"] = raw
            candidates.append(item)

        if not candidates:
            return None

        return max(candidates, key=self._score)

    def _attempt_paths(self, image_path: str) -> list[str]:
        paths = [image_path]
        cropped = self._save_content_crop(image_path)
        if cropped:
            paths.insert(0, cropped)
        for src in list(paths):
            roi = self._save_mrz_roi(src)
            if roi and roi not in paths:
                paths.insert(0, roi)
        return paths

    def _save_content_crop(self, image_path: str) -> Optional[str]:
        """Remove large white/gray padding so MRZ sits near the image bottom."""
        image = cv2.imread(image_path)
        if image is None:
            return None

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        mask = gray < 245
        coords = cv2.findNonZero(mask.astype("uint8") * 255)
        if coords is None:
            return None

        x, y, w, h = cv2.boundingRect(coords)
        ih, iw = gray.shape[:2]
        if w < iw * 0.4 or h < ih * 0.4:
            return None
        if w > iw * 0.98 and h > ih * 0.98:
            return None

        pad = 8
        x0, y0 = max(0, x - pad), max(0, y - pad)
        x1, y1 = min(iw, x + w + pad), min(ih, y + h + pad)
        crop = image[y0:y1, x0:x1]
        out_path = f"{os.path.splitext(image_path)[0]}_content.jpg"
        cv2.imwrite(out_path, crop)
        return out_path

    def _save_mrz_roi(self, image_path: str) -> Optional[str]:
        image = cv2.imread(image_path)
        if image is None:
            return None

        h, w = image.shape[:2]
        y0 = int(h * 0.62)
        roi = image[y0:h, 0:w]
        if roi.size == 0:
            return None

        if roi.shape[0] < 180:
            scale = 180 / max(roi.shape[0], 1)
            roi = cv2.resize(roi, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

        out_path = f"{os.path.splitext(image_path)[0]}_mrz_roi.jpg"
        cv2.imwrite(out_path, roi)
        return out_path

    def _ocr_mrz_fallback(self, image_path: str) -> Optional[dict[str, Any]]:
        """Tesseract MRZ read when PassportEye box-locator returns None."""
        try:
            import pytesseract
            from utils.tesseract_config import configure_tesseract

            configure_tesseract()
        except Exception:
            return None

        image = cv2.imread(image_path)
        if image is None:
            return None

        crops: list = []
        content_path = self._save_content_crop(image_path)
        sources = [image]
        if content_path:
            content = cv2.imread(content_path)
            if content is not None:
                sources.insert(0, content)

        for src in sources:
            h = src.shape[0]
            for frac in (0.55, 0.62, 0.70, 0.75):
                band = src[int(h * frac) : h, :]
                if band.size:
                    crops.append(band)

        cfg = (
            "--oem 3 --psm 6 "
            "-c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<"
        )
        best: Optional[dict[str, Any]] = None
        best_score = -1

        for crop in crops:
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if len(crop.shape) == 3 else crop
            if gray.shape[0] < 120:
                gray = cv2.resize(gray, None, fx=2.5, fy=2.5, interpolation=cv2.INTER_CUBIC)
            _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

            for variant in (gray, th):
                try:
                    text = pytesseract.image_to_string(variant, config=cfg)
                except Exception:
                    continue
                parsed = self._parse_from_plain_text(text)
                if not parsed:
                    continue
                raw = parsed.get("raw") or {}
                raw["tesseract_mrz_fallback"] = True
                parsed["raw"] = raw
                score = self._score(parsed)
                if score > best_score:
                    best = parsed
                    best_score = score

        return best

    def _candidates_from_mrz(self, mrz: Any) -> list[dict[str, Any]]:
        base = self._normalize(mrz)
        results = [base]

        raw = base.get("raw") or {}
        raw_text = raw.get("raw_text") or raw.get("text") or ""
        lines = self._lines_from_raw_text(raw_text)

        if len(lines) >= 2:
            repaired = self._repair_and_parse(lines)
            results.extend(repaired)

        results.append(self._maybe_force_td3(base))
        return results

    def _lines_from_raw_text(self, raw_text: str) -> list[str]:
        lines: list[str] = []
        if not raw_text:
            return lines
        for ln in raw_text.splitlines():
            ln = re.sub(r"\s+", "", ln.upper())
            ln = re.sub(r"[^A-Z0-9<]", "", ln)
            if len(ln) >= 20 or "<<" in ln:
                lines.append(ln)
        return lines[:3]

    def _repair_and_parse(self, lines: list[str]) -> list[dict[str, Any]]:
        """Checksum-guided cleanup for common OCR mistakes on TD3 passport MRZ."""
        if len(lines) < 2:
            return []

        line1 = self._pre_clean_line(lines[0], is_first=True)
        line2 = self._pre_clean_line(lines[1], is_first=False)

        variants_l1 = self._line1_variants(line1)
        variants_l2 = self._line2_variants(line2)

        ranked_l2: list[tuple[int, str]] = []
        seed_l1 = self._pad44(line1)
        for b in variants_l2:
            try:
                mrz = MRZ(MRZOCRCleaner.apply(f"{seed_l1}\n{b}"))
                raw = mrz.to_dict()
                s = 0
                if raw.get("valid_number"):
                    s += 40
                if raw.get("valid_date_of_birth"):
                    s += 30
                if raw.get("valid_expiration_date"):
                    s += 30
                ranked_l2.append((s, b))
            except Exception:
                ranked_l2.append((0, b))
        ranked_l2.sort(key=lambda x: x[0], reverse=True)
        top_l2 = [b for _, b in ranked_l2[:5]]

        parsed_list: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        for b in top_l2:
            for a in variants_l1:
                key = (a, b)
                if key in seen:
                    continue
                seen.add(key)
                try:
                    cleaned = MRZOCRCleaner.apply(f"{a}\n{b}")
                    mrz = MRZ(cleaned)
                except Exception:  # noqa: BLE001
                    continue
                item = self._normalize(mrz)
                raw = item.get("raw") or {}
                raw["raw_text"] = f"{a}\n{b}"
                raw["repaired"] = True
                item["raw"] = raw
                parsed_list.append(item)

        return parsed_list

    def _pre_clean_line(self, line: str, is_first: bool) -> str:
        s = line.upper().replace(" ", "")
        s = re.sub(r"[^A-Z0-9<]", "", s)

        if is_first:
            if s.startswith("PS"):
                s = "P<" + s[2:]
            elif s.startswith("PK"):
                s = "P<" + s[2:]
            elif s.startswith("P") and len(s) > 1 and s[1] != "<":
                s = "P<" + s[1:]

        s = re.sub(r"K+", lambda m: "<" * len(m.group()), s)
        s = re.sub(r"S{3,}", lambda m: "<" * len(m.group()), s)

        s = re.sub(r"([A-Z]{2,})S([A-Z])(<|$)", r"\1<\2\3", s)

        if len(s) > 20:
            head, tail = s[:-12], s[-12:]
            tail = re.sub(r"[A-Z]", "<", tail)
            s = head + tail

        return s

    def _line1_variants(self, line: str) -> list[str]:
        base = line if len(line) >= 30 else line + ("<" * (44 - len(line)))
        variants = [self._pad44(base)]

        core = base.rstrip("<")
        if len(core) > 10:
            for i in range(5, min(len(core), 40)):
                variants.append(self._pad44(core[:i] + core[i + 1 :]))
            for i in range(5, min(len(core) - 1, 39)):
                variants.append(self._pad44(core[:i] + core[i + 2 :]))

        for v in list(variants[:10]):
            variants.append(self._pad44(re.sub(r"[A-Z]+$", "", v.rstrip("<")) + ("<" * 10)))

        out: list[str] = []
        seen: set[str] = set()
        for v in variants:
            if v in seen:
                continue
            seen.add(v)
            if v.startswith("P<") or v.startswith("P"):
                out.append(v)
        return out[:60] if out else [self._pad44(base)]

    def _line2_variants(self, line: str) -> list[str]:
        s = line.replace(" ", "")
        s = re.sub(r"K+", lambda m: "<" * len(m.group()), s)
        variants = [self._pad44(s)]

        if len(s) < 44 and len(s) >= 30 and s[-2:].isdigit():
            body, checks = s[:-2], s[-2:]
            need = 44 - len(s)
            variants.append(self._pad44(body + ("<" * need) + checks))
           
            if len(body) >= 28:
                variants.append(body[:28] + ("<" * need) + body[28:] + checks)

        if len(s) > 44:
            variants.append(self._pad44(s[:44]))

            if s[-2:].isdigit():
                body = s[:-2]
                while len(body) > 42:
                    body = body[:28] + body[29:] if len(body) > 28 else body[:-1]
                variants.append(self._pad44(body + s[-2:]))

        elif len(s) < 44:
            for i in range(28, min(len(s) + 1, 42)):
                trial = s[:i] + "<" + s[i:]
                variants.append(self._pad44(trial))

        out: list[str] = []
        seen: set[str] = set()
        for v in variants:
            vv = v if len(v) == 44 else self._pad44(v)

            if vv not in seen:
                seen.add(vv)
                out.append(vv)
        return out[:30]

    def _pad44(self, line: str) -> str:
        s = re.sub(r"[^A-Z0-9<]", "", line.upper())
        if len(s) < 44:
            s = s + ("<" * (44 - len(s)))
        return s[:44]

    def _normalize(self, mrz: Any) -> dict[str, Any]:
        raw = mrz.to_dict() if hasattr(mrz, "to_dict") else dict(mrz)

        surname = self._clean_name(raw.get("surname") or raw.get("last_name"))
        given_name = self._clean_name(
            raw.get("names") or raw.get("given_name") or raw.get("first_name")
        )

        date_of_birth = self._mrz_date_to_iso(raw.get("date_of_birth") or raw.get("birth_date"))
        date_of_expiry = self._mrz_date_to_iso(
            raw.get("expiration_date") or raw.get("expiry_date")
        )

        return {
            "surname": surname,
            "given_name": given_name,
            "date_of_birth": date_of_birth,
            "date_of_expiry": date_of_expiry,
            "checksum_valid": self._checksum_ok(raw, mrz),
            "raw": raw,
        }

    def _maybe_force_td3(self, parsed: dict[str, Any]) -> dict[str, Any]:
        raw = parsed.get("raw") or {}
        mrz_type = raw.get("mrz_type")
        if mrz_type == "TD3" and parsed.get("checksum_valid"):
            return parsed

        raw_text = raw.get("raw_text") or raw.get("text") or ""
        lines = self._lines_from_raw_text(raw_text)
        if len(lines) < 2:
            return parsed

        first = lines[0]
        if not first.upper().startswith("P") and mrz_type != "TD2":
            return parsed

        padded = [self._pad44(self._pre_clean_line(lines[0], True)), self._pad44(self._pre_clean_line(lines[1], False))]
        try:
            forced = MRZ(MRZOCRCleaner.apply("\n".join(padded)))
        except Exception:  # noqa: BLE001
            return parsed

        forced_parsed = self._normalize(forced)
        forced_raw = forced_parsed.get("raw") or {}
        forced_raw["raw_text"] = raw_text
        forced_raw["forced_td3"] = True
        forced_parsed["raw"] = forced_raw

        if self._score(forced_parsed) >= self._score(parsed):
            return forced_parsed
        return parsed

    def _score(self, parsed: dict[str, Any]) -> int:
        raw = parsed.get("raw") or {}
        score = 0
        try:
            score = int(raw.get("valid_score") or 0)
        except (TypeError, ValueError):
            score = 0

        if parsed.get("checksum_valid"):
            score += 30
        if raw.get("valid_number"):
            score += 15
        if raw.get("valid_date_of_birth"):
            score += 15
        if raw.get("valid_expiration_date"):
            score += 15

        if parsed.get("date_of_birth"):
            score += 10
        if parsed.get("date_of_expiry"):
            score += 10
        if raw.get("mrz_type") == "TD3":
            score += 15

        surname = (parsed.get("surname") or "").strip()
        given = (parsed.get("given_name") or "").strip()

        if surname:
            score += 10

            if 3 <= len(surname) <= 15 and re.fullmatch(r"[A-Za-z]+(?: [A-Za-z]+)*", surname):
                score += 20
                score += max(0, 8 - abs(len(surname) - 5))
            else:
                score -= 10

        if given:
            score += 10
            if re.fullmatch(r"[A-Za-z]+(?: [A-Za-z]+)*", given) and len(given) <= 30:
                score += 20
            else:
                score -= 10
            if re.search(r"\s{2,}|[A-Z]$", given) and not re.fullmatch(
                r"[A-Za-z]+(?: [A-Za-z])?", given
            ):
                score -= 15

        raw_text = raw.get("raw_text") or ""
        if "<<" in raw_text:
            score += 5
        if raw_text.upper().startswith("P<"):
            score += 5
        return score

    def _clean_name(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        cleaned = value.replace("<", " ")
        cleaned = re.sub(r"[KX]{2,}", " ", cleaned, flags=re.I)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        parts = cleaned.split(" ")
        while len(parts) > 2 and len(parts[-1]) == 1 and parts[-1].upper() in "KXES":
            parts.pop()
        if len(parts) >= 3 and all(len(p) == 1 for p in parts[1:]):
            cleaned = " ".join(parts[:2])
        elif len(parts) >= 3 and len(parts[-1]) == 1 and len(parts[-2]) == 1:
            cleaned = " ".join(parts[:-1])
        else:
            cleaned = " ".join(parts)
        return cleaned or None

    def _mrz_date_to_iso(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None

        digits = "".join(ch for ch in str(value) if ch.isdigit())
        if len(digits) != 6:
            return None

        yy = int(digits[0:2])
        mm = int(digits[2:4])
        dd = int(digits[4:6])

        current_yy = datetime.now().year % 100
        current_century = (datetime.now().year // 100) * 100
        year = current_century + yy
        if yy > current_yy + 20:
            year -= 100

        try:
            return datetime(year, mm, dd).strftime("%Y-%m-%d")
        except ValueError:
            return None

    def _checksum_ok(self, raw: dict, mrz: Any) -> bool:
        if hasattr(mrz, "valid") and isinstance(mrz.valid, bool):
            return mrz.valid

        if "valid" in raw and isinstance(raw["valid"], bool):
            return raw["valid"]

        score = raw.get("valid_score")
        if score is not None:
            try:
                return float(score) >= 70
            except (TypeError, ValueError):
                pass

        flags = [
            raw.get("valid_number"),
            raw.get("valid_date_of_birth"),
            raw.get("valid_expiration_date"),
            raw.get("valid_composite"),
        ]
        bool_flags = [f for f in flags if isinstance(f, bool)]
        if bool_flags:
            return all(bool_flags)

        return False
