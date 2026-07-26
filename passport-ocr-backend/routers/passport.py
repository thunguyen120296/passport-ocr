from fastapi import APIRouter, File, HTTPException, UploadFile

from models.passport import PassportExtractResponse

router = APIRouter()
_passport_service = None


def get_passport_service():
    global _passport_service
    if _passport_service is None:
        from utils.tesseract_config import configure_tesseract

        configure_tesseract()
        from services.passport_service import PassportService

        _passport_service = PassportService()
    return _passport_service


@router.post("/extract", response_model=PassportExtractResponse)
async def extract(file: UploadFile = File(...)):
    if not file.content_type and not file.filename:
        raise HTTPException(status_code=400, detail="Empty upload.")

    return get_passport_service().extract(file)
