import fitz
from PIL import Image

from services.engineering_drawing.hybrid_ocr import _crop_review_regions
from services.engineering_drawing.hybrid_ocr import _merge_native_and_visual
from services.engineering_drawing.hybrid_ocr import _needs_deepseek
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


def test_paddle_polygon_preserves_vertical_text_direction() -> None:
    doc = fitz.open()
    page = doc.new_page(width=200, height=100)
    regions = _paddle_regions(
        {"items": [{"text": "BOUNDARY LINE", "confidence": 0.91, "polygon": [[20, 20], [20, 80], [32, 80], [32, 20]]}]},
        page=page,
        page_number=1,
        image_width=200,
        image_height=100,
        min_confidence=0.25,
    )

    assert regions[0]["rotation"] == 90
    assert regions[0]["baseline_angle"] == 90
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


def test_unlimited_deepseek_review_profile_does_not_silently_cap_candidates(tmp_path) -> None:
    image_path = tmp_path / "page.png"
    Image.new("RGB", (1000, 1000), "white").save(image_path)
    document = fitz.open()
    page = document.new_page(width=100, height=100)
    regions = [
        {
            "region_id": f"region-{index}",
            "source_text": f"Label {index}",
            "bbox": [5, 5 + index * 8, 60, 11 + index * 8],
            "provenance": "paddle_ocr",
            "ocr_confidence": 0.4,
            "rotation": 0,
        }
        for index in range(10)
    ]

    manifest, skipped = _crop_review_regions(
        image_path,
        regions,
        page=page,
        output_dir=tmp_path,
        limit=0,
        threshold=0.9,
    )

    assert len(manifest) == len(regions)
    assert skipped == []
    document.close()


def test_deepseek_review_ignores_non_latin_noise_but_keeps_vector_outline_regression() -> None:
    assert not _needs_deepseek(
        {
            "source_text": "金",
            "provenance": "paddle_ocr",
            "ocr_confidence": 0.08,
            "rotation": 0,
        },
        threshold=0.65,
    )
    assert _needs_deepseek(
        {
            "source_text": "DEPOH",
            "provenance": "vector_outline",
            "ocr_confidence": 0.99,
            "rotation": 0,
        },
        threshold=0.65,
    )
