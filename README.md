# Passport OCR

Trích xuất thông tin hộ chiếu từ file JPG/PNG/PDF theo pipeline **ưu tiên MRZ**, kết hợp OCR vùng visual cho **Ngày cấp** (Date of Issue).

## Cấu trúc thư mục liên quan

| Thư mục | Mô tả |
|---------|--------|
| `passport-ocr-backend/` | API FastAPI, xử lý ảnh / MRZ / OCR / validate |
| `passport-ocr-frontend/` | UI React cơ bản (upload + bảng kết quả) |
| `docs/` | Requirement, kiến trúc, kế hoạch triển khai |
| `demo/` | Hình ảnh dùng để test (JPG/PNG/PDF mẫu) |

## Kiến trúc

```
React (giao diện upload)
        │
        ▼
FastAPI  POST /api/v1/passport/extract
        │
        ├── UploadService      (kiểm tra file, PDF → ảnh qua PyMuPDF)
        ├── PreprocessService  (OpenCV: CLAHE, deskew, denoise)
        ├── MRZService         (PassportEye + Tesseract)
        ├── OCRService         (Tesseract vùng visual → Date of Issue)
        └── ValidationService  (checksum MRZ + quy tắc ngày tháng)
                │
                ▼
        JSON (5 trường + validation)
```

### Các trường được trích xuất

| Trường | Nguồn |
|--------|--------|
| Họ (Surname) | MRZ |
| Tên (Given name) | MRZ |
| Ngày sinh (Date of birth) | MRZ |
| Ngày hết hạn (Date of expiry) | MRZ |
| Ngày cấp (Date of issue) | OCR vùng visual (không có trong MRZ TD3 ICAO) |

## Lý do chọn thư viện

| Công cụ | Vai trò | Lý do |
|---------|---------|--------|
| **FastAPI** | API | Nhẹ, hỗ trợ async, lỗi/validation rõ ràng |
| **OpenCV** | Tiền xử lý ảnh | Deskew / tăng tương phản / khử nhiễu nhẹ cho ảnh nghiêng, tối, nhiễu |
| **PassportEye** | Đọc MRZ | Chuyên dụng định vị + parse MRZ, có điểm checksum |
| **Tesseract** (`pytesseract`) | Engine OCR cho PassportEye + Date of Issue | PassportEye cần Tesseract; đồng thời dùng OCR vùng visual |
| **PyMuPDF** | Hỗ trợ PDF | Convert trang đầu PDF sang ảnh, không cần Poppler trên Windows |
| **React + Vite** | UI cơ bản | Upload / loading / bảng kết quả tối giản |

> **Ghi chú về PaddleOCR:** `docs/system-design.md` ban đầu dự kiến dùng PaddleOCR cho OCR visual. Trên môi trường hiện tại chỉ có **Python 3.14** và **PaddlePaddle chưa có wheel tương thích**, nên OCR visual dùng **Tesseract** (cùng vai trò kiến trúc). Trên Python 3.10–3.12 có thể đổi `OCRService` sang PaddleOCR nếu muốn.

## Luồng xử lý

1. Client upload JPG / PNG / PDF.
2. Backend lưu file; nếu PDF thì rasterize trang đầu.
3. OpenCV cải thiện ánh sáng (CLAHE), chỉnh nghiêng nhẹ, denoise nhẹ.
4. PassportEye (và fallback Tesseract) đọc MRZ → họ, tên, ngày sinh, ngày hết hạn + điểm checksum.
5. Tesseract OCR vùng visual; tìm nhãn “Date of issue” (và biến thể) rồi parse ngày gần đó.
6. Validator kiểm tra checksum MRZ, định dạng ngày ISO, `birth < issue < expiry` (khi có ngày cấp).
7. Trả JSON gồm 5 trường kèm `validation.errors` / `warnings`.

## Yêu cầu môi trường

- Python 3.10+ (3.14 chạy được stack hiện tại; PaddleOCR cần ≤3.12)
- Node.js 18+
- **Tesseract OCR** đã cài và có trên `PATH`
  - Windows (khuyến nghị): [UB Mannheim Tesseract installer](https://github.com/UB-Mannheim/tesseract/wiki)
  - Hoặc: `winget install --id UB-Mannheim.TesseractOCR -e`

## Chạy backend

```bash
cd passport-ocr-backend
python -m venv venv
# Windows (khuyến nghị — dùng venv của project):
.\run.bat
# hoặc:
.\venv\Scripts\activate
pip install -r requirements.txt
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

> **Mẹo Windows:** Nên dùng `.\venv\Scripts\activate` rồi `uvicorn`, hoặc chạy `run.bat`.  
> Nếu dùng `py -m uvicorn` thì đang chạy **Python hệ thống** — cần `py -m pip install -r requirements.txt` đúng môi trường đó.  
> Tránh mở nhiều uvicorn cùng cổng `8000` (dễ gọi nhầm process cũ).

Health check: `GET http://localhost:8000/health`  
Swagger: `http://localhost:8000/docs`

## Chạy frontend

```bash
cd passport-ocr-frontend
npm install
npm run dev
```

Mở `http://localhost:5173`, chọn ảnh hộ chiếu, bấm **Extract**.

## API

`POST /api/v1/passport/extract` (`multipart/form-data`, field `file`)

Ví dụ body thành công:

```json
{
  "surname": "NGUYEN",
  "given_name": "VAN A",
  "date_of_birth": "1990-01-15",
  "date_of_issue": "2020-06-01",
  "date_of_expiry": "2030-06-01",
  "validation": {
    "mrz_checksum_valid": true,
    "dates_valid": true,
    "errors": [],
    "warnings": []
  },
  "raw_mrz": { }
}
```

Ví dụ lỗi rõ ràng:

- `400` sai định dạng file / ảnh không đọc được / convert PDF thất bại
- `422` `MRZ_NOT_FOUND` / `MRZ_PARSE_FAILED`

## Hạn chế hiện tại

- Ngày cấp phụ thuộc chất lượng in và ngôn ngữ nhãn; có thể trả `null` kèm warning.
- Deskew chỉ xử lý nghiêng nhẹ (±15°); góc lớn có thể làm mất MRZ.
- MRZ mờ / độ phân giải thấp thường fail checksum hoặc không detect — lỗi được trả rõ.
- Xử lý đồng bộ theo từng request (chưa có queue); môi trường này không dùng PaddleOCR / GPU.
- Chưa có authentication; file upload lưu tại `passport-ocr-backend/uploads/`.
- Passport specimen/test thường có checksum ICAO không chuẩn → `mrz_checksum_valid: false` kèm warning (vẫn có thể trả đủ field).

## Hướng mở rộng

- Crop ROI MRZ trước OCR để tăng độ chính xác
- Ensemble OCR (Tesseract + PaddleOCR) cho Date of Issue
- Hàng đợi async cho ảnh nặng
- Auth, rate limit, chính sách lưu/xóa upload
- Nhận diện nhãn ngày cấp đa ngôn ngữ tốt hơn
