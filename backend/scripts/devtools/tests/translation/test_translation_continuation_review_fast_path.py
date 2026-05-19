import sys
import types
from pathlib import Path


REPO_SCRIPTS_ROOT = Path("REPO_ROOT_PLACEHOLDER/backend/scripts")
sys.path.insert(0, str(REPO_SCRIPTS_ROOT))


from services.translation.continuation import pairs as continuation_pairs
from services.translation.continuation import rules as continuation_rules
from services.translation.orchestration import document_orchestrator


def _install_minimal_continuation_stub() -> None:
    module = types.ModuleType("services.translation.continuation")
    module.apply_candidate_pair_joins = continuation_pairs.apply_candidate_pair_joins
    module.candidate_continuation_pairs = continuation_pairs.candidate_continuation_pairs
    module.pair_break_score = continuation_rules.pair_break_score
    module.pair_join_score = continuation_rules.pair_join_score
    module.review_candidate_pairs = lambda *args, **kwargs: {}
    sys.modules["services.translation.continuation"] = module


def test_continuation_review_short_circuits_high_confidence_pairs() -> None:
    _install_minimal_continuation_stub()
    flat_payload = [
        {
            "item_id": "a",
            "page_idx": 0,
            "block_type": "text",
            "protected_source_text": "This sentence continues with",
            "bbox": [10, 10, 200, 30],
        },
        {
            "item_id": "b",
            "page_idx": 1,
            "block_type": "text",
            "protected_source_text": "and additional evidence from the experiment.",
            "bbox": [10, 10, 200, 30],
        },
        {
            "item_id": "c",
            "page_idx": 1,
            "block_type": "text",
            "protected_source_text": "Conclusion.",
            "bbox": [220, 10, 320, 30],
        },
        {
            "item_id": "d",
            "page_idx": 1,
            "block_type": "text",
            "protected_source_text": "Methods",
            "bbox": [10, 50, 120, 70],
        },
    ]
    pairs = [
        {"prev_item_id": "a", "next_item_id": "b"},
        {"prev_item_id": "c", "next_item_id": "d"},
    ]
    auto_join, review = document_orchestrator._split_high_confidence_continuation_pairs(
        flat_payload,
        pairs,
    )

    assert auto_join == [("a", "b")]
    assert review == []


def test_continuation_review_keeps_mid_confidence_pairs_for_review() -> None:
    _install_minimal_continuation_stub()
    flat_payload = [
        {
            "item_id": "a",
            "page_idx": 0,
            "block_type": "text",
            "protected_source_text": "This paragraph ends with a complete noun phrase",
            "bbox": [10, 10, 220, 30],
        },
        {
            "item_id": "b",
            "page_idx": 1,
            "block_type": "text",
            "protected_source_text": "Results are summarized below.",
            "bbox": [10, 10, 240, 30],
        },
    ]
    pairs = [{"prev_item_id": "a", "next_item_id": "b"}]

    auto_join, review = document_orchestrator._split_high_confidence_continuation_pairs(
        flat_payload,
        pairs,
    )

    assert auto_join == []
    assert review == pairs
