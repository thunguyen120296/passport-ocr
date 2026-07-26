from fastapi import UploadFile

from models.passport import PassportExtractResponse
from services.mrz_service import MRZService
from services.ocr_service import OCRService
from services.preprocess_service import PreprocessService
from services.upload_service import UploadService
from services.validation_service import ValidationService


class PassportService:
    def __init__(self):
        self.upload_service = UploadService()
        self.preprocess_service = PreprocessService()
        self.mrz_service = MRZService()
        self.ocr_service = OCRService()
        self.validation_service = ValidationService()

    def extract(self, file: UploadFile) -> PassportExtractResponse:
        upload = self.upload_service.save(file)
        path = upload.primary_path

        processed_paths: list[str] = []
        for variant in upload.variant_paths or [path]:
            try:
                processed_paths.append(self.preprocess_service.process(variant))
            except Exception:
                continue

        processed_path = processed_paths[0] if processed_paths else None

        mrz = self.mrz_service.extract(
            path,
            fallback_path=processed_path,
            extra_paths=[*(upload.variant_paths or []), *processed_paths],
            pdf_text=upload.pdf_text,
        )

        date_of_issue = None
        for candidate in [path, *(upload.variant_paths or []), *processed_paths]:
            date_of_issue = self.ocr_service.extract_issue_date(candidate)
            if date_of_issue:
                break

        raw = mrz.get("raw")
        if isinstance(raw, dict):
            raw = {k: v for k, v in raw.items() if k != "mrz_obj"}

        validation = self.validation_service.validate(mrz, date_of_issue)

        return PassportExtractResponse(
            surname=mrz.get("surname"),
            given_name=mrz.get("given_name"),
            date_of_birth=mrz.get("date_of_birth"),
            date_of_issue=date_of_issue,
            date_of_expiry=mrz.get("date_of_expiry"),
            validation=validation,
            raw_mrz=raw,
        )
