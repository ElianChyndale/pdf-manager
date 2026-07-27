from pathlib import Path
import json

import fitz

from services.engineering_drawing import sample_builder
from services.engineering_drawing.sample_builder import SampleSpec
from services.engineering_drawing.sample_builder import _merge_ocr_resolutions
from services.engineering_drawing.sample_builder import _merge_vector_outline_phrase
from services.engineering_drawing.sample_builder import _offline_translation
from services.engineering_drawing.sample_builder import _sample_regions
from services.engineering_drawing.translation_qa import EngineeringTranslationResult


def test_offline_sample_glossary_preserves_numeric_annotation() -> None:
    assert _offline_translation("GARISAN ANJAKAN BANGUNAN 40'") == "建筑退界线 40'"
    assert _offline_translation("CADANGAN LALUAN SEHALA (6100MM LEBAR)") == "建议单向通道 6100MM"


def test_offline_sample_glossary_handles_fixed_vector_regression() -> None:
    assert _offline_translation("DEPOH LORI") == "卡车车库"


def test_sample_builder_rejects_incomplete_legacy_translation() -> None:
    file_audit = {
        "relative_path": "A3 DETAIL DRAWING/24_REV. JULAI 2025 SIGNAGE.pdf",
        "pages": [
            {
                "page_number": 1,
                "regions": [
                    {
                        "region_id": "p1-r1",
                        "source_text": "CADANGAN LALUAN SEHALA (6100MM LEBAR)",
                        "translated_text": "宽",
                        "bbox": [20, 20, 140, 30],
                        "rotation": 0,
                        "action": "translate",
                        "legacy_status": "layout_defect",
                        "qa_flags": [],
                    }
                ],
            }
        ],
    }

    regions, unresolved = _sample_regions(file_audit, 1)

    assert regions[0]["translated_text"] == "建议单向通道 6100MM"
    assert "legacy_translation_rejected" in regions[0]["qa_flags"]
    assert not unresolved


def test_build_samples_uses_hybrid_ocr_instead_of_legacy_audit_regions(tmp_path: Path, monkeypatch) -> None:
    source_path = tmp_path / "source.pdf"
    document = fitz.open()
    page = document.new_page(width=300, height=200)
    page.insert_text((20, 40), "Old legacy text", fontsize=10)
    document.save(source_path)
    document.close()
    audit_path = tmp_path / "legacy-audit.json"
    audit_path.write_text(
        json.dumps(
            {
                "files": [
                    {
                        "source_path": str(source_path),
                        "relative_path": "source.pdf",
                        "regression_checks": [],
                        "pages": [
                            {
                                "page_number": 1,
                                "regions": [
                                    {
                                        "region_id": "legacy-only",
                                        "source_text": "Old legacy text",
                                        "translated_text": "旧稿错配",
                                        "bbox": [20, 20, 90, 30],
                                        "rotation": 0,
                                        "action": "translate",
                                        "qa_flags": [],
                                    }
                                ],
                            }
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    calls = []

    def fake_ocr(*, output_path: Path, **kwargs):
        calls.append(kwargs)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(
                {
                    "regions": [
                        {
                            "region_id": "fresh-ocr",
                            "source_text": "Distribution Water Pump",
                            "source_language": "en",
                            "bbox": [20, 28, 150, 44],
                            "rotation": 0,
                            "provenance": "paddle_ocr",
                            "action": "translate",
                            "qa_flags": [],
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return type("Result", (), {"cache_hit": False})()

    def fake_translate(regions, **_kwargs):
        translated = [dict(region, translated_text="配水泵", coverage_status="translated", ai_judgement="accepted") for region in regions]
        return EngineeringTranslationResult(
            regions=translated,
            report={"target_regions": 1, "unresolved_regions": 0, "passed": True, "translation_api_calls": 1, "qa_api_calls": 1},
        )

    monkeypatch.setattr(sample_builder, "run_hybrid_ocr", fake_ocr)
    monkeypatch.setattr(sample_builder, "translate_and_judge_engineering_regions", fake_translate)

    result = sample_builder.build_samples(
        audit_json_path=audit_path,
        output_root=tmp_path / "output",
        work_dir=tmp_path / "work",
        samples=(SampleSpec("source.pdf", "fresh"),),
        api_key="test-key",
        enable_deepseek_ocr=False,
    )

    assert calls
    sample = result["samples"][0]
    assert Path(sample["bilingual_pdf"]).exists()
    coverage = json.loads(Path(sample["coverage_json"]).read_text(encoding="utf-8"))
    assert coverage["regions"][0]["source_text"] == "Distribution Water Pump"
    assert coverage["regions"][0]["source_text"] != "Old legacy text"


def test_multiresolution_fallback_restores_vector_outline_phrase_missing_at_primary_scale() -> None:
    primary = [
        {
            "region_id": "high-water",
            "source_text": "Treated Water Tank",
            "bbox": [20, 20, 140, 35],
            "qa_flags": [],
        }
    ]
    fallback = [
        {
            "region_id": "low-depoh",
            "source_text": "DEPOH",
            "bbox": [160, 100, 240, 120],
            "provenance": "vector_outline",
            "qa_flags": [],
        },
        {
            "region_id": "low-lori",
            "source_text": "LORI",
            "bbox": [170, 125, 230, 145],
            "provenance": "vector_outline",
            "qa_flags": [],
        },
        {
            "region_id": "low-area",
            "source_text": "2.020 ek.",
            "bbox": [155, 150, 240, 165],
            "provenance": "paddle_ocr",
            "qa_flags": [],
        },
    ]

    merged = _merge_vector_outline_phrase(_merge_ocr_resolutions(primary, fallback))

    compound = next(item for item in merged if item["region_id"] == "p001-vector-depoh-lori")
    assert compound["source_text"] == "DEPOH LORI 2.020 ek."
    assert set(compound["covered_region_ids"]) == {
        "low-depoh-lowdpi",
        "low-lori-lowdpi",
        "low-area-lowdpi",
    }
