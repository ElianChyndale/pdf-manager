from __future__ import annotations

from collections import Counter
import re

from services.translation.diagnostics import TranslationDiagnosticsCollector
from services.translation.llm.validation.errors import EnglishResidueError
from services.translation.llm.validation.errors import TranslationProtocolError
import services.translation.llm.shared.orchestration.intentional_keep_origin as intentional_keep_origin
import services.translation.llm.shared.orchestration.terminal_payloads as terminal_payloads


_EN_WORD_RE = re.compile(r"[A-Za-z]+(?:[-'][A-Za-z]+)?")
_EN_RESIDUE_SEGMENT_RE = re.compile(r"[A-Za-z][A-Za-z0-9\s,;:()'./%+-]{30,}")


def _is_named_exception(exc: Exception, *names: str) -> bool:
    return type(exc).__name__ in set(names)


def _english_words(text: str) -> list[str]:
    return [word.lower() for word in _EN_WORD_RE.findall(str(text or ""))]


def _english_word_overlap_ratio(words: list[str], source_words: list[str]) -> float:
    if not words or not source_words:
        return 0.0
    words_counter = Counter(words)
    source_counter = Counter(source_words)
    shared = sum(min(words_counter[token], source_counter[token]) for token in words_counter)
    return shared / max(1, len(words))


def _trim_copied_english_tail(
    source_text: str,
    translated_text: str,
    *,
    zh_char_count_fn,
) -> str | None:
    text = str(translated_text or "").strip()
    if not text:
        return None
    if zh_char_count_fn(text) < 6:
        return None

    source_words = _english_words(source_text)
    if len(source_words) < 8:
        return None

    for match in _EN_RESIDUE_SEGMENT_RE.finditer(text):
        segment = " ".join((match.group(0) or "").split())
        segment_words = _english_words(segment)
        if len(segment_words) < 8:
            continue

        prefix = text[: match.start()]
        if zh_char_count_fn(prefix) < 4:
            continue

        overlap_ratio = _english_word_overlap_ratio(segment_words, source_words)
        if overlap_ratio < 0.55:
            continue

        suffix = text[match.end() :]
        if suffix and re.search(r"[A-Za-z\u4e00-\u9fff0-9]", suffix):
            continue

        cleaned = prefix.rstrip(" \t\r\n-—:;,.")
        if zh_char_count_fn(cleaned) < 4:
            continue
        return cleaned

    return None


def try_salvage_protocol_shell_error(
    item: dict,
    *,
    exc: TranslationProtocolError,
    context,
    diagnostics: TranslationDiagnosticsCollector | None,
    route_path: list[str],
    output_mode_path: list[str],
    unwrap_translation_shell_fn,
    result_entry_fn,
    canonicalize_batch_result_fn,
    validate_batch_result_fn,
    restore_runtime_term_tokens_fn,
    attach_result_metadata_fn,
) -> dict[str, dict[str, str]] | None:
    raw_text = str(getattr(exc, "translated_text", "") or "").strip()
    if not raw_text:
        return None
    unwrapped = unwrap_translation_shell_fn(raw_text, item_id=str(item.get("item_id", "") or ""))
    if not unwrapped or unwrapped == raw_text:
        return None
    try:
        result = {str(item.get("item_id", "") or ""): result_entry_fn("translate", unwrapped)}
        result = canonicalize_batch_result_fn([item], result)
        validate_batch_result_fn([item], result, diagnostics=diagnostics)
        result = restore_runtime_term_tokens_fn(result, item=item)
        return attach_result_metadata_fn(
            result,
            item=item,
            context=context,
            route_path=route_path,
            output_mode_path=output_mode_path,
        )
    except Exception:
        return None


def try_salvage_partial_english_residue(
    item: dict,
    *,
    exc: EnglishResidueError,
    context,
    zh_char_count_fn,
    canonicalize_batch_result_fn,
    validate_batch_result_fn,
    result_entry_fn,
    restore_runtime_term_tokens_fn,
    attach_result_metadata_fn,
) -> dict[str, dict[str, str]] | None:
    cleaned_text = _trim_copied_english_tail(
        str(getattr(exc, "source_text", "") or ""),
        str(getattr(exc, "translated_text", "") or ""),
        zh_char_count_fn=zh_char_count_fn,
    )
    if not cleaned_text:
        return None
    try:
        result = canonicalize_batch_result_fn(
            [item],
            {str(item.get("item_id", "") or ""): result_entry_fn("translate", cleaned_text)},
        )
        validate_batch_result_fn([item], result)
        result = restore_runtime_term_tokens_fn(result, item=item)
        return attach_result_metadata_fn(
            result,
            item=item,
            context=context,
            route_path=["block_level", "english_residue_tail_trim"],
            output_mode_path=["plain_text"],
            degradation_reason="english_residue_tail_trimmed",
        )
    except Exception:
        return None


def finalize_plain_text_validation_failure(
    item: dict,
    *,
    last_error: Exception,
    context,
    diagnostics: TranslationDiagnosticsCollector | None,
    request_label: str,
    route_prefix: list[str],
    should_keep_origin_on_protocol_shell_fn,
    should_force_translate_body_text_fn,
    has_formula_placeholders_fn,
    try_salvage_partial_english_residue_fn,
) -> dict[str, dict[str, str]] | None:
    if _is_named_exception(last_error, "EnglishResidueError"):
        salvaged = try_salvage_partial_english_residue_fn(item, exc=last_error, context=context)
        if salvaged is not None:
            if diagnostics is not None:
                diagnostics.emit(
                    kind="english_residue_tail_trimmed",
                    item_id=str(item.get("item_id", "") or ""),
                    page_idx=item.get("page_idx"),
                    severity="warning",
                    message="Trimmed copied English residue tail after repeated English-residue validation failure",
                    retryable=True,
                )
            if request_label:
                print(
                    f"{request_label}: trimmed copied English residue tail after repeated validation failure",
                    flush=True,
                )
            return salvaged
        if diagnostics is not None:
            diagnostics.emit(
                kind="english_residue_degraded",
                item_id=str(item.get("item_id", "") or ""),
                page_idx=item.get("page_idx"),
                severity="warning",
                message="Degraded to keep_origin after repeated English-residue validation failure",
                retryable=True,
            )
        if request_label:
            print(f"{request_label}: degraded to keep_origin after repeated English-residue validation failure", flush=True)
        return terminal_payloads.translation_failed_payload_for_validation(
            item,
            context=context,
            route_path=route_prefix + ["failed"],
            degradation_reason="english_residue_repeated",
            error_code="ENGLISH_RESIDUE",
        )

    if _is_named_exception(last_error, "TranslationProtocolError") and should_keep_origin_on_protocol_shell_fn(item):
        if diagnostics is not None:
            diagnostics.emit(
                kind="protocol_shell_degraded",
                item_id=str(item.get("item_id", "") or ""),
                page_idx=item.get("page_idx"),
                severity="warning",
                message="Degraded to keep_origin after repeated protocol/json shell output",
                retryable=True,
            )
        if request_label:
            print(f"{request_label}: degraded to keep_origin after repeated protocol/json shell output", flush=True)
        return intentional_keep_origin.keep_origin_payload_for_validation(
            item,
            context=context,
            route_path=route_prefix + ["keep_origin"],
            degradation_reason="protocol_shell_repeated",
            error_code="PROTOCOL_SHELL",
        )

    if _is_named_exception(last_error, "TranslationProtocolError"):
        return terminal_payloads.translation_failed_payload_for_validation(
            item,
            context=context,
            route_path=route_prefix + ["failed"],
            degradation_reason="protocol_shell_repeated",
            error_code="PROTOCOL_SHELL",
        )

    if _is_named_exception(last_error, "MathDelimiterError") and not should_force_translate_body_text_fn(item):
        if diagnostics is not None:
            diagnostics.emit(
                kind="math_delimiter_degraded",
                item_id=str(item.get("item_id", "") or ""),
                page_idx=item.get("page_idx"),
                severity="warning",
                message="Degraded to keep_origin after repeated inline math delimiter failure",
                retryable=True,
            )
        if request_label:
            print(f"{request_label}: degraded to keep_origin after repeated inline math delimiter failure", flush=True)
        return intentional_keep_origin.keep_origin_payload_for_validation(
            item,
            context=context,
            route_path=route_prefix + ["keep_origin"],
            degradation_reason="math_delimiter_unbalanced",
            error_code="MATH_DELIMITER_UNBALANCED",
        )

    if _is_named_exception(last_error, "EmptyTranslationError") and not should_force_translate_body_text_fn(item):
        if diagnostics is not None:
            diagnostics.emit(
                kind="empty_translation_degraded",
                item_id=str(item.get("item_id", "") or ""),
                page_idx=item.get("page_idx"),
                severity="warning",
                message="Degraded to keep_origin after repeated empty translation output",
                retryable=True,
            )
        if request_label:
            print(f"{request_label}: degraded to keep_origin after repeated empty translation output", flush=True)
        return intentional_keep_origin.keep_origin_payload_for_repeated_empty_translation(item)

    if _is_named_exception(last_error, "EmptyTranslationError"):
        return terminal_payloads.translation_failed_payload_for_validation(
            item,
            context=context,
            route_path=route_prefix + ["failed"],
            degradation_reason="empty_translation_repeated",
            error_code="EMPTY_TRANSLATION",
        )

    if (
        has_formula_placeholders_fn(item)
        and context.fallback_policy.allow_keep_origin_degradation
        and _is_named_exception(last_error, "UnexpectedPlaceholderError", "PlaceholderInventoryError")
    ):
        if diagnostics is not None:
            diagnostics.emit(
                kind="placeholder_unstable",
                item_id=str(item.get("item_id", "") or ""),
                page_idx=item.get("page_idx"),
                severity="warning",
                message="Degraded to keep_origin after repeated placeholder instability",
                retryable=True,
            )
        if request_label:
            print(f"{request_label}: degraded to keep_origin after repeated placeholder instability", flush=True)
        return terminal_payloads.translation_failed_payload_for_validation(
            item,
            context=context,
            route_path=route_prefix + ["failed"],
            degradation_reason="placeholder_unstable",
            error_code="PLACEHOLDER_UNSTABLE",
        )

    return None
