                React
                  │
          Upload JPG/PNG/PDF
                  │
                  ▼
         FastAPI (Python)
                  │
      ┌───────────┼────────────┐
      │           │            │
      ▼           ▼            ▼
 Image        MRZ Reader    Visual OCR
Processor   (PassportEye) (PaddleOCR)
      │           │            │
      └───────────┴────────────┘
                  │
                  ▼
            Data Validator
                  │
                  ▼
             JSON Response