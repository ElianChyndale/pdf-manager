import json
import sys
from pathlib import Path

import fitz
import pytest
from PIL import Image

import services.engineering_drawing.hybrid_ocr as hybrid_ocr
from services.engineering_drawing.hybrid_ocr import _crop_review_regions
from services.engineering_drawing.hybrid_ocr import _merge_native_and_visual
from services.engineering_drawing.hybrid_ocr import _needs_deepseek
from services.engineering_drawing.hybrid_ocr import _paddle_regions
from services.engineering_drawing.hybrid_ocr import _supervisor_task_manifest
from services.engineering_drawing.hybrid_ocr import _supervisor_tasks_for_page


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


def test_supervisor_task_manifest_uses_only_declared_regions(tmp_path) -> None:
    image_path = tmp_path / "page.png"
    Image.new("RGB", (400, 200), "white").save(image_path)

    entries = _supervisor_task_manifest(
        image_path,
        tasks=[
            {"id": "left", "region_norm": [0.0, 0.0, 0.25, 1.0]},
            {"id": "right", "region": {"left": 200, "top": 50, "right": 400, "bottom": 150}},
        ],
        output_dir=tmp_path / "crops",
        image_width=400,
        image_height=200,
    )

    assert [entry["meta"]["supervisor_task_id"] for entry in entries] == ["left", "right"]
    assert Image.open(entries[0]["image_path"]).size == (100, 200)
    assert Image.open(entries[1]["image_path"]).size == (200, 100)
    assert all("tile-" not in entry["image_path"] for entry in entries)


def test_supervisor_task_manifest_rejects_invalid_or_inverted_region(tmp_path) -> None:
    image_path = tmp_path / "page.png"
    Image.new("RGB", (100, 100), "white").save(image_path)

    with pytest.raises(ValueError, match="bounded region"):
        _supervisor_task_manifest(
            image_path,
            tasks=[{"id": "bad", "region_norm": [0.8, 0.2, 0.4, 0.7]}],
            output_dir=tmp_path / "crops",
            image_width=100,
            image_height=100,
        )

    with pytest.raises(ValueError, match="bounded region"):
        _supervisor_task_manifest(
            image_path,
            tasks=[{"id": "outside", "region_norm": [0.0, 0.0, 1.1, 1.0]}],
            output_dir=tmp_path / "crops-2",
            image_width=100,
            image_height=100,
        )


def test_supervisor_tasks_require_page_binding_for_multi_page_execution() -> None:
    tasks = [{"id": "unscoped", "region_norm": [0.0, 0.0, 1.0, 1.0]}]
    assert _supervisor_tasks_for_page(
        tasks,
        page_number=1,
        requested_page_count=1,
    ) == tasks
    with pytest.raises(ValueError, match="page_index"):
        _supervisor_tasks_for_page(
            tasks,
            page_number=1,
            requested_page_count=2,
        )


def test_run_hybrid_ocr_executes_supervisor_crops_instead_of_generic_tiles(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.pdf"
    document = fitz.open()
    document.new_page(width=200, height=100)
    document.save(source)
    document.close()

    captured_manifests: list[list[dict]] = []

    def fake_run(command: list[str], *, timeout: int) -> None:
        manifest_path = Path(command[command.index("--manifest") + 1])
        output_path = Path(command[command.index("--output") + 1])
        captured_manifests.append(json.loads(manifest_path.read_text(encoding="utf-8"))["items"])
        output_path.write_text(json.dumps({"pages": [{"items": []}]}), encoding="utf-8")

    monkeypatch.setattr(hybrid_ocr, "_runtime_python", lambda _engine: Path(sys.executable))
    monkeypatch.setattr(hybrid_ocr, "_run", fake_run)
    output = tmp_path / "ocr.json"
    hybrid_ocr.run_hybrid_ocr(
        pdf_path=source,
        output_path=output,
        cache_dir=tmp_path / "cache",
        start_page=1,
        end_page=1,
        enable_deepseek=False,
        supervisor_plan={
            "ocr_tasks": [
                {"id": "left", "region_norm": [0.0, 0.0, 0.5, 1.0]},
                {"id": "right", "region_norm": [0.5, 0.0, 1.0, 1.0]},
            ]
        },
    )

    assert len(captured_manifests) == 1
    assert [item["meta"]["supervisor_task_id"] for item in captured_manifests[0]] == ["left", "right"]
    payload = json.loads(output.read_text(encoding="utf-8"))
    execution = payload["supervisor_execution"]
    assert execution["ocr_execution_mode"] == "supervisor_declared_task_crops"
    assert execution["unplanned_full_page_scan"] is False
    assert execution["executed_task_ids"] == ["left", "right"]


def test_run_hybrid_ocr_does_not_fallback_when_supervisor_tasks_are_empty(tmp_path) -> None:
    source = tmp_path / "source.pdf"
    document = fitz.open()
    document.new_page(width=100, height=100)
    document.save(source)
    document.close()

    with pytest.raises(ValueError, match="at least one OCR task"):
        hybrid_ocr.run_hybrid_ocr(
            pdf_path=source,
            output_path=tmp_path / "ocr.json",
            cache_dir=tmp_path / "cache",
            enable_deepseek=False,
            supervisor_plan={"ocr_tasks": []},
        )
