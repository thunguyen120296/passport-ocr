from utils.tesseract_config import configure_tesseract
import os
configure_tesseract()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers.passport import router as passport_router

app = FastAPI(
    title="Passport OCR Backend",
    description="Backend for Passport OCR — MRZ-first extraction with visual OCR for date of issue.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        os.getenv("FRONTEND_URL"),
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(
    passport_router,
    prefix="/api/v1/passport",
    tags=["Passport"],
)


@app.get("/health")
def health():
    import shutil

    import pytesseract

    tess = shutil.which("tesseract") or getattr(
        pytesseract.pytesseract, "tesseract_cmd", None
    )
    return {
        "status": "ok",
        "tesseract": tess,
    }
