from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import requests


REPO_SCRIPTS_ROOT = Path("REPO_ROOT_PLACEHOLDER/backend/scripts")
sys.path.insert(0, str(REPO_SCRIPTS_ROOT))


from services.translation.batching.pending_units import _translate_batch_or_keep_origin
from services.translation.llm.shared.control_context import build_translation_control_context


def _item(item_id: str, text: str, **overrides):
    item = {
        "item_id": item_id,
        "block_type": "text",
        "source_text": text,
        "protected_source_text": text,
        "should_translate": True,
    }
    item.update(overrides)
    return item


def test_translate_batch_wrapper_marks_transport_failure_failed() -> None:
    context = build_translation_control_context()
    batch = [
        _item("a", "This sentence describes antibacterial activity and provides enough body text for translation."),
        _item("b", "This paragraph keeps enough content for translation even when the network request times out."),
    ]
    with mock.patch(
        "services.translation.batching.pending_units.translate_batch",
        side_effect=requests.ConnectionError("Read timed out"),
    ):
        result = _translate_batch_or_keep_origin(
            batch,
            api_key="sk-test",
            model="deepseek-chat",
            base_url="https://api.deepseek.com/v1",
            request_label="book: batch 1/1",
            domain_guidance="",
            mode="fast",
            context=context,
        )

    assert result["a"]["decision"] == "translate"
    assert result["b"]["decision"] == "translate"
    assert result["a"]["translated_text"] == ""
    assert result["b"]["translated_text"] == ""
    assert result["a"]["final_status"] == "failed"
    assert result["b"]["final_status"] == "failed"
    assert result["a"]["translation_diagnostics"]["degradation_reason"] == "batch_transport_timeout_budget_exceeded"
    assert result["a"]["translation_diagnostics"]["fallback_to"] == "retry_required"
    assert result["a"]["translation_diagnostics"]["route_path"] == ["block_level", "batched_plain", "failed"]


def test_translate_batch_wrapper_appends_relevant_job_memory_to_domain_guidance() -> None:
    captured: dict[str, object] = {}

    class _MemoryStore:
        def summary(self) -> str:
            return "当前文档记忆：术语保持一致。\n- SCF => 自洽场\n- DFTB => 密度泛函紧束缚"

        def summary_for_batch(self, batch) -> str:
            source = "\n".join(str(item.get("source_text") or "") for item in batch)
            if "SCF" in source:
                return "当前块相关文档记忆：术语保持一致。\n- SCF => 自洽场"
            return ""

    def _fake_translate_fn(*_args, **kwargs):
        captured["domain_guidance"] = kwargs["domain_guidance"]
        captured["context"] = kwargs["context"]
        return {"a": {"decision": "translate", "translated_text": "自洽场"}}

    result = _translate_batch_or_keep_origin(
        [_item("a", "SCF")],
        api_key="sk-test",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        request_label="book: batch 1/1",
        domain_guidance="文档领域：量子化学。",
        mode="fast",
        context=build_translation_control_context(),
        memory_store=_MemoryStore(),
        translate_fn=_fake_translate_fn,
    )

    assert result["a"]["translated_text"] == "自洽场"
    assert "文档领域：量子化学。" in captured["domain_guidance"]
    assert "SCF => 自洽场" in captured["domain_guidance"]
    assert "DFTB =>" not in captured["domain_guidance"]
    assert "SCF => 自洽场" in captured["context"].merged_guidance
    assert "DFTB =>" not in captured["context"].merged_guidance
