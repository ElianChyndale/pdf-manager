import sys
from pathlib import Path


REPO_SCRIPTS_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_SCRIPTS_ROOT))


from services.translation.llm.shared.cache import cache_key_for_item
from services.translation.llm.shared import cache


def test_translation_cache_key_includes_translation_style_hint() -> None:
    base_item = {
        "item_id": "p001-b001",
        "translation_unit_protected_source_text": "Default: 0",
    }
    hinted_item = {
        **base_item,
        "translation_style_hint": "保持结构化字段名和值。",
        "translation_structure_kind": "structured_technical_block",
    }

    before = cache_key_for_item(
        base_item,
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        mode="sci",
    )
    after = cache_key_for_item(
        hinted_item,
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        mode="sci",
    )

    assert before != after


def test_translation_cache_key_includes_target_language() -> None:
    item = {
        "item_id": "p001-b001",
        "translation_unit_protected_source_text": "Default: 0",
    }

    zh_key = cache_key_for_item(
        item,
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        mode="sci",
        target_lang="zh-CN",
        target_language_name="简体中文",
    )
    en_key = cache_key_for_item(
        item,
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        mode="sci",
        target_lang="en",
        target_language_name="英文",
    )

    assert zh_key != en_key


def test_translation_cache_key_includes_policy_version(monkeypatch) -> None:
    item = {
        "item_id": "p001-b001",
        "translation_unit_protected_source_text": "Default: 0",
    }

    before = cache.cache_key_for_item(
        item,
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com/v1",
        mode="sci",
    )
    monkeypatch.setattr(cache, "TRANSLATION_POLICY_VERSION", "policy-test-version")
    after = cache.cache_key_for_item(
        item,
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com/v1",
        mode="sci",
    )

    assert before != after
