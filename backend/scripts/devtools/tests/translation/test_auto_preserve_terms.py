from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_SCRIPTS_ROOT = Path("REPO_ROOT_PLACEHOLDER/backend/scripts")
sys.path.insert(0, str(REPO_SCRIPTS_ROOT))

from services.translation.terms import auto_preserve_glossary_entries_from_texts
from services.translation.workflow.execution import TranslationExecutionRequest
from services.translation.workflow.execution_plan import build_translation_execution_plan


def test_auto_preserve_terms_keeps_hyphenated_scientific_names() -> None:
    entries = auto_preserve_glossary_entries_from_texts(
        [
            "Hartree-Fock and Kohn-Sham density functional theory are compared with DFTB3.",
            "The SCF procedure uses GFN2-xTB parameters.",
        ]
    )
    by_source = {entry.source: entry for entry in entries}

    assert by_source["Hartree-Fock"].target == "Hartree-Fock"
    assert by_source["Hartree-Fock"].level == "preserve"
    assert by_source["Hartree-Fock"].match_mode == "case_insensitive"
    assert by_source["Kohn-Sham"].level == "preserve"
    assert by_source["GFN2-xTB"].level == "preserve"
    assert by_source["SCF"].level == "preserve"
    assert "The" not in by_source


def test_execution_plan_injects_auto_preserve_glossary(tmp_path: Path) -> None:
    source_json = tmp_path / "document.v1.json"
    source_json.write_text(
        json.dumps(
            {
                "schema": "normalized_document_v1",
                "schema_version": "1.1",
                "document_id": "auto-preserve-test",
                "source": {"provider": "test", "provider_version": "test", "raw_files": {}},
                "page_count": 1,
                "pages": [
                    {
                        "page_index": 0,
                        "width": 200.0,
                        "height": 120.0,
                        "unit": "pt",
                        "blocks": [
                            {
                                "block_id": "p001-b0000",
                                "page_index": 0,
                                "order": 0,
                                "type": "text",
                                "sub_type": "",
                                "geometry": {"bbox": [0, 0, 150, 20]},
                                "content": {
                                    "kind": "text",
                                    "text": "Hartree-Fock theory and SCF iterations are used.",
                                },
                                "bbox": [0, 0, 150, 20],
                                "text": "Hartree-Fock theory and SCF iterations are used.",
                                "lines": [],
                                "segments": [],
                                "layout_role": "paragraph",
                                "semantic_role": "body",
                                "structure_role": "body",
                                "policy": {"translate": True, "translate_reason": "test"},
                                "provenance": {
                                    "provider": "test",
                                    "raw_label": "text",
                                    "raw_sub_type": "",
                                    "raw_bbox": [0, 0, 150, 20],
                                    "raw_path": "$.pages[0].blocks[0]",
                                },
                                "continuation_hint": {
                                    "source": "",
                                    "group_id": "",
                                    "role": "",
                                    "scope": "",
                                    "reading_order": -1,
                                    "confidence": 0.0,
                                },
                                "metadata": {},
                                "source": {"provider": "test", "raw_type": "text"},
                            }
                        ],
                    }
                ],
                "derived": {},
                "markers": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    plan = build_translation_execution_plan(
        TranslationExecutionRequest(
            source_json_path=source_json,
            output_dir=tmp_path / "translated",
            api_key="sk-test",
            glossary_entries=[
                {
                    "source": "SCF",
                    "target": "自洽场",
                    "level": "preferred",
                    "match_mode": "exact",
                }
            ],
        )
    )
    sources = {entry.source: entry for entry in plan.glossary_entries}

    assert sources["Hartree-Fock"].target == "Hartree-Fock"
    assert sources["Hartree-Fock"].level == "preserve"
    assert sources["SCF"].target == "自洽场"
    assert sources["SCF"].level == "preferred"
    assert plan.translation_context.glossary_entries == plan.glossary_entries
