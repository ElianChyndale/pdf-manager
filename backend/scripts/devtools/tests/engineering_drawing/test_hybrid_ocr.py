import fitz

from services.engineering_drawing.hybrid_ocr import _merge_native_and_visual
from services.engineering_drawing.hybrid_ocr import _paddle_regions


def test_paddle_result_maps_pixel_bbox_back_to_pdf_points() -> None:
    doc = fitz.open()
    page = doc.new_page(width=200, height=100)
    payload = {
        "pages": [
            {
                "items": [
                    {
                        "text": "DEPOH LORI",
                        "confidence": 0.91,
                        "bbox": [100, 40, 300, 80],
                        "orientation": 0,
                    }
                ]
            }
        ]
    }

    regions = _paddle_regions(
        payload,
        page=page,
        page_number=1,
        image_width=400,
        image_height=200,
        min_confidence=0.25,
    )

    assert regions[0]["bbox"] == [50.0, 20.0, 150.0, 40.0]
    assert regions[0]["provenance"] == "vector_outline"
    assert regions[0]["action"] == "translate"
    doc.close()


def test_visual_region_is_not_dropped_when_native_text_does_not_match() -> None:
    native = [
        {
            "source_text": "1310-CN-ELEC-A001",
            "bbox": [10, 10, 100, 30],
            "provenance": "native_text",
        }
    ]
    visual = [
        {
            "source_text": "DEPOH LORI",
            "bbox": [10, 10, 100, 30],
            "provenance": "vector_outline",
        }
    ]

    assert len(_merge_native_and_visual(native, visual)) == 2
