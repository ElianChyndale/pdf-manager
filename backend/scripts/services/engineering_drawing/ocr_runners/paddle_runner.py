from __future__ import annotations

import argparse
import json
from pathlib import Path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--det-model", default="PP-OCRv5_server_det")
    parser.add_argument("--rec-model", default="PP-OCRv5_server_rec")
    return parser


def _plain(value):
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def main() -> int:
    args = _parser().parse_args()
    from paddleocr import PaddleOCR

    pipeline = PaddleOCR(
        text_detection_model_name=args.det_model,
        text_recognition_model_name=args.rec_model,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=True,
        device=args.device,
    )
    if args.manifest:
        inputs = json.loads(args.manifest.read_text(encoding="utf-8")).get("items", [])
    elif args.input:
        inputs = [{"id": "full", "image_path": str(args.input)}]
    else:
        raise RuntimeError("provide --input or --manifest")
    pages = []
    for source in inputs:
        for prediction in pipeline.predict(str(source["image_path"])):
            payload = _plain(prediction.json)
            result = payload.get("res", payload)
            texts = list(result.get("rec_texts") or [])
            scores = list(result.get("rec_scores") or [])
            boxes = list(result.get("rec_boxes") or [])
            polygons = list(result.get("rec_polys") or [])
            angles = list(result.get("textline_orientation_angles") or [])
            items = []
            for index, text in enumerate(texts):
                if not str(text or "").strip():
                    continue
                box = boxes[index] if index < len(boxes) else []
                polygon = polygons[index] if index < len(polygons) else []
                items.append(
                    {
                        "text": str(text).strip(),
                        "confidence": float(scores[index]) if index < len(scores) else 0.0,
                        "bbox": box,
                        "polygon": polygon,
                        "orientation": int(angles[index]) if index < len(angles) else -1,
                    }
                )
            pages.append(
                {
                    "id": str(source.get("id", "")),
                    "meta": source.get("meta", {}),
                    "items": items,
                    "raw_item_count": len(texts),
                }
            )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "engine": "paddleocr",
                "det_model": args.det_model,
                "rec_model": args.rec_model,
                "pages": pages,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
