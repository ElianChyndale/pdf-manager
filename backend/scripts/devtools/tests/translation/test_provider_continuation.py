import importlib.util
import sys
import tempfile
import types
from pathlib import Path


REPO_SCRIPTS_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_SCRIPTS_ROOT))


from services.document_schema.defaults import default_block_continuation_hint
from services.document_schema.adapters import adapt_payload_to_document_v1
from services.document_schema.providers import PROVIDER_GENERIC_FLAT_OCR
from services.translation.ocr.json_extractor import extract_text_items
from services.translation.ocr.models import TextItem
from services.translation.payload.translations import export_translation_template
from services.translation.payload.translations import load_translations
from services.translation.orchestration.document_orchestrator import _filter_boundary_candidate_pairs


def _ensure_package_stubs() -> None:
    package_paths = {
        "services": REPO_SCRIPTS_ROOT / "services",
        "services.translation": REPO_SCRIPTS_ROOT / "services" / "translation",
        "services.translation.continuation": REPO_SCRIPTS_ROOT / "services" / "translation" / "continuation",
    }
    for name, path in package_paths.items():
        module = sys.modules.get(name)
        if module is None:
            module = types.ModuleType(name)
            module.__path__ = [str(path)]
            sys.modules[name] = module


def _load_module(name: str, path: Path):
    _ensure_package_stubs()
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_state_module():
    _load_module(
        "services.translation.continuation.rules",
        REPO_SCRIPTS_ROOT / "services" / "translation" / "continuation" / "rules.py",
    )
    return _load_module(
        "services.translation.continuation.state",
        REPO_SCRIPTS_ROOT / "services" / "translation" / "continuation" / "state.py",
    )


def _payload_item(
    *,
    item_id: str,
    page_idx: int,
    text: str,
    bbox: list[float],
    ocr_source: str = "",
    ocr_group_id: str = "",
    ocr_scope: str = "",
    ocr_order: int = -1,
    layout_mode: str = "",
    layout_zone: str = "",
    layout_boundary_role: str = "",
    provider_body_repair_applied: bool = False,
) -> dict:
    return {
        "item_id": item_id,
        "page_idx": page_idx,
        "block_idx": 0,
        "block_type": "text",
        "block_kind": "text",
        "layout_role": "paragraph",
        "semantic_role": "body",
        "structure_role": "body",
        "policy_translate": True,
        "raw_block_type": "text",
        "normalized_sub_type": "",
        "bbox": bbox,
        "protected_source_text": text,
        "ocr_continuation_source": ocr_source,
        "ocr_continuation_group_id": ocr_group_id,
        "ocr_continuation_scope": ocr_scope,
        "ocr_continuation_reading_order": ocr_order,
        "layout_mode": layout_mode,
        "layout_zone": layout_zone,
        "layout_boundary_role": layout_boundary_role,
        "body_repair_applied": provider_body_repair_applied,
        "provider_body_repair_applied": provider_body_repair_applied,
    }


def test_boundary_review_skips_body_repair_items() -> None:
    payload = [
        _payload_item(
            item_id="a",
            page_idx=0,
            text="The present work attempts to explain,",
            bbox=[0, 0, 100, 20],
            layout_mode="double",
            layout_zone="left_column",
            layout_boundary_role="tail",
            provider_body_repair_applied=True,
        ),
        _payload_item(
            item_id="b",
            page_idx=0,
            text="perhaps vaguely but completely based on the obtained results.",
            bbox=[120, 0, 220, 20],
            layout_mode="double",
            layout_zone="right_column",
            layout_boundary_role="head",
            provider_body_repair_applied=True,
        ),
    ]
    pairs = [
        {
            "prev_item_id": "a",
            "next_item_id": "b",
            "prev_text": payload[0]["protected_source_text"],
            "next_text": payload[1]["protected_source_text"],
            "prev_page_idx": 0,
            "next_page_idx": 0,
            "prev_bbox": payload[0]["bbox"],
            "next_bbox": payload[1]["bbox"],
        }
    ]

    assert _filter_boundary_candidate_pairs(payload, pairs) == []


def test_provider_intra_page_join_takes_priority_and_rule_fallback_still_runs() -> None:
    state = _load_state_module()
    payload = [
        _payload_item(
            item_id="a",
            page_idx=0,
            text="left column sentence",
            bbox=[0, 0, 100, 20],
            ocr_source="provider",
            ocr_group_id="provider-paddle-page-001-group-12",
            ocr_scope="intra_page",
            ocr_order=0,
        ),
        _payload_item(
            item_id="b",
            page_idx=0,
            text="right column continuation",
            bbox=[120, 0, 220, 20],
            ocr_source="provider",
            ocr_group_id="provider-paddle-page-001-group-12",
            ocr_scope="intra_page",
            ocr_order=1,
        ),
        _payload_item(
            item_id="c",
            page_idx=0,
            text="This sentence continues with",
            bbox=[0, 40, 180, 60],
        ),
        _payload_item(
            item_id="d",
            page_idx=1,
            text="and additional evidence from the experiment.",
            bbox=[0, 0, 180, 20],
        ),
    ]

    annotated = state.annotate_continuation_context(payload)
    summary = state.summarize_continuation_decisions(payload)

    assert annotated == 4
    assert payload[0]["continuation_decision"] == "provider_joined"
    assert payload[1]["continuation_decision"] == "provider_joined"
    assert payload[0]["continuation_group"] == "provider-paddle-page-001-group-12"
    assert payload[2]["continuation_decision"] == "joined"
    assert payload[3]["continuation_decision"] == "joined"
    assert summary["joined_items"] == 4
    assert summary["provider_joined_items"] == 2
    assert summary["rule_joined_items"] == 2


def test_provider_cross_page_boundary_pair_is_consumed() -> None:
    state = _load_state_module()
    payload = [
        _payload_item(
            item_id="a",
            page_idx=0,
            text="This sentence continues with",
            bbox=[0, 0, 180, 20],
            ocr_source="provider",
            ocr_group_id="provider-paddle-global-abc",
            ocr_scope="cross_page",
            ocr_order=0,
            layout_mode="single",
            layout_zone="single_column",
            layout_boundary_role="tail",
        ),
        _payload_item(
            item_id="b",
            page_idx=1,
            text="and additional evidence from the experiment.",
            bbox=[0, 0, 180, 20],
            ocr_source="provider",
            ocr_group_id="provider-paddle-global-abc",
            ocr_scope="cross_page",
            ocr_order=1,
            layout_mode="single",
            layout_zone="single_column",
            layout_boundary_role="head",
        ),
    ]

    state.annotate_continuation_context(payload)

    assert payload[0]["continuation_decision"] == "provider_joined"
    assert payload[0]["continuation_group"] == "provider-paddle-global-abc"


def test_chunk_source_text_fallback_keeps_inline_math_atomic() -> None:
    from services.translation.llm.shared.orchestration.common import chunk_source_text_fallback

    text = "h mode i of the excitation spectrum can be characterized by its dispersion relation $\\omega_i(Q)$ and lifetime $\\tau$."
    chunks = chunk_source_text_fallback(text, words_per_chunk=5)

    assert any("$\\omega_i(Q)$" in chunk for chunk in chunks)
    assert not any(chunk.endswith("$\\omega_i(Q)") or chunk.startswith("\\omega_i(Q)$") for chunk in chunks)


def test_group_translation_split_keeps_inline_math_atomic() -> None:
    from services.translation.payload.parts.apply import _split_group_protected_translation

    items = [
        {"protected_source_text": "prev part"},
        {"protected_source_text": "next part"},
    ]
    translated = "激发谱的每个模式 i 可由其色散关系 $\\omega^i(\\mathbf{Q})$、寿命 $\\tau_{\\mathrm{SW}}^i$ 和强度 I_0 表征。"
    chunks = _split_group_protected_translation(translated, items)

    assert len(chunks) == 2
    assert sum("$\\omega^i(\\mathbf{Q})$" in chunk for chunk in chunks) == 1
    assert all(chunk.count("$") % 2 == 0 for chunk in chunks if chunk)


def test_unbalanced_inline_math_blocks_do_not_join_across_pages() -> None:
    state = _load_state_module()
    payload = [
        _payload_item(
            item_id="a",
            page_idx=0,
            text="The objective function is $a",
            bbox=[0, 0, 180, 20],
            ocr_source="provider",
            ocr_group_id="provider-paddle-global-math",
            ocr_scope="cross_page",
            ocr_order=0,
            layout_mode="single",
            layout_zone="single_column",
            layout_boundary_role="tail",
        ),
        _payload_item(
            item_id="b",
            page_idx=1,
            text="+b $ and additional evidence from the experiment.",
            bbox=[0, 0, 180, 20],
            ocr_source="provider",
            ocr_group_id="provider-paddle-global-math",
            ocr_scope="cross_page",
            ocr_order=1,
            layout_mode="single",
            layout_zone="single_column",
            layout_boundary_role="head",
        ),
    ]

    state.annotate_continuation_context(payload)

    assert payload[0]["continuation_decision"] == ""
    assert payload[1]["continuation_decision"] == ""
    assert payload[0]["continuation_group"] == ""
    assert payload[1]["continuation_group"] == ""


def test_provider_cross_page_hint_without_boundary_roles_falls_back_to_rules() -> None:
    state = _load_state_module()
    payload = [
        _payload_item(
            item_id="a",
            page_idx=0,
            text="This sentence continues with",
            bbox=[0, 0, 180, 20],
            ocr_source="provider",
            ocr_group_id="provider-paddle-global-abc",
            ocr_scope="cross_page",
            ocr_order=0,
        ),
        _payload_item(
            item_id="b",
            page_idx=1,
            text="and additional evidence from the experiment.",
            bbox=[0, 0, 180, 20],
            ocr_source="provider",
            ocr_group_id="provider-paddle-global-abc",
            ocr_scope="cross_page",
            ocr_order=1,
        ),
    ]

    state.annotate_continuation_context(payload)

    assert payload[0]["continuation_decision"] == "joined"
    assert payload[1]["continuation_decision"] == "joined"
    assert payload[0]["continuation_group"] != "provider-paddle-global-abc"


def test_provider_cross_page_hint_skipping_pages_is_not_consumed() -> None:
    state = _load_state_module()
    payload = [
        _payload_item(
            item_id="a",
            page_idx=0,
            text="This sentence continues with",
            bbox=[0, 0, 180, 20],
            ocr_source="provider",
            ocr_group_id="provider-paddle-global-abc",
            ocr_scope="cross_page",
            ocr_order=0,
            layout_boundary_role="tail",
        ),
        _payload_item(
            item_id="b",
            page_idx=2,
            text="and additional evidence from the experiment.",
            bbox=[0, 0, 180, 20],
            ocr_source="provider",
            ocr_group_id="provider-paddle-global-abc",
            ocr_scope="cross_page",
            ocr_order=1,
            layout_boundary_role="head",
        ),
    ]

    state.annotate_continuation_context(payload)

    assert payload[0]["continuation_decision"] == ""
    assert payload[1]["continuation_decision"] == ""
    assert payload[0]["continuation_group"] == ""


def test_provider_cross_page_double_column_left_tail_is_not_consumed() -> None:
    state = _load_state_module()
    payload = [
        _payload_item(
            item_id="a",
            page_idx=0,
            text="This sentence continues with",
            bbox=[0, 0, 100, 20],
            ocr_source="provider",
            ocr_group_id="provider-paddle-global-abc",
            ocr_scope="cross_page",
            ocr_order=0,
            layout_mode="double",
            layout_zone="left_column",
            layout_boundary_role="tail",
        ),
        _payload_item(
            item_id="b",
            page_idx=1,
            text="and additional evidence from the experiment.",
            bbox=[0, 0, 100, 20],
            ocr_source="provider",
            ocr_group_id="provider-paddle-global-abc",
            ocr_scope="cross_page",
            ocr_order=1,
            layout_mode="double",
            layout_zone="left_column",
            layout_boundary_role="head",
        ),
    ]

    state.annotate_continuation_context(payload)

    assert payload[0]["continuation_decision"] != "provider_joined"
    assert payload[0]["continuation_group"] != "provider-paddle-global-abc"


def test_provider_cross_page_short_fragments_are_not_consumed() -> None:
    state = _load_state_module()
    payload = [
        _payload_item(
            item_id="a",
            page_idx=0,
            text="A",
            bbox=[0, 0, 180, 20],
            ocr_source="provider",
            ocr_group_id="provider-paddle-global-abc",
            ocr_scope="cross_page",
            ocr_order=0,
            layout_mode="single",
            layout_zone="single_column",
            layout_boundary_role="tail",
        ),
        _payload_item(
            item_id="b",
            page_idx=1,
            text="B",
            bbox=[0, 0, 180, 20],
            ocr_source="provider",
            ocr_group_id="provider-paddle-global-abc",
            ocr_scope="cross_page",
            ocr_order=1,
            layout_mode="single",
            layout_zone="single_column",
            layout_boundary_role="head",
        ),
    ]

    state.annotate_continuation_context(payload)

    assert payload[0]["continuation_decision"] != "provider_joined"
    assert payload[0]["continuation_group"] != "provider-paddle-global-abc"


def test_vision_footnote_is_not_eligible_for_provider_or_rule_continuation() -> None:
    state = _load_state_module()
    payload = [
        _payload_item(
            item_id="body",
            page_idx=0,
            text="This body sentence continues with",
            bbox=[0, 0, 180, 20],
        ),
        _payload_item(
            item_id="footnote-a",
            page_idx=0,
            text="footnote note continues with",
            bbox=[0, 30, 180, 45],
            ocr_source="provider",
            ocr_group_id="provider-paddle-footnote",
            ocr_scope="intra_page",
            ocr_order=0,
        ),
        _payload_item(
            item_id="footnote-b",
            page_idx=0,
            text="and details in the lower note.",
            bbox=[190, 30, 360, 45],
            ocr_source="provider",
            ocr_group_id="provider-paddle-footnote",
            ocr_scope="intra_page",
            ocr_order=1,
        ),
        _payload_item(
            item_id="body-next",
            page_idx=1,
            text="and additional evidence from the experiment.",
            bbox=[0, 0, 180, 20],
        ),
    ]
    for item in payload[1:3]:
        item.update(
            {
                "layout_role": "footnote",
                "semantic_role": "metadata",
                "structure_role": "footnote",
                "raw_block_type": "vision_footnote",
                "normalized_sub_type": "table_footnote",
            }
        )

    state.annotate_continuation_context(payload)

    assert payload[0]["continuation_decision"] == "joined"
    assert payload[3]["continuation_decision"] == "joined"
    assert payload[1]["continuation_decision"] == ""
    assert payload[2]["continuation_decision"] == ""
    assert payload[1]["continuation_group"] == ""
    assert payload[2]["continuation_group"] == ""
    assert payload[0]["continuation_candidate_next_id"] != "footnote-a"
    assert payload[2]["continuation_candidate_next_id"] != "body-next"


def test_generic_provider_continuation_hint_flows_through_extractor_and_template() -> None:
    state = _load_state_module()
    adapted = adapt_payload_to_document_v1(
        payload={
            "provider": PROVIDER_GENERIC_FLAT_OCR,
            "pages": [
                {
                    "width": 240.0,
                    "height": 200.0,
                    "unit": "pt",
                    "blocks": [
                        {
                            "type": "text",
                            "sub_type": "body",
                            "bbox": [0, 0, 100, 20],
                            "text": "left column sentence",
                            "lines": [
                                {
                                    "bbox": [0, 0, 100, 20],
                                    "spans": [
                                        {
                                            "type": "text",
                                            "raw_type": "text",
                                            "text": "left column sentence",
                                            "bbox": [0, 0, 100, 20],
                                        }
                                    ],
                                }
                            ],
                            "segments": [],
                            "tags": [],
                            "derived": {"role": "", "by": "", "confidence": 0.0},
                            "continuation_hint": {
                                "source": "provider",
                                "group_id": "provider-generic-group-1",
                                "role": "head",
                                "scope": "intra_page",
                                "reading_order": 0,
                                "confidence": 0.91,
                            },
                            "metadata": {},
                        },
                        {
                            "type": "text",
                            "sub_type": "body",
                            "bbox": [120, 0, 220, 20],
                            "text": "right column continuation",
                            "lines": [
                                {
                                    "bbox": [120, 0, 220, 20],
                                    "spans": [
                                        {
                                            "type": "text",
                                            "raw_type": "text",
                                            "text": "right column continuation",
                                            "bbox": [120, 0, 220, 20],
                                        }
                                    ],
                                }
                            ],
                            "segments": [],
                            "tags": [],
                            "derived": {"role": "", "by": "", "confidence": 0.0},
                            "continuation_hint": {
                                "source": "provider",
                                "group_id": "provider-generic-group-1",
                                "role": "tail",
                                "scope": "intra_page",
                                "reading_order": 1,
                                "confidence": 0.91,
                            },
                            "metadata": {},
                        },
                    ],
                }
            ],
        },
        provider=PROVIDER_GENERIC_FLAT_OCR,
        document_id="generic-continuation-doc",
        source_json_path=Path("/tmp/generic-continuation.json"),
    )

    blocks = adapted["pages"][0]["blocks"]
    assert blocks[0]["continuation_hint"]["group_id"] == "provider-generic-group-1"
    assert blocks[1]["continuation_hint"]["role"] == "tail"

    items = extract_text_items(adapted, 0)
    assert len(items) == 2
    assert items[0].metadata["continuation_hint"]["source"] == "provider"

    with tempfile.TemporaryDirectory() as tmp:
        translation_path = Path(tmp) / "page-001.json"
        export_translation_template(items, translation_path, page_idx=0)
        payload = load_translations(translation_path)

    assert payload[0]["ocr_continuation_group_id"] == "provider-generic-group-1"
    assert payload[1]["ocr_continuation_role"] == "tail"

    annotated = state.annotate_continuation_context(payload)

    assert annotated == 2
    assert payload[0]["continuation_decision"] == "provider_joined"
    assert payload[1]["continuation_decision"] == "provider_joined"
    assert payload[0]["continuation_group"] == "provider-generic-group-1"


def test_provider_layout_warning_fields_flow_through_template() -> None:
    item = TextItem(
        item_id="p001-b0001",
        page_idx=0,
        block_idx=0,
        block_type="text",
        bbox=[0, 0, 100, 20],
        text="merged text block",
        segments=[],
        lines=[],
        metadata={
            "continuation_hint": default_block_continuation_hint(),
            "provider_cross_column_merge_suspected": True,
            "provider_reading_order_unreliable": True,
            "provider_structure_unreliable": True,
            "provider_text_missing_but_bbox_present": False,
            "provider_peer_block_absorbed_text": True,
            "provider_suspected_peer_block_id": "p001-b0002",
            "provider_continuation_suppressed": True,
            "provider_continuation_suppressed_reason": "cross_column_merge_suspected",
            "provider_column_layout_mode": "double",
            "provider_column_index_guess": "left",
        },
    )
    with tempfile.TemporaryDirectory() as tmp:
        translation_path = Path(tmp) / "page-001.json"
        export_translation_template([item], translation_path, page_idx=0)
        payload = load_translations(translation_path)

    assert payload[0]["provider_cross_column_merge_suspected"] is True
    assert payload[0]["provider_reading_order_unreliable"] is True
    assert payload[0]["provider_structure_unreliable"] is True
    assert payload[0]["provider_text_missing_but_bbox_present"] is False
    assert payload[0]["provider_peer_block_absorbed_text"] is True
    assert payload[0]["provider_suspected_peer_block_id"] == "p001-b0002"
    assert payload[0]["provider_continuation_suppressed"] is True
    assert payload[0]["provider_continuation_suppressed_reason"] == "cross_column_merge_suspected"
    assert payload[0]["provider_column_layout_mode"] == "double"
    assert payload[0]["provider_column_index_guess"] == "left"
