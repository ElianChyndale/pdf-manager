# Engineering drawing backend

This backend inventories source/legacy PDFs, audits missing translations, runs
hybrid OCR, and renders bilingual overlay and source/Chinese dual-page PDFs.

## OCR strategy

1. Read the native PDF text layer.
2. Render each page at 220 DPI.
3. Run `PP-OCRv5_server_det` + `PP-OCRv5_server_rec` on the full page and
   overlapping 2200 px tiles.
4. Deduplicate native and visual regions by geometry and normalized text.
5. Send only unique low-confidence, rotated, or fixed-regression crops to
   DeepSeek-OCR-2.
6. Keep a high-confidence Paddle result when DeepSeek disagrees; record the
   disagreement as `deepseek_ocr_conflict` for manual review.

DeepSeek-OCR-2 uses BF16 weights. On GPUs below 12 GiB the runner keeps the
vision encoder and first eight language layers on the GPU and offloads the
remaining layers to CPU. This preserves OCR quality on the local 8 GiB GPU
without quantizing the verification model.

## Local runtimes

The default paths are:

```text
.runtime/ocr/paddle/Scripts/python.exe
.runtime/ocr/deepseek/Scripts/python.exe
.runtime/ocr/models/deepseek-ocr-2/
```

Dependencies are pinned in `ocr_runners/requirements-paddle.txt` and
`ocr_runners/requirements-deepseek.txt`. DeepSeek-OCR-2 is loaded from the
local model directory when present, otherwise its Hugging Face model id is
used.

## Commands

Run inventory and legacy audit:

```powershell
$env:PYTHONPATH='backend/scripts'
python -m services.engineering_drawing.cli all `
  --root '<malasia-root>' `
  --output 'output/pdf/engineering-drawing' `
  --screenshots
```

Run one-page hybrid OCR:

```powershell
python -m services.engineering_drawing.cli ocr `
  --pdf '<source.pdf>' `
  --output 'output/pdf/engineering-drawing/04_QA_Reports/source-ocr.json' `
  --cache-dir 'output/pdf/engineering-drawing/04_QA_Reports/ocr-cache' `
  --start-page 1 --end-page 1
```

Build the three sample deliverables:

```powershell
python -m services.engineering_drawing.cli samples `
  --audit-json 'output/pdf/engineering-drawing/legacy-audit.json' `
  --output-root 'output/pdf/engineering-drawing' `
  --work-dir 'tmp/pdfs/engineering-samples'
```
