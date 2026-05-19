import sys
import tempfile
from pathlib import Path


REPO_SCRIPTS_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_SCRIPTS_ROOT))


from services.translation.workflow.page_policies import finalize_page_payloads
from services.translation.policy.flow import apply_translation_policies
from services.translation.policy.config import build_translation_policy_config
from services.translation.payload.parts.legacy_policy_mutations import apply_mixed_literal_split_policy
from services.translation.payload.parts.legacy_policy_mutations import apply_cjk_source_keep_origin
from services.translation.payload.parts.policy_mutations import apply_title_skip
from services.translation.context import TranslationDocumentContext
from services.translation.policy.planner import TranslationPlanner


def _page_payload_item(
    *,
    item_id: str,
    page_idx: int,
    text: str,
    bbox: list[float],
    group_id: str,
    order: int,
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
        "source_text": text,
        "protected_source_text": text,
        "formula_map": [],
        "classification_label": "",
        "should_translate": True,
        "ocr_continuation_source": "provider",
        "ocr_continuation_group_id": group_id,
        "ocr_continuation_role": "head" if order == 0 else "tail",
        "ocr_continuation_scope": "cross_page",
        "ocr_continuation_reading_order": order,
        "layout_mode": "",
        "layout_split_x": 0.0,
        "layout_zone": "",
        "layout_zone_rank": -1,
        "layout_zone_size": 0,
        "layout_boundary_role": "",
        "continuation_group": "",
        "continuation_prev_text": "",
        "continuation_next_text": "",
        "continuation_decision": "",
        "continuation_candidate_prev_id": "",
        "continuation_candidate_next_id": "",
        "translation_unit_id": item_id,
        "translation_unit_kind": "single",
        "translation_unit_member_ids": [item_id],
        "translation_unit_protected_source_text": text,
        "translation_unit_formula_map": [],
    }


def test_finalize_page_payloads_annotates_layout_before_cross_page_provider_join() -> None:
    group_id = "provider-generic-global-1"
    page_payloads = {
        0: [
            _page_payload_item(
                item_id="p001-b000",
                page_idx=0,
                text="This sentence continues with enough context",
                bbox=[0, 0, 180, 20],
                group_id=group_id,
                order=0,
            )
        ],
        1: [
            _page_payload_item(
                item_id="p002-b000",
                page_idx=1,
                text="and additional evidence from the next page.",
                bbox=[0, 0, 180, 20],
                group_id=group_id,
                order=1,
            )
        ],
    }

    with tempfile.TemporaryDirectory() as tmp:
        translation_paths = {
            0: Path(tmp) / "page-001.json",
            1: Path(tmp) / "page-002.json",
        }
        summary = finalize_page_payloads(
            page_payloads=page_payloads,
            translation_paths=translation_paths,
        )

    assert summary["provider_joined_items"] == 2
    assert page_payloads[0][0]["layout_zone"] == "single_column"
    assert page_payloads[1][0]["layout_zone"] == "single_column"
    assert page_payloads[0][0]["continuation_decision"] == "provider_joined"
    assert page_payloads[1][0]["continuation_decision"] == "provider_joined"
    assert page_payloads[0][0]["continuation_group"] == group_id


def test_translation_planner_reuses_page_context_for_no_trans_classification(monkeypatch) -> None:
    captured = {}

    def _fake_request(messages, **kwargs):
        captured["messages"] = messages
        return "no-trans: 1"

    monkeypatch.setattr(
        "services.translation.classification.page_classifier.request_chat_content",
        _fake_request,
    )
    payload = [
        {
            "item_id": "p008-b003",
            "block_type": "text",
            "block_kind": "text",
            "layout_role": "paragraph",
            "semantic_role": "body",
            "structure_role": "body",
            "bbox": [10, 20, 300, 80],
            "source_text": "$ source deeph/bin/activate",
            "protected_source_text": "$ source deeph/bin/activate",
            "formula_map": [],
            "lines": [{"spans": [{"content": "$ source deeph/bin/activate"}]}],
            "metadata": {"structure_role": "body"},
        }
    ]

    labels = TranslationPlanner(
        TranslationDocumentContext(mode="sci", rule_guidance="technical manual")
    ).classify_no_trans(
        payload,
        api_key="",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        batch_size=8,
        request_label="classification page 8",
    )

    assert labels == {"p008-b003": "code"}
    assert "technical manual" in captured["messages"][0]["content"]
    assert "$ source deeph/bin/activate" in captured["messages"][1]["content"]


def test_finalize_page_payloads_does_not_join_figure_caption_with_body_text() -> None:
    page_payloads = {
        2: [
            {
                "item_id": "p003-b008",
                "page_idx": 2,
                "block_idx": 8,
                "block_type": "text",
                "block_kind": "text",
                "layout_role": "paragraph",
                "semantic_role": "body",
                "structure_role": "body",
                "policy_translate": True,
                "raw_block_type": "text",
                "normalized_sub_type": "",
                "bbox": [60, 240, 270, 360],
                "source_text": "This is a body paragraph that ends with the",
                "protected_source_text": "This is a body paragraph that ends with the",
                "formula_map": [],
                "classification_label": "",
                "should_translate": True,
                "layout_mode": "double",
                "layout_split_x": 300.0,
                "layout_zone": "",
                "layout_zone_rank": -1,
                "layout_zone_size": 0,
                "layout_boundary_role": "",
                "continuation_group": "",
                "continuation_prev_text": "",
                "continuation_next_text": "",
                "continuation_decision": "",
                "continuation_candidate_prev_id": "",
                "continuation_candidate_next_id": "",
                "translation_unit_id": "p003-b008",
                "translation_unit_kind": "single",
                "translation_unit_member_ids": ["p003-b008"],
                "translation_unit_protected_source_text": "This is a body paragraph that ends with the",
                "translation_unit_formula_map": [],
            },
            {
                "item_id": "p003-b010",
                "page_idx": 2,
                "block_idx": 10,
                "block_type": "text",
                "block_kind": "text",
                "layout_role": "caption",
                "semantic_role": "caption",
                "structure_role": "figure_caption",
                "policy_translate": True,
                "raw_block_type": "figure_title",
                "normalized_sub_type": "figure_caption",
                "bbox": [330, 240, 550, 300],
                "source_text": "FIG. 3. Final electronic structure spectrum.",
                "protected_source_text": "FIG. 3. Final electronic structure spectrum.",
                "formula_map": [],
                "classification_label": "",
                "should_translate": True,
                "layout_mode": "double",
                "layout_split_x": 300.0,
                "layout_zone": "",
                "layout_zone_rank": -1,
                "layout_zone_size": 0,
                "layout_boundary_role": "",
                "continuation_group": "",
                "continuation_prev_text": "",
                "continuation_next_text": "",
                "continuation_decision": "",
                "continuation_candidate_prev_id": "",
                "continuation_candidate_next_id": "",
                "translation_unit_id": "p003-b010",
                "translation_unit_kind": "single",
                "translation_unit_member_ids": ["p003-b010"],
                "translation_unit_protected_source_text": "FIG. 3. Final electronic structure spectrum.",
                "translation_unit_formula_map": [],
            },
        ],
    }

    with tempfile.TemporaryDirectory() as tmp:
        translation_paths = {2: Path(tmp) / "page-003.json"}
        summary = finalize_page_payloads(
            page_payloads=page_payloads,
            translation_paths=translation_paths,
        )

    body, caption = page_payloads[2]
    assert summary["joined_items"] == 0
    assert body["continuation_group"] == ""
    assert body["continuation_candidate_next_id"] == ""
    assert caption["continuation_group"] == ""
    assert caption["continuation_candidate_prev_id"] == ""
    assert caption["translation_unit_id"] == "p003-b010"


def test_apply_translation_policies_does_not_call_no_trans_classifier_by_default(monkeypatch) -> None:
    def _fail_if_called(*args, **kwargs):
        raise AssertionError("no-trans classifier should be opt-in")

    monkeypatch.setattr(TranslationPlanner, "classify_no_trans", _fail_if_called)
    payload = [
        {
            "item_id": "p001-b001",
            "page_idx": 0,
            "block_idx": 1,
            "block_type": "text",
            "block_kind": "text",
            "layout_role": "paragraph",
            "semantic_role": "body",
            "structure_role": "body",
            "policy_translate": True,
            "source_text": "Default: 0\nType: <INT>",
            "protected_source_text": "Default: 0\nType: <INT>",
            "classification_label": "",
            "should_translate": True,
            "skip_reason": "",
            "translation_unit_kind": "single",
            "translation_unit_protected_source_text": "Default: 0\nType: <INT>",
            "translation_unit_formula_map": [],
            "formula_map": [],
            "mixed_original_protected_source_text": "",
            "translation_unit_protected_translated_text": "",
            "translation_unit_translated_text": "",
            "protected_translated_text": "",
            "translated_text": "",
            "group_protected_translated_text": "",
            "group_translated_text": "",
            "final_status": "",
            "layout_zone": "",
        }
    ]

    classified, _ = apply_translation_policies(
        payload=payload,
        mode="sci",
        classify_batch_size=8,
        workers=1,
        api_key="",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        skip_title_translation=False,
        page_idx=0,
        sci_cutoff_page_idx=None,
        sci_cutoff_block_idx=None,
    )

    assert classified == 0
    assert payload[0]["should_translate"] is True
    assert payload[0]["classification_label"] == ""

