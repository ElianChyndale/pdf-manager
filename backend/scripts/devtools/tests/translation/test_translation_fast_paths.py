import importlib.util
import json
import sys
import tempfile
import types
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock


REPO_SCRIPTS_ROOT = Path("REPO_ROOT_PLACEHOLDER/backend/scripts")
sys.path.insert(0, str(REPO_SCRIPTS_ROOT))


def _ensure_package_stubs():
    package_paths = {
        "services": REPO_SCRIPTS_ROOT / "services",
        "services.translation": REPO_SCRIPTS_ROOT / "services" / "translation",
        "services.translation.llm": REPO_SCRIPTS_ROOT / "services" / "translation" / "llm",
        "services.translation.llm.shared": REPO_SCRIPTS_ROOT / "services" / "translation" / "llm" / "shared",
        "services.translation.llm.shared.orchestration": REPO_SCRIPTS_ROOT / "services" / "translation" / "llm" / "shared" / "orchestration",
        "services.translation.llm.providers": REPO_SCRIPTS_ROOT / "services" / "translation" / "llm" / "providers",
        "services.translation.llm.providers.deepseek": REPO_SCRIPTS_ROOT / "services" / "translation" / "llm" / "providers" / "deepseek",
        "services.translation.orchestration": REPO_SCRIPTS_ROOT / "services" / "translation" / "orchestration",
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


def _load_continuation_package():
    return _load_module(
        "services.translation.continuation",
        REPO_SCRIPTS_ROOT / "services" / "translation" / "continuation" / "__init__.py",
    )


def _install_minimal_continuation_stub():
    rules_module = _load_module(
        "services.translation.continuation.rules",
        REPO_SCRIPTS_ROOT / "services" / "translation" / "continuation" / "rules.py",
    )
    pairs_module = _load_module(
        "services.translation.continuation.pairs",
        REPO_SCRIPTS_ROOT / "services" / "translation" / "continuation" / "pairs.py",
    )
    module = types.ModuleType("services.translation.continuation")
    module.apply_candidate_pair_joins = pairs_module.apply_candidate_pair_joins
    module.candidate_continuation_pairs = pairs_module.candidate_continuation_pairs
    module.pair_break_score = rules_module.pair_break_score
    module.pair_join_score = rules_module.pair_join_score
    module.review_candidate_pairs = lambda *args, **kwargs: {}
    sys.modules["services.translation.continuation"] = module
    return module


def _translate_direct_typst_for_test(module, item: dict, *, context, request_label: str = "test"):
    direct_typst = _load_module(
        "services.translation.llm.shared.orchestration.direct_typst",
        REPO_SCRIPTS_ROOT / "services" / "translation" / "llm" / "shared" / "orchestration" / "direct_typst.py",
    )
    return direct_typst.translate_direct_typst_plain_text_with_retries(
        item,
        api_key="",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        request_label=request_label,
        context=context,
        diagnostics=None,
        translator=module.translate_single_item_plain_text_with_retries,
        translate_plain_fn=module.translate_single_item_plain_text,
        translate_unstructured_fn=module.translate_single_item_plain_text_unstructured,
        sentence_level_fallback_fn=module._sentence_level_fallback,
        validate_batch_result_fn=module.validate_batch_result,
    )


class TranslationFastPathTests(unittest.TestCase):
    def test_direct_typst_protocol_shell_degrades_for_cjk_body_text(self):
        module = _load_module(
            "services.translation.llm.shared.orchestration.fallbacks",
            REPO_SCRIPTS_ROOT / "services" / "translation" / "llm" / "shared" / "orchestration" / "fallbacks.py",
        )
        context_module = _load_module(
            "services.translation.llm.shared.control_context",
            REPO_SCRIPTS_ROOT / "services" / "translation" / "llm" / "shared" / "control_context.py",
        )
        context = context_module.build_translation_control_context(mode="sci")
        item = {
            "item_id": "p036-b015",
            "page_idx": 35,
            "block_type": "text",
            "metadata": {"structure_role": "body"},
            "math_mode": "direct_typst",
            "translation_unit_protected_source_text": (
                "综上，本文系统综述了DFT计算在光催化领域中的广泛应用，并为未来开发高效稳定催化剂提供参考。"
            ),
            "protected_source_text": (
                "综上，本文系统综述了DFT计算在光催化领域中的广泛应用，并为未来开发高效稳定催化剂提供参考。"
            ),
        }

        protocol_exc = module.TranslationProtocolError(
            "p036-b015",
            translated_text='{"translations":[{"item_id":"p036-b015","translated_text":"综上，本文系统综述了DFT计算在光催化领域中的广泛应用。"}]}',
        )
        with mock.patch.object(
            module,
            "translate_single_item_plain_text",
            side_effect=protocol_exc,
        ), mock.patch.object(
            module,
            "translate_single_item_plain_text_unstructured",
            side_effect=protocol_exc,
        ):
            result = _translate_direct_typst_for_test(module, item, context=context)

        payload = result["p036-b015"]
        self.assertEqual(payload["decision"], "translate")
        self.assertEqual(payload["final_status"], "translated")
        self.assertEqual(
            payload["translation_diagnostics"]["degradation_reason"],
            "protocol_shell_salvaged",
        )

    def test_continuation_group_protocol_shell_degrades_to_keep_origin(self):
        module = _load_module(
            "services.translation.llm.shared.orchestration.fallbacks",
            REPO_SCRIPTS_ROOT / "services" / "translation" / "llm" / "shared" / "orchestration" / "fallbacks.py",
        )
        context_module = _load_module(
            "services.translation.llm.shared.control_context",
            REPO_SCRIPTS_ROOT / "services" / "translation" / "llm" / "shared" / "control_context.py",
        )
        context = context_module.build_translation_control_context(mode="sci")
        item = {
            "item_id": "__cg__:cg-028-037",
            "translation_unit_id": "__cg__:cg-028-037",
            "page_idx": 27,
            "block_type": "text",
            "metadata": {"structure_role": "body"},
            "math_mode": "placeholder",
            "continuation_group": "cg-028-037",
            "translation_unit_protected_source_text": (
                "Among the conversion reactions containing nitrogen, the oxidation of nitric oxide (NO) "
                "has received extensive attention in photocatalysis based on theoretical investigations as well."
            ),
            "protected_source_text": (
                "Among the conversion reactions containing nitrogen, the oxidation of nitric oxide (NO) "
                "has received extensive attention in photocatalysis based on theoretical investigations as well."
            ),
        }

        with mock.patch.object(
            module,
            "translate_single_item_plain_text",
            side_effect=module.TranslationProtocolError("__cg__:cg-028-037"),
        ), mock.patch.object(
            module,
            "translate_single_item_plain_text_unstructured",
            side_effect=module.TranslationProtocolError("__cg__:cg-028-037"),
        ), mock.patch.object(
            module,
            "_sentence_level_fallback",
            side_effect=module.TranslationProtocolError("__cg__:cg-028-037"),
        ) as sentence_mock:
            result = module.translate_single_item_plain_text_with_retries(
                item,
                api_key="",
                model="deepseek-chat",
                base_url="https://api.deepseek.com/v1",
                request_label="test",
                context=context,
                diagnostics=None,
            )

        payload = result["__cg__:cg-028-037"]
        sentence_mock.assert_not_called()
        self.assertEqual(payload["decision"], "keep_origin")
        self.assertEqual(payload["final_status"], "kept_origin")
        self.assertEqual(
            payload["translation_diagnostics"]["degradation_reason"],
            "protocol_shell_repeated",
        )

    def test_direct_typst_continuation_group_protocol_shell_is_salvaged(self):
        module = _load_module(
            "services.translation.llm.shared.orchestration.fallbacks",
            REPO_SCRIPTS_ROOT / "services" / "translation" / "llm" / "shared" / "orchestration" / "fallbacks.py",
        )
        context_module = _load_module(
            "services.translation.llm.shared.control_context",
            REPO_SCRIPTS_ROOT / "services" / "translation" / "llm" / "shared" / "control_context.py",
        )
        context = context_module.build_translation_control_context(mode="sci")
        item = {
            "item_id": "__cg__:cg-007-003",
            "translation_unit_id": "__cg__:cg-007-003",
            "page_idx": 6,
            "block_type": "text",
            "metadata": {"structure_role": "body"},
            "math_mode": "direct_typst",
            "continuation_group": "cg-007-003",
            "translation_unit_protected_source_text": (
                "Anthropic and OpenAI: Conversely, the clear message was that the AI model providers were grabbing more enterprise wallet share."
            ),
            "protected_source_text": (
                "Anthropic and OpenAI: Conversely, the clear message was that the AI model providers were grabbing more enterprise wallet share."
            ),
        }
        protocol_exc = module.TranslationProtocolError(
            "__cg__:cg-007-003",
            translated_text=(
                '{"translations":[{"item_id":"__cg__:cg-007-003","translated_text":"Anthropic与OpenAI：相反，一个明确的信息是，AI模型提供商正在攫取更多的企业钱包份额。"}]}'
            ),
        )

        with mock.patch.object(module, "translate_single_item_plain_text", side_effect=protocol_exc), mock.patch.object(
            module,
            "translate_single_item_plain_text_unstructured",
            side_effect=protocol_exc,
        ):
            result = _translate_direct_typst_for_test(module, item, context=context)

        payload = result["__cg__:cg-007-003"]
        self.assertEqual(payload["decision"], "translate")
        self.assertIn("Anthropic与OpenAI", payload["translated_text"])
        self.assertEqual(payload["translation_diagnostics"]["degradation_reason"], "protocol_shell_salvaged")

    def test_direct_typst_continuation_group_protocol_shell_partial_accepts_body_text(self):
        module = _load_module(
            "services.translation.llm.shared.orchestration.fallbacks",
            REPO_SCRIPTS_ROOT / "services" / "translation" / "llm" / "shared" / "orchestration" / "fallbacks.py",
        )
        context_module = _load_module(
            "services.translation.llm.shared.control_context",
            REPO_SCRIPTS_ROOT / "services" / "translation" / "llm" / "shared" / "control_context.py",
        )
        context = context_module.build_translation_control_context(mode="sci")
        item = {
            "item_id": "__cg__:cg-008-004",
            "translation_unit_id": "__cg__:cg-008-004",
            "page_idx": 7,
            "block_type": "text",
            "metadata": {"structure_role": "body"},
            "math_mode": "direct_typst",
            "continuation_group": "cg-008-004",
            "translation_unit_protected_source_text": "COBOL Code Modernization: It was just one data point so we’re highlighting it last.",
            "protected_source_text": "COBOL Code Modernization: It was just one data point so we’re highlighting it last.",
        }
        protocol_exc = module.TranslationProtocolError(
            "__cg__:cg-008-004",
            translated_text=(
                '{"translations":[{"item_id":"wrong-id","translated_text":"COBOL代码现代化：这只是一个数据点，因此我们最后才重点提及。"}]}'
            ),
        )

        with mock.patch.object(module, "translate_single_item_plain_text", side_effect=protocol_exc), mock.patch.object(
            module,
            "translate_single_item_plain_text_unstructured",
            side_effect=protocol_exc,
        ), mock.patch.object(
            module,
            "validate_batch_result",
            side_effect=module.TranslationProtocolError(
                "__cg__:cg-008-004",
                translated_text="COBOL代码现代化：这只是一个数据点，因此我们最后才重点提及。",
            ),
        ):
            result = _translate_direct_typst_for_test(module, item, context=context)

        payload = result["__cg__:cg-008-004"]
        self.assertEqual(payload["decision"], "translate")
        self.assertEqual(payload["translation_diagnostics"]["degradation_reason"], "protocol_shell_partial_accept")

    def test_direct_typst_long_text_is_split_before_remote_translation(self):
        module = _load_module(
            "services.translation.llm.shared.orchestration.fallbacks",
            REPO_SCRIPTS_ROOT / "services" / "translation" / "llm" / "shared" / "orchestration" / "fallbacks.py",
        )
        context_module = _load_module(
            "services.translation.llm.shared.control_context",
            REPO_SCRIPTS_ROOT / "services" / "translation" / "llm" / "shared" / "control_context.py",
        )
        context = context_module.build_translation_control_context(mode="sci")
        long_source = " ".join(f"This is sentence {i} describing a long legal disclaimer." for i in range(1, 180))
        item = {
            "item_id": "__cg__:cg-long-001",
            "translation_unit_id": "__cg__:cg-long-001",
            "page_idx": 17,
            "block_type": "text",
            "metadata": {"structure_role": "body"},
            "math_mode": "direct_typst",
            "continuation_group": "cg-long-001",
            "translation_unit_protected_source_text": long_source,
            "protected_source_text": long_source,
        }

        def _fake_plain_text(chunk_item, **_kwargs):
            text = str(chunk_item.get("translation_unit_protected_source_text", "") or "")
            return {
                chunk_item["item_id"]: {
                    "decision": "translate",
                    "translated_text": f"已翻译:{text[:24]}",
                    "final_status": "translated",
                }
            }

        with mock.patch.object(module, "translate_single_item_plain_text", side_effect=_fake_plain_text) as plain_mock:
            result = _translate_direct_typst_for_test(module, item, context=context)

        payload = result[item["item_id"]]
        self.assertEqual(payload["decision"], "translate")
        self.assertGreater(plain_mock.call_count, 1)
        self.assertEqual(payload["translation_diagnostics"]["route_path"], ["block_level", "direct_typst", "long_text_split"])

    def test_continuation_group_english_residue_does_not_enter_sentence_level_fallback(self):
        module = _load_module(
            "services.translation.llm.shared.orchestration.fallbacks",
            REPO_SCRIPTS_ROOT / "services" / "translation" / "llm" / "shared" / "orchestration" / "fallbacks.py",
        )
        control_context = _load_module(
            "services.translation.llm.shared.control_context",
            REPO_SCRIPTS_ROOT / "services" / "translation" / "llm" / "shared" / "control_context.py",
        )
        item = {
            "item_id": "__cg__:cg-001-001",
            "translation_unit_id": "__cg__:cg-001-001",
            "page_idx": 0,
            "block_type": "text",
            "continuation_group": "cg-001-001",
            "metadata": {"structure_role": "body"},
            "protected_source_text": "This is the first sentence. This is the second sentence.",
            "translation_unit_protected_source_text": "This is the first sentence. This is the second sentence.",
        }
        context = control_context.build_translation_control_context(mode="sci")
        context = replace(
            context,
            fallback_policy=replace(
                context.fallback_policy,
                plain_text_attempts=1,
                allow_tagged_placeholder_retry=False,
            ),
        )
        english_residue = module.EnglishResidueError(item["item_id"])

        with mock.patch.object(module, "translate_single_item_plain_text", side_effect=english_residue):
            with mock.patch.object(module, "translate_single_item_plain_text_unstructured", side_effect=english_residue):
                with mock.patch.object(module, "_sentence_level_fallback", side_effect=AssertionError("should not be called")):
                    result = module.translate_single_item_plain_text_with_retries(
                        item,
                        api_key="",
                        model="deepseek-chat",
                        base_url="https://api.deepseek.com/v1",
                        request_label="test",
                        context=context,
                        diagnostics=None,
                    )

        payload = result[item["item_id"]]
        self.assertEqual(payload["decision"], "translate")
        self.assertEqual(payload["translated_text"], "")
        self.assertEqual(payload["final_status"], "failed")
        self.assertEqual(payload["translation_diagnostics"]["degradation_reason"], "english_residue_repeated")

    def test_continuation_group_english_residue_with_partial_chinese_is_salvaged(self):
        module = _load_module(
            "services.translation.llm.shared.orchestration.fallbacks",
            REPO_SCRIPTS_ROOT / "services" / "translation" / "llm" / "shared" / "orchestration" / "fallbacks.py",
        )
        control_context = _load_module(
            "services.translation.llm.shared.control_context",
            REPO_SCRIPTS_ROOT / "services" / "translation" / "llm" / "shared" / "control_context.py",
        )
        item = {
            "item_id": "__cg__:cg-001-002",
            "translation_unit_id": "__cg__:cg-001-002",
            "page_idx": 0,
            "block_type": "text",
            "continuation_group": "cg-001-002",
            "metadata": {"structure_role": "body"},
            "protected_source_text": "This is the first sentence. This is the second sentence with reaction details.",
            "translation_unit_protected_source_text": "This is the first sentence. This is the second sentence with reaction details.",
        }
        context = control_context.build_translation_control_context(mode="sci")
        context = replace(
            context,
            fallback_policy=replace(
                context.fallback_policy,
                plain_text_attempts=1,
                allow_tagged_placeholder_retry=False,
            ),
        )
        english_residue = module.EnglishResidueError(
            item["item_id"],
            source_text=item["translation_unit_protected_source_text"],
            translated_text="这是第一句话。This is the second sentence with reaction details.",
        )

        with mock.patch.object(module, "translate_single_item_plain_text", side_effect=english_residue):
            with mock.patch.object(module, "translate_single_item_plain_text_unstructured", side_effect=english_residue):
                with mock.patch.object(module, "_sentence_level_fallback", side_effect=AssertionError("should not be called")):
                    result = module.translate_single_item_plain_text_with_retries(
                        item,
                        api_key="",
                        model="deepseek-chat",
                        base_url="https://api.deepseek.com/v1",
                        request_label="test",
                        context=context,
                        diagnostics=None,
                    )

        payload = result[item["item_id"]]
        self.assertEqual(payload["decision"], "translate")
        self.assertEqual(payload["translated_text"], "这是第一句话")
        self.assertEqual(payload["translation_diagnostics"]["degradation_reason"], "english_residue_tail_trimmed")
        self.assertEqual(payload["translation_diagnostics"]["route_path"], ["block_level", "english_residue_tail_trim"])

    def test_protocol_shell_unwrap_salvages_continuation_group_without_sentence_fallback(self):
        module = _load_module(
            "services.translation.llm.shared.orchestration.fallbacks",
            REPO_SCRIPTS_ROOT / "services" / "translation" / "llm" / "shared" / "orchestration" / "fallbacks.py",
        )
        control_context = _load_module(
            "services.translation.llm.shared.control_context",
            REPO_SCRIPTS_ROOT / "services" / "translation" / "llm" / "shared" / "control_context.py",
        )
        item = {
            "item_id": "__cg__:cg-005-007",
            "translation_unit_id": "__cg__:cg-005-007",
            "page_idx": 4,
            "block_type": "text",
            "continuation_group": "cg-005-007",
            "metadata": {"structure_role": "body"},
            "protected_source_text": "Orbital interactions provide only one of several factors. The transition state is significantly stabilized by electrostatic interactions.",
            "translation_unit_protected_source_text": "Orbital interactions provide only one of several factors. The transition state is significantly stabilized by electrostatic interactions.",
        }
        context = control_context.build_translation_control_context(mode="sci")
        shell_exc = module.TranslationProtocolError(
            item["item_id"],
            source_text=item["translation_unit_protected_source_text"],
            translated_text='{"translations":[{"item_id":"__cg__:cg-005-007","translated_text":"轨道相互作用仅是若干因素之一。该反应的过渡态因静电相互作用而显著稳定。"}]}',
        )

        with mock.patch.object(module, "translate_single_item_plain_text", side_effect=shell_exc):
            with mock.patch.object(module, "_sentence_level_fallback", side_effect=AssertionError("should not be called")):
                result = module.translate_single_item_plain_text_with_retries(
                    item,
                    api_key="",
                    model="deepseek-chat",
                    base_url="https://api.deepseek.com/v1",
                    request_label="test",
                    context=context,
                    diagnostics=None,
                )

        payload = result[item["item_id"]]
        self.assertEqual(payload["decision"], "translate")
        self.assertIn("轨道相互作用仅是若干因素之一", payload["translated_text"])
        self.assertEqual(payload["translation_diagnostics"]["route_path"], ["block_level", "protocol_shell_unwrap"])

    def test_formula_english_residue_marks_failed_after_all_fallbacks_fail(self):
        module = _load_module(
            "services.translation.llm.shared.orchestration.fallbacks",
            REPO_SCRIPTS_ROOT / "services" / "translation" / "llm" / "shared" / "orchestration" / "fallbacks.py",
        )
        control_context = _load_module(
            "services.translation.llm.shared.control_context",
            REPO_SCRIPTS_ROOT / "services" / "translation" / "llm" / "shared" / "control_context.py",
        )
        item = {
            "item_id": "p009-b067",
            "page_idx": 8,
            "block_type": "text",
            "metadata": {"structure_role": "body"},
            "protected_source_text": "Olefins offer the unique benefit of starting from prochiral <f1-8fa/> carbons.",
            "translation_unit_protected_source_text": "Olefins offer the unique benefit of starting from prochiral <f1-8fa/> carbons.",
            "formula_map": [{"placeholder": "<f1-8fa/>"}],
            "translation_unit_formula_map": [{"placeholder": "<f1-8fa/>"}],
        }
        context = control_context.build_translation_control_context(mode="sci")
        context = replace(
            context,
            fallback_policy=replace(
                context.fallback_policy,
                plain_text_attempts=1,
                allow_tagged_placeholder_retry=False,
            ),
        )

        english_residue = module.EnglishResidueError("p009-b067")
        with mock.patch.object(module, "translate_single_item_plain_text", side_effect=english_residue):
            with mock.patch.object(module, "translate_single_item_plain_text_unstructured", side_effect=english_residue):
                with mock.patch.object(module, "_sentence_level_fallback", side_effect=english_residue):
                    result = module.translate_single_item_plain_text_with_retries(
                        item,
                        api_key="",
                        model="deepseek-chat",
                        base_url="https://api.deepseek.com/v1",
                        request_label="test",
                        context=context,
                        diagnostics=None,
                    )
        payload = result["p009-b067"]
        self.assertEqual(payload["decision"], "translate")
        self.assertEqual(payload["translated_text"], "")
        self.assertEqual(payload["final_status"], "failed")
        self.assertEqual(payload["translation_diagnostics"]["degradation_reason"], "english_residue_repeated")

    def test_english_residue_after_raw_fallback_continues_to_sentence_level(self):
        module = _load_module(
            "services.translation.llm.shared.orchestration.fallbacks",
            REPO_SCRIPTS_ROOT / "services" / "translation" / "llm" / "shared" / "orchestration" / "fallbacks.py",
        )
        control_context = _load_module(
            "services.translation.llm.shared.control_context",
            REPO_SCRIPTS_ROOT / "services" / "translation" / "llm" / "shared" / "control_context.py",
        )
        placeholder_guard = _load_module(
            "services.translation.llm.placeholder_guard",
            REPO_SCRIPTS_ROOT / "services" / "translation" / "llm" / "placeholder_guard.py",
        )
        item = {
            "item_id": "p001-b002",
            "page_idx": 0,
            "block_type": "text",
            "metadata": {"structure_role": "body"},
            "protected_source_text": "This is the first sentence. This is the second sentence.",
            "translation_unit_protected_source_text": "This is the first sentence. This is the second sentence.",
        }
        context = control_context.build_translation_control_context(mode="sci")
        context = replace(
            context,
            fallback_policy=replace(
                context.fallback_policy,
                plain_text_attempts=1,
                allow_tagged_placeholder_retry=False,
            ),
        )
        english_residue = module.EnglishResidueError("p001-b002")
        sentence_payload = {
            "p001-b002": {
                "decision": "translate",
                "translated_text": "这是第一句。 第二句保留原文。",
                "final_status": "partially_translated",
            }
        }

        with mock.patch.object(module, "translate_single_item_plain_text", side_effect=english_residue):
            with mock.patch.object(module, "translate_single_item_plain_text_unstructured", side_effect=english_residue):
                with mock.patch.object(module, "_sentence_level_fallback", return_value=sentence_payload) as sentence_mock:
                    result = module.translate_single_item_plain_text_with_retries(
                        item,
                        api_key="",
                        model="deepseek-chat",
                        base_url="https://api.deepseek.com/v1",
                        request_label="test",
                        context=context,
                        diagnostics=None,
                    )
        self.assertEqual(result, sentence_payload)
        sentence_mock.assert_called_once()

    def test_direct_typst_english_residue_does_not_enter_sentence_level_fallback(self):
        module = _load_module(
            "services.translation.llm.shared.orchestration.fallbacks",
            REPO_SCRIPTS_ROOT / "services" / "translation" / "llm" / "shared" / "orchestration" / "fallbacks.py",
        )
        control_context = _load_module(
            "services.translation.llm.shared.control_context",
            REPO_SCRIPTS_ROOT / "services" / "translation" / "llm" / "shared" / "control_context.py",
        )
        item = {
            "item_id": "p001-b002",
            "page_idx": 0,
            "block_type": "text",
            "math_mode": "direct_typst",
            "metadata": {"structure_role": "body"},
            "protected_source_text": "This is the first sentence. This is the second sentence.",
            "translation_unit_protected_source_text": "This is the first sentence. This is the second sentence.",
        }
        context = control_context.build_translation_control_context(mode="sci")
        context = replace(
            context,
            fallback_policy=replace(
                context.fallback_policy,
                plain_text_attempts=1,
                allow_tagged_placeholder_retry=False,
            ),
        )
        english_residue = module.EnglishResidueError("p001-b002")

        with mock.patch.object(module, "translate_single_item_plain_text", side_effect=english_residue):
            with mock.patch.object(module, "translate_single_item_plain_text_unstructured", side_effect=english_residue):
                with mock.patch.object(module, "_sentence_level_fallback", side_effect=AssertionError("should not be called")):
                    result = module.translate_single_item_plain_text_with_retries(
                        item,
                        api_key="",
                        model="deepseek-chat",
                        base_url="https://api.deepseek.com/v1",
                        request_label="test",
                        context=context,
                        diagnostics=None,
                    )

        payload = result["p001-b002"]
        self.assertEqual(payload["decision"], "translate")
        self.assertEqual(payload["translated_text"], "")
        self.assertEqual(payload["final_status"], "failed")
        self.assertEqual(payload["translation_diagnostics"]["degradation_reason"], "english_residue_repeated")
        self.assertEqual(payload["translation_diagnostics"]["route_path"], ["block_level", "direct_typst", "failed"])

    def test_direct_typst_body_protocol_failure_falls_back_to_sentence_level(self):
        module = _load_module(
            "services.translation.llm.shared.orchestration.fallbacks",
            REPO_SCRIPTS_ROOT / "services" / "translation" / "llm" / "shared" / "orchestration" / "fallbacks.py",
        )
        control_context = _load_module(
            "services.translation.llm.shared.control_context",
            REPO_SCRIPTS_ROOT / "services" / "translation" / "llm" / "shared" / "control_context.py",
        )
        item = {
            "item_id": "p021-b005",
            "page_idx": 20,
            "block_type": "text",
            "math_mode": "direct_typst",
            "metadata": {"structure_role": "body"},
            "protected_source_text": (
                "Conventional Context Parallelism partitions the sequence dimension, with each rank "
                "maintaining contiguous s tokens. This introduces two challenges to our compressed "
                "attention mechanisms."
            ),
            "translation_unit_protected_source_text": (
                "Conventional Context Parallelism partitions the sequence dimension, with each rank "
                "maintaining contiguous s tokens. This introduces two challenges to our compressed "
                "attention mechanisms."
            ),
        }
        context = control_context.build_translation_control_context(mode="sci")
        context = replace(
            context,
            fallback_policy=replace(
                context.fallback_policy,
                plain_text_attempts=1,
                allow_tagged_placeholder_retry=False,
            ),
        )
        protocol_error = module.TranslationProtocolError(
            item["item_id"],
            source_text=item["translation_unit_protected_source_text"],
            translated_text='{"translated_text": ""}',
        )
        sentence_payload = {
            item["item_id"]: {
                "decision": "translate",
                "translated_text": "传统上下文并行将序列维度进行划分。",
                "final_status": "partially_translated",
                "translation_diagnostics": {
                    "route_path": ["block_level", "sentence_level"],
                    "fallback_to": "sentence_level",
                },
            }
        }

        with mock.patch.object(module, "translate_single_item_plain_text", side_effect=protocol_error):
            with mock.patch.object(module, "translate_single_item_plain_text_unstructured", side_effect=protocol_error):
                with mock.patch.object(module, "_sentence_level_fallback", return_value=sentence_payload) as sentence_mock:
                    result = module.translate_single_item_plain_text_with_retries(
                        item,
                        api_key="",
                        model="deepseek-chat",
                        base_url="https://api.deepseek.com/v1",
                        request_label="test",
                        context=context,
                        diagnostics=None,
                    )

        sentence_mock.assert_called_once()
        payload = result[item["item_id"]]
        self.assertEqual(payload["decision"], "translate")
        self.assertEqual(payload["final_status"], "partially_translated")
        self.assertIn("传统上下文并行", payload["translated_text"])

    def test_direct_typst_validation_failure_does_not_enter_tagged_placeholder_retry(self):
        module = _load_module(
            "services.translation.llm.shared.orchestration.fallbacks",
            REPO_SCRIPTS_ROOT / "services" / "translation" / "llm" / "shared" / "orchestration" / "fallbacks.py",
        )
        control_context = _load_module(
            "services.translation.llm.shared.control_context",
            REPO_SCRIPTS_ROOT / "services" / "translation" / "llm" / "shared" / "control_context.py",
        )
        item = {
            "item_id": "p001-b002",
            "page_idx": 0,
            "block_type": "text",
            "math_mode": "direct_typst",
            "metadata": {"structure_role": "body"},
            "protected_source_text": "This is body text with inline math x.",
            "translation_unit_protected_source_text": "This is body text with inline math x.",
        }
        context = control_context.build_translation_control_context(mode="sci")
        context = replace(
            context,
            fallback_policy=replace(
                context.fallback_policy,
                plain_text_attempts=1,
                allow_tagged_placeholder_retry=True,
            ),
        )
        english_residue = module.EnglishResidueError("p001-b002")

        with mock.patch.object(module, "translate_single_item_plain_text", side_effect=english_residue):
            with mock.patch.object(module, "translate_single_item_plain_text_unstructured", side_effect=english_residue):
                with mock.patch.object(module, "translate_single_item_stable_placeholder_text", side_effect=AssertionError("should not be called")):
                    result = module.translate_single_item_plain_text_with_retries(
                        item,
                        api_key="",
                        model="deepseek-chat",
                        base_url="https://api.deepseek.com/v1",
                        request_label="test",
                        context=context,
                        diagnostics=None,
                    )

        self.assertEqual(result["p001-b002"]["decision"], "keep_origin")

    def test_continuation_group_with_placeholders_uses_plain_path_first(self):
        module = _load_module(
            "services.translation.llm.shared.orchestration.fallbacks",
            REPO_SCRIPTS_ROOT / "services" / "translation" / "llm" / "shared" / "orchestration" / "fallbacks.py",
        )
        control_context = _load_module(
            "services.translation.llm.shared.control_context",
            REPO_SCRIPTS_ROOT / "services" / "translation" / "llm" / "shared" / "control_context.py",
        )
        item = {
            "item_id": "__cg__:cg-009-013",
            "translation_unit_id": "__cg__:cg-009-013",
            "page_idx": 8,
            "block_type": "text",
            "continuation_group": "cg-009-013",
            "metadata": {"structure_role": "body"},
            "protected_source_text": "This continuation group mentions <f1-c1b/> and <f2-a77/> inside a long body paragraph.",
            "translation_unit_protected_source_text": "This continuation group mentions <f1-c1b/> and <f2-a77/> inside a long body paragraph.",
            "formula_map": [{"placeholder": "<f1-c1b/>"}, {"placeholder": "<f2-a77/>"}],
            "translation_unit_formula_map": [{"placeholder": "<f1-c1b/>"}, {"placeholder": "<f2-a77/>"}],
        }
        context = control_context.build_translation_control_context(mode="sci")

        with mock.patch.object(
            module,
            "translate_single_item_stable_placeholder_text",
            side_effect=AssertionError("tagged-first should not run"),
        ) as tagged_mock:
            with mock.patch.object(module, "translate_single_item_plain_text") as plain_mock:
                plain_mock.return_value = {
                    item["item_id"]: {
                        "decision": "translate",
                        "translated_text": "该连续段落提到 <f1-c1b/> 与 <f2-a77/>。",
                        "final_status": "translated",
                    }
                }
                result = module.translate_single_item_plain_text_with_retries(
                    item,
                    api_key="",
                    model="deepseek-chat",
                    base_url="https://api.deepseek.com/v1",
                    request_label="test",
                    context=context,
                    diagnostics=None,
                )
        tagged_mock.assert_not_called()
        plain_mock.assert_called_once()
        payload = result[item["item_id"]]
        self.assertEqual(payload["translation_diagnostics"]["route_path"], ["block_level"])
        self.assertEqual(payload["translation_diagnostics"]["output_mode_path"], ["plain_text"])

if __name__ == "__main__":
    unittest.main()
