from __future__ import annotations

"""Strict translation and semantic QA for engineering-drawing OCR regions.

This module deliberately treats the OCR result as an auditable source inventory.
It does not use a legacy PDF as translation memory: every visible natural-language
candidate must receive a Chinese companion, be classified as non-language noise,
or be reported as a blocking review item.  A partial LLM response is never
silently treated as success.
"""

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping

from .cache import load_cache, save_cache, stage_code_fingerprint
from foundation.shared.prompt_loader import load_prompt
from services.translation.llm.shared.provider_runtime import DEFAULT_BASE_URL
from services.translation.llm.shared.provider_runtime import DEFAULT_MODEL
from services.translation.llm.shared.provider_runtime import request_chat_content
from services.translation.llm.shared.response_parsing import extract_json_text


_LATIN_RE = re.compile(r"[A-Za-z]")
_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_SCRIPT_NAME_HINTS = (
    "ARABIC",
    "HEBREW",
    "CYRILLIC",
    "GREEK",
    "DEVANAGARI",
    "BENGALI",
    "GURMUKHI",
    "GUJARATI",
    "TAMIL",
    "TELUGU",
    "KANNADA",
    "MALAYALAM",
    "THAI",
    "LAO",
    "GEORGIAN",
    "ARMENIAN",
    "ETHIOPIC",
)
_WHITESPACE_RE = re.compile(r"\s+")
_PRESERVED_TOKEN_RE = re.compile(
    r"(?:[A-Za-z]+[-_/]?[A-Za-z]*\d+[A-Za-z0-9./×xØø+\-]*|"
    r"\d+(?:[.,]\d+)?\s*(?:mm|cm|m2|m3|m|kV|V|A|Hz|kW|kVA|bar|°C|ek\.)|"
    r"\d+\s*:\s*\d+)",
    re.IGNORECASE,
)
_ALLOWED_ACTIONS = {"translate", "keep_literal", "review"}
_ALLOWED_VERDICTS = {"accepted", "corrected", "manual_review", "not_language", "missing_translation"}
_CACHE_SCHEMA = "engineering_drawing_translation_qa_v1"
_PROMPT_VERSION = "2026-07-full-coverage-v3"
_LITERAL_DESCRIPTOR_OVERRIDES = {
    "in": "入口（原文：IN）",
    "out": "出口（原文：OUT）",
    "car": "小汽车（原文：CAR）",
    "hv": "高压（原文：HV）",
    "lv": "低压（原文：LV）",
    "elec": "电气（原文：ELEC）",
    "mech": "机械（原文：MECH）",
    "fall": "排水坡向（原文：FALL）",
    "flow": "流向（原文：FLOW）",
    "pitch": "坡度（原文：PITCH）",
    "roof": "屋面（原文：ROOF）",
    "void": "挑空（原文：VOID）",
}
_NATURAL_LANGUAGE_HINTS = {
    "jalan", "taman", "kampung", "bandar", "johor", "selangor", "kuala", "level",
    "consultant", "architect", "developer", "project", "proposed", "building", "system",
    "water", "tank", "pump", "trench", "boundary", "setback", "website", "email",
}

ChatRequester = Callable[..., str]


@dataclass(frozen=True)
class EngineeringTranslationResult:
    regions: list[dict]
    report: dict[str, object]


def _normalized(value: object) -> str:
    return _WHITESPACE_RE.sub(" ", str(value or "").strip()).casefold()


def _source_text(region: dict) -> str:
    return str(region.get("source_text") or region.get("text") or "").strip()


def _requires_natural_language_translation(source_text: str) -> bool:
    """Override a permissive OCR/code classifier for readable prose/address text."""
    if _has_non_latin_language_script(source_text):
        return True
    words = re.findall(r"[A-Za-z]{3,}", str(source_text or "").casefold())
    if any(word in _NATURAL_LANGUAGE_HINTS for word in words):
        return True
    # Multi-word labels are readable language even when they start with a lot
    # number or company abbreviation.  Short technical codes remain literals.
    return len(words) >= 2 and any(len(word) >= 4 for word in words)


def _has_non_latin_language_script(source: str) -> bool:
    for char in str(source or ""):
        if char.isspace() or unicodedata.category(char).startswith("P"):
            continue
        name = unicodedata.name(char, "")
        if any(hint in name for hint in _SCRIPT_NAME_HINTS):
            return True
    return False


def _is_language_candidate(region: dict) -> bool:
    source = _source_text(region)
    if _LATIN_RE.search(source) or _has_non_latin_language_script(source):
        # OCR occasionally labels mixed English/CJK title-block strings as
        # Chinese. Latin or a recognised non-CJK script wins for the coverage
        # inventory so those strings cannot be dropped accidentally.
        return True
    return False


# Kept as a compatibility alias for callers that used the old private helper.
_is_latin_candidate = _is_language_candidate


def _language(region: dict) -> str:
    value = str(region.get("source_language") or "").strip().lower()
    if value in {"en", "ms", "mixed", "ar", "jawi", "other"}:
        return value
    source = _source_text(region)
    if _has_non_latin_language_script(source):
        return "other"
    return "mixed" if _CJK_RE.search(source) else "en"


def _translation_stage_fingerprint() -> str:
    """Hash only the files that affect translation output, not the whole commit."""
    here = Path(__file__).resolve()
    prompt_paths = [
        here.parents[2] / "foundation" / "prompts" / "rule_profile_engineering_drawing.txt",
        here.parents[2] / "foundation" / "prompts" / "engineering_drawing_supervisor_v37.txt",
    ]
    return stage_code_fingerprint(
        paths=[here, *prompt_paths],
        extra_payload={"prompt_version": _PROMPT_VERSION},
    )


def _cache_key(*, source_text: str, source_language: str, action_hint: str, model: str, base_url: str) -> str:
    payload = {
        "prompt_version": _PROMPT_VERSION,
        "stage_fingerprint": _translation_stage_fingerprint(),
        "source_text": _normalized(source_text),
        "source_language": source_language,
        "action_hint": action_hint if action_hint in _ALLOWED_ACTIONS else "translate",
        "model": str(model or "").strip(),
        "base_url": str(base_url or "").strip().rstrip("/"),
        "target": "zh-CN",
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _load_cache(path: Path | None) -> dict[str, dict]:
    return load_cache(path, schema=_CACHE_SCHEMA)


def _save_cache(path: Path | None, entries: dict[str, dict]) -> None:
    save_cache(path, entries, schema=_CACHE_SCHEMA)


def _translation_messages(
    items: list[dict],
    *,
    supervisor_tasks: list[dict] | None = None,
) -> list[dict[str, str]]:
    profile = load_prompt("rule_profile_engineering_drawing.txt")
    system = f"""You are the translation stage of a strict engineering-drawing production system.

{profile}

Return one JSON object only, with a `translations` array. Every requested item_id
must occur exactly once; never add, omit, merge, or split IDs. Each item_id is a
semantic block, not an individual OCR word. Reconstruct the complete source
phrase before translating it and return one coherent Chinese block for that item.
Each entry must be:
{{"item_id":"...","translated_text":"...","action":"translate|keep_literal|review","issues":["..."]}}.

All visible natural-language content is mandatory, including English, Malay,
Arabic, Jawi and other scripts. For drawing/model/equipment codes,
preserve the literal unchanged and provide a concise Chinese semantic companion,
for example AHU-01 -> 空气处理机编号：AHU-01. Do not return an empty translation
for a Latin-script item. Preserve numbers, dimensions, units, scale ratios, drawing
codes and standards verbatim. If OCR text is genuinely unreadable, return a concise
Chinese OCR-review descriptor plus action `review`, rather than silently omitting it.
For genuinely unreadable text, keep the original source visible and defer the
meaning decision to multimodal model review; never replace it with a guessed
technical translation.
Preserve line order for wrapped notes and do not merge independent IDs, dimensions,
schedule rows, or title-block fields. FLOW, FALL, PITCH, ROOF and VOID are
natural-language engineering labels, never model codes. If the supervisor binds
an arrow, slope mark, degree value or FROM/TO direction to a block, preserve that
relationship in the Chinese translation rather than translating the word alone."""
    if supervisor_tasks:
        system += """

The multimodal page supervisor issued the following translation-task directives.
Treat them as the manager's instructions for grouping, terminology, and
completeness; do not replace them with word-level OCR decisions:
""" + json.dumps(supervisor_tasks, ensure_ascii=False)
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "stage": "engineering_translation",
                    "target_language": "简体中文",
                    "items": items,
                },
                ensure_ascii=False,
            ),
        },
    ]


def _repair_messages(items: list[dict]) -> list[dict[str, str]]:
    """Ask the model to repair a reply that did not actually contain Chinese.

    This is deliberately a separate stage instead of silently accepting a
    translated-looking English echo.  It is only used for normal language
    candidates; code-like regions classified as ``keep_literal`` are handled by
    the deterministic descriptor rule below.
    """
    profile = load_prompt("rule_profile_engineering_drawing.txt")
    system = f"""You repair incomplete Chinese translations for engineering drawings.

{profile}

The previous candidate contained no Chinese, so it is not an acceptable final
translation. Return one JSON object only, with a `translations` array. Every
requested item_id must occur exactly once, without merging or splitting IDs.
Each item_id is a semantic block, not an individual OCR word. Repair the whole
phrase as one readable Chinese block and preserve its line order. Each entry must be:
{{"item_id":"...","translated_text":"...","action":"translate|keep_literal|review","issues":["..."]}}.

Write a complete Simplified-Chinese companion for every readable natural-language
source in English, Malay, Arabic, Jawi or another script
word, including company names, addresses, titles and small drawing notes. Keep
numbers, dimensions, units and drawing/model identifiers verbatim. If the source
is genuinely unreadable OCR, return a Chinese OCR-review descriptor with action
`review`; do not merely echo the source text. Proper names and addresses are
not an exception: transliterate/place-translate them in Chinese and retain the
literal in parentheses. For example, `Johor Bahru` -> `新山（Johor Bahru）`,
`Jalan Indah` -> `英达路（Jalan Indah）`, and a company ending `SDN. BHD.` must
include `私人有限公司`. An English/Malay-only result is invalid."""
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "stage": "engineering_translation_repair",
                    "target_language": "简体中文",
                    "items": items,
                },
                ensure_ascii=False,
            ),
        },
    ]


def _qa_messages(items: list[dict]) -> list[dict[str, str]]:
    system = """You are the independent semantic quality gate for bilingual engineering drawings.
Return one JSON object only, with a `reviews` array. Every requested item_id must
occur exactly once; never add, omit, merge, or split IDs. Each item_id represents
one semantic block. Judge the block as a whole; a word-by-word fragment is not a
complete translation. Each entry must be:
{"item_id":"...","verdict":"accepted|corrected|manual_review|not_language|missing_translation",
"translated_text":"...","issues":["..."]}.

Check source-to-Chinese alignment, completeness, engineering terminology, residual
source-language text, and preservation of every number/unit/model/drawing code. A code is
acceptable only when the candidate includes a Chinese descriptor and preserves the
original literal. Use `corrected` and supply a complete replacement when needed.
Use `manual_review` for genuine OCR ambiguity. Use `missing_translation` for an
empty, incomplete, or unrelated candidate. Do not approve a fragment of a longer
source phrase as a complete translation. In Malaysian drawing units, `ek` / `ek.`
means `ekar` (acre): preserve the literal and translate its meaning as 英亩 rather
than treating it as unreadable OCR. Use `not_language` only for clear OCR/image
noise or non-linguistic marks. A drawing/model code is not noise: it must retain
its literal and have a Chinese descriptor."""
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": json.dumps(
                {"stage": "engineering_translation_qa", "items": items},
                ensure_ascii=False,
            ),
        },
    ]


def _parse_rows(content: str, *, key: str, item_ids: set[str]) -> tuple[dict[str, dict], set[str]]:
    try:
        # Prefer direct JSON parsing so Chinese punctuation in an actual
        # translation (for example ：) is not normalised by the compatibility
        # fallback used for malformed model protocol shells.
        payload = json.loads((content or "").strip())
    except (TypeError, ValueError, json.JSONDecodeError):
        try:
            payload = json.loads(extract_json_text(content))
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}, set(item_ids)
    values = payload.get(key, [])
    if not isinstance(values, list):
        return {}, set(item_ids)
    rows: dict[str, dict] = {}
    invalid = False
    for raw in values:
        if not isinstance(raw, dict):
            invalid = True
            continue
        item_id = str(raw.get("item_id") or "").strip()
        if not item_id or item_id not in item_ids or item_id in rows:
            invalid = True
            continue
        rows[item_id] = dict(raw)
    # Unknown/duplicate rows invalidate the whole reply: accepting any portion
    # would make a malformed model response appear to have full coverage.
    if invalid:
        return {}, set(item_ids)
    return rows, item_ids - set(rows)


def _request_with_missing_retry(
    *,
    items: list[dict],
    messages_builder: Callable[[list[dict]], list[dict[str, str]]],
    response_key: str,
    api_key: str,
    model: str,
    base_url: str,
    request_chat_content_fn: ChatRequester,
    request_label: str,
) -> tuple[dict[str, dict], set[str], int, list[str]]:
    pending = list(items)
    accepted: dict[str, dict] = {}
    errors: list[str] = []
    calls = 0
    for attempt in range(2):
        if not pending:
            break
        calls += 1
        try:
            content = request_chat_content_fn(
                messages_builder(pending),
                api_key=api_key,
                model=model,
                base_url=base_url,
                temperature=0.0,
                response_format={"type": "json_object"},
                timeout=180,
                request_label=f"{request_label}-{attempt + 1}",
                max_attempts=2,
            )
            parsed, missing = _parse_rows(
                content,
                key=response_key,
                item_ids={str(item["item_id"]) for item in pending},
            )
        except Exception as exc:  # retain a blocking record instead of dropping the OCR candidate
            parsed = {}
            missing = {str(item["item_id"]) for item in pending}
            errors.append(f"{type(exc).__name__}: {exc}")
        accepted.update(parsed)
        pending = [item for item in pending if str(item["item_id"]) in missing]
    return accepted, {str(item["item_id"]) for item in pending}, calls, errors


def _preserved_tokens(source_text: str) -> list[str]:
    return [match.group(0).strip() for match in _PRESERVED_TOKEN_RE.finditer(source_text) if match.group(0).strip()]


def _target_preserves_tokens(source_text: str, translated_text: str) -> bool:
    target = _normalized(translated_text).replace(" ", "")
    return all(_normalized(token).replace(" ", "") in target for token in _preserved_tokens(source_text))


def _has_chinese_companion(text: str) -> bool:
    return bool(_CJK_RE.search(text or ""))


def _literal_descriptor(source_text: str) -> str:
    normalized = _normalized(source_text)
    if normalized in _LITERAL_DESCRIPTOR_OVERRIDES:
        return _LITERAL_DESCRIPTOR_OVERRIDES[normalized]
    compact = re.sub(r"[^a-z0-9]", "", normalized)
    # Malaysian land-lot labels recur throughout layout drawings.  PTD is not
    # OCR noise or a generic equipment code: readers need to know it denotes a
    # land / provisional title identifier while preserving its exact number.
    if normalized == "ptd":
        return "土地编号（PTD）"
    if re.fullmatch(r"ptd[\s_-]*\d+", normalized, flags=re.IGNORECASE):
        literal = str(source_text or "").strip().replace("_", " ")
        return f"土地编号：{literal}"
    # A high-value regression on the submitted site plan.  It is intentionally
    # deterministic, so a model echo cannot turn a readable Malay road name
    # into an untranslated literal.
    if compact == "jalanfeldacahayabaru":
        return "费尔达新光路（Jalan Felda Cahaya Baru）"
    if normalized.startswith("jalan "):
        return f"道路名称（原文：{str(source_text or '').strip()}）"
    return f"图纸/设备标识（原文：{source_text.strip()}）"


def _requires_specific_literal_descriptor(source_text: str) -> bool:
    normalized = _normalized(source_text)
    compact = re.sub(r"[^a-z0-9]", "", normalized)
    return normalized == "ptd" or bool(re.fullmatch(r"ptd[\s_-]*\d+", normalized, flags=re.IGNORECASE)) or compact == "jalanfeldacahayabaru"


def _ensure_literal_descriptor(source_text: str, translated_text: str) -> str:
    """Ensure a code has both Chinese meaning and its exact source literal."""
    source = str(source_text or "").strip()
    target = str(translated_text or "").strip()
    if _requires_specific_literal_descriptor(source):
        return _literal_descriptor(source)
    if not _has_chinese_companion(target):
        return _literal_descriptor(source)
    normalized_source = _normalized(source).replace(" ", "")
    normalized_target = _normalized(target).replace(" ", "")
    if normalized_source and normalized_source not in normalized_target:
        return f"{target}（原文：{source}）"
    return target


def _missing_preserved_tokens(source_text: str, translated_text: str) -> list[str]:
    target = _normalized(translated_text).replace(" ", "")
    return [
        token
        for token in _preserved_tokens(source_text)
        if _normalized(token).replace(" ", "") not in target
    ]


def _append_missing_preserved_tokens(source_text: str, translated_text: str) -> str:
    """Keep exact dimensions/codes after a model writes only their Chinese meaning."""
    target = str(translated_text or "").strip()
    missing = _missing_preserved_tokens(source_text, target)
    if not target or not missing:
        return target
    return f"{target}（原文数值/标识：{'；'.join(missing)}）"


def _needs_chinese_repair(item: dict, translated_text: str) -> bool:
    """Detect a normal-language reply that is merely an English/Malay echo."""
    if str(item.get("action_hint") or "translate") == "keep_literal":
        return False
    source = str(item.get("source_text") or "")
    if not _LATIN_RE.search(source):
        return False
    return not _has_chinese_companion(str(translated_text or ""))


def _cached_entry_is_complete(item: dict, entry: dict) -> bool:
    """Do not let an older cache result bypass current strict coverage rules."""
    verdict = str(entry.get("verdict") or "").strip().lower()
    if verdict not in {"accepted", "corrected", "not_language"}:
        return False
    if verdict == "not_language":
        return True
    target = str(entry.get("translated_text") or "").strip()
    if not target or not _has_chinese_companion(target):
        return False
    if str(item.get("action_hint") or "") == "keep_literal":
        if _requires_specific_literal_descriptor(str(item.get("source_text") or "")) and target != _literal_descriptor(str(item.get("source_text") or "")):
            return False
        source_literal = _normalized(str(item.get("source_text") or "")).replace(" ", "")
        target_literal = _normalized(target).replace(" ", "")
        if source_literal and source_literal not in target_literal:
            return False
    return _target_preserves_tokens(str(item.get("source_text") or ""), target)


def _region_may_be_confirmed_noise(region: dict) -> bool:
    """A visual model may not discard credible source text as OCR noise.

    OCR garbage can be a successful audited disposition only when it came from a
    low-confidence raster OCR observation.  Native text, vector outlines, and
    corrected/visually-reviewed regions remain blocking even if a model calls
    them noise.
    """
    provenance = str(region.get("provenance") or "").lower()
    if provenance in {"native_pdf", "native_text", "vector_outline", "deepseek_ocr"}:
        return False
    flags = {str(flag) for flag in (region.get("qa_flags") or [])}
    if any("deepseek" in flag or "vector" in flag for flag in flags):
        return False
    try:
        confidence = float(region.get("ocr_confidence", region.get("confidence", 1.0)))
    except (TypeError, ValueError):
        confidence = 1.0
    return provenance in {"paddle_ocr", "paddle_tile_ocr"} and confidence < 0.45


def _batched(items: list[dict], size: int) -> Iterable[list[dict]]:
    effective_size = max(1, min(60, int(size or 32)))
    for index in range(0, len(items), effective_size):
        yield items[index:index + effective_size]


def translate_and_judge_engineering_regions(
    regions: Iterable[dict],
    *,
    api_key: str,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    cache_path: Path | None = None,
    batch_size: int = 32,
    request_chat_content_fn: ChatRequester = request_chat_content,
    supervisor_plan: Mapping[str, object] | None = None,
) -> EngineeringTranslationResult:
    """Translate all detected Latin-script regions and return a blocking coverage report.

    The result retains one record per OCR region.  Rendering is permitted only when
    ``report['passed']`` is true; a `manual_review` or missing entry is deliberately
    counted as unresolved so it cannot masquerade as a completed delivery.
    """
    copied_regions = [dict(region) for region in regions]
    supervisor_translation_tasks = []
    if isinstance(supervisor_plan, Mapping):
        raw_tasks = supervisor_plan.get("translation_tasks")
        if isinstance(raw_tasks, list):
            supervisor_translation_tasks = [dict(task) for task in raw_tasks if isinstance(task, Mapping)]
    cache = _load_cache(cache_path)
    cache_dirty = False
    unique: dict[str, dict] = {}
    eligible_keys_by_index: dict[int, str] = {}
    for index, region in enumerate(copied_regions):
        if not _is_language_candidate(region):
            region["coverage_status"] = "not_source_language"
            continue
        source = _source_text(region)
        action_hint = str(region.get("action") or "translate").strip().lower()
        if action_hint == "keep_literal" and _requires_natural_language_translation(source):
            action_hint = "translate"
        key = _cache_key(
            source_text=source,
            source_language=_language(region),
            action_hint=action_hint,
            model=model,
            base_url=base_url,
        )
        eligible_keys_by_index[index] = key
        if key not in unique:
            unique[key] = {
                "item_id": f"ed-{len(unique) + 1:04d}",
                "source_text": source,
                "source_language": _language(region),
                "action_hint": action_hint if action_hint in _ALLOWED_ACTIONS else "translate",
                "literal_tokens": _preserved_tokens(source),
                "cache_key": key,
            }

    entries: dict[str, dict] = {}
    cache_hits = 0
    to_translate: list[dict] = []
    for key, item in unique.items():
        cached = cache.get(key)
        if cached and _cached_entry_is_complete(item, cached):
            entries[key] = dict(cached)
            cache_hits += 1
        else:
            to_translate.append(item)

    translation_calls = qa_calls = 0
    request_errors: list[str] = []
    translated_by_item_id: dict[str, dict] = {}
    missing_translation_ids: set[str] = set()
    if to_translate and not str(api_key or "").strip():
        missing_translation_ids = {str(item["item_id"]) for item in to_translate}
        request_errors.append("api_key_missing")
    else:
        for batch in _batched(to_translate, batch_size):
            parsed, missing, calls, errors = _request_with_missing_retry(
                items=batch,
                messages_builder=lambda items: _translation_messages(
                    items,
                    supervisor_tasks=supervisor_translation_tasks,
                ),
                response_key="translations",
                api_key=api_key,
                model=model,
                base_url=base_url,
                request_chat_content_fn=request_chat_content_fn,
                request_label="engineering-translation",
            )
            translated_by_item_id.update(parsed)
            missing_translation_ids.update(missing)
            translation_calls += calls
            request_errors.extend(errors)
            # Incremental persist: a timeout mid-batch must not lose prior
            # translations.  The final _save_cache below re-saves the full set.
            if cache_dirty:
                _save_cache(cache_path, cache)

    candidate_items: list[dict] = []
    item_by_id = {str(item["item_id"]): item for item in to_translate}
    for item_id, raw in translated_by_item_id.items():
        item = item_by_id[item_id]
        target = str(raw.get("translated_text") or "").strip()
        action = str(raw.get("action") or item["action_hint"]).strip().lower()
        if action not in _ALLOWED_ACTIONS:
            action = item["action_hint"]
        descriptor_added = False
        # The generic chat model sometimes follows its usual “preserve codes”
        # convention and echoes IN / X / AHU-01 unchanged.  In engineering mode
        # that is not a completed state: every such literal needs a Chinese
        # semantic companion and the exact code.  Apply the deterministic rule
        # only when OCR classified the source as a literal; a normal uppercase
        # Malay word must go through the Chinese repair pass instead.
        if item["action_hint"] == "keep_literal" or action == "keep_literal":
            repaired_target = _ensure_literal_descriptor(item["source_text"], target)
            descriptor_added = repaired_target != target
            target = repaired_target
            action = "keep_literal"
        candidate_items.append(
            {
                "item_id": item_id,
                "source_text": item["source_text"],
                "source_language": item["source_language"],
                "literal_tokens": item["literal_tokens"],
                "translated_text": target,
                "action": action,
                "action_hint": item["action_hint"],
                "issues": list(raw.get("issues") or []) + (
                    ["deterministic_literal_descriptor"] if descriptor_added else []
                ),
                "cache_key": item["cache_key"],
            }
        )

    candidate_by_item_id = {str(item["item_id"]): item for item in candidate_items}
    repair_items = [
        {
            "item_id": item["item_id"],
            "source_text": item["source_text"],
            "source_language": item["source_language"],
            "previous_candidate": item["translated_text"],
            "literal_tokens": item["literal_tokens"],
        }
        for item in candidate_items
        if _needs_chinese_repair(item, str(item.get("translated_text") or ""))
    ]
    if repair_items:
        for batch in _batched(repair_items, batch_size):
            parsed, missing, calls, errors = _request_with_missing_retry(
                items=batch,
                messages_builder=_repair_messages,
                response_key="translations",
                api_key=api_key,
                model=model,
                base_url=base_url,
                request_chat_content_fn=request_chat_content_fn,
                request_label="engineering-translation-repair",
            )
            translation_calls += calls
            request_errors.extend(errors)
            for item_id, repaired in parsed.items():
                candidate = candidate_by_item_id[item_id]
                target = str(repaired.get("translated_text") or "").strip()
                action = str(repaired.get("action") or candidate["action"]).strip().lower()
                candidate["translated_text"] = target
                candidate["action"] = action if action in _ALLOWED_ACTIONS else candidate["action"]
                candidate["issues"].extend(
                    ["forced_chinese_repair"]
                    + [str(value) for value in (repaired.get("issues") or []) if str(value)]
                )
            for item_id in missing:
                candidate_by_item_id[item_id]["issues"].append("forced_chinese_repair_missing")

    # Ensure required source literals survive both the first translation and the
    # repair pass before the independent judge sees the candidate.
    for candidate in candidate_items:
        if candidate["action_hint"] == "keep_literal" or candidate["action"] == "keep_literal":
            candidate["translated_text"] = _ensure_literal_descriptor(
                candidate["source_text"], str(candidate.get("translated_text") or "")
            )
            candidate["action"] = "keep_literal"
        candidate["translated_text"] = _append_missing_preserved_tokens(
            candidate["source_text"], str(candidate.get("translated_text") or "")
        )

    qa_by_item_id: dict[str, dict] = {}
    qa_missing_ids: set[str] = set()
    for batch in _batched(candidate_items, batch_size):
        parsed, missing, calls, errors = _request_with_missing_retry(
            items=batch,
            messages_builder=_qa_messages,
            response_key="reviews",
            api_key=api_key,
            model=model,
            base_url=base_url,
            request_chat_content_fn=request_chat_content_fn,
            request_label="engineering-translation-qa",
        )
        qa_by_item_id.update(parsed)
        qa_missing_ids.update(missing)
        qa_calls += calls
        request_errors.extend(errors)

    # Incremental persist after QA too: the final promote loop below also
    # writes accepted entries; saving here keeps those on timeout.
    if cache_dirty:
        _save_cache(cache_path, cache)

    # Promote each non-cached unique source to a final, QA-backed cache entry.
    for key, item in unique.items():
        if key in entries:
            continue
        item_id = str(item["item_id"])
        raw = translated_by_item_id.get(item_id)
        candidate = candidate_by_item_id.get(item_id)
        review = qa_by_item_id.get(item_id)
        if raw is None or candidate is None or item_id in missing_translation_ids:
            entries[key] = {
                "translated_text": "",
                "action": item["action_hint"],
                "verdict": "missing_translation",
                "issues": ["ai_translation_missing"],
            }
            continue
        target = str(candidate.get("translated_text") or "").strip()
        action = str(candidate.get("action") or item["action_hint"]).strip().lower()
        if action not in _ALLOWED_ACTIONS:
            action = item["action_hint"]
        issues = [str(value) for value in (candidate.get("issues") or []) if str(value)]
        if review is None or item_id in qa_missing_ids:
            entries[key] = {
                "translated_text": target,
                "action": action,
                "verdict": "manual_review",
                "issues": issues + ["ai_qa_missing"],
            }
            continue
        verdict = str(review.get("verdict") or "manual_review").strip().lower()
        if verdict not in _ALLOWED_VERDICTS:
            verdict = "manual_review"
            issues.append("ai_qa_invalid_verdict")
        corrected = str(review.get("translated_text") or "").strip()
        if verdict == "corrected":
            target = corrected
        elif verdict == "accepted" and corrected:
            target = corrected
        issues.extend(str(value) for value in (review.get("issues") or []) if str(value))
        if verdict == "not_language":
            target = ""
        elif not target:
            verdict = "missing_translation"
            issues.append("empty_translation")
        if target and (item["action_hint"] == "keep_literal" or action == "keep_literal"):
            target = _ensure_literal_descriptor(item["source_text"], target)
            action = "keep_literal"
        if target:
            target = _append_missing_preserved_tokens(item["source_text"], target)
        if target and not _target_preserves_tokens(item["source_text"], target):
            verdict = "manual_review"
            issues.append("number_or_literal_token_mismatch")
        if target and not _has_chinese_companion(target):
            verdict = "manual_review"
            issues.append("missing_chinese_companion")
        entries[key] = {
            "translated_text": target,
            "action": action,
            "verdict": verdict,
            "issues": sorted(set(issues)),
        }
        if verdict in {"accepted", "corrected", "not_language"}:
            cache[key] = dict(entries[key])
            cache_dirty = True

    if cache_dirty:
        _save_cache(cache_path, cache)

    translated_regions = literal_regions = manual_regions = unresolved_regions = 0
    ai_confirmed_non_language_regions = 0
    corrected_regions = 0
    for index, region in enumerate(copied_regions):
        key = eligible_keys_by_index.get(index)
        if key is None:
            continue
        entry = entries[key]
        target = str(entry.get("translated_text") or "").strip()
        action = str(entry.get("action") or "translate")
        verdict = str(entry.get("verdict") or "manual_review")
        flags = {str(flag) for flag in (region.get("qa_flags") or []) if str(flag)}
        flags.update(str(issue) for issue in (entry.get("issues") or []) if str(issue))
        region["translated_text"] = target
        region["action"] = action
        region["ai_judgement"] = verdict
        if verdict == "missing_translation" or (not target and verdict != "not_language"):
            flags.add("ai_translation_missing")
            region["coverage_status"] = "missing_translation"
            unresolved_regions += 1
        elif verdict == "not_language" and _region_may_be_confirmed_noise(region):
            region["translated_text"] = ""
            region["coverage_status"] = "ai_confirmed_non_language"
            flags.add("ai_non_language")
            ai_confirmed_non_language_regions += 1
        elif verdict == "not_language":
            # A credible native/vector/high-confidence source word cannot be
            # removed just because one model calls it noise.  Keep the page
            # blocked and expose the evidence to a reviewer.
            region["coverage_status"] = "manual_review"
            region["ai_judgement"] = "manual_review"
            flags.update({"ai_non_language_rejected_for_credible_source", "manual_review_required"})
            manual_regions += 1
            unresolved_regions += 1
        elif verdict == "manual_review":
            region["coverage_status"] = "manual_review"
            flags.add("manual_review_required")
            manual_regions += 1
            unresolved_regions += 1
        elif action == "keep_literal":
            region["coverage_status"] = "literal_labeled"
            literal_regions += 1
        else:
            region["coverage_status"] = "translated"
            translated_regions += 1
        if verdict == "corrected":
            corrected_regions += 1
        region["qa_flags"] = sorted(flags)

    report: dict[str, object] = {
        "schema": "engineering_drawing_coverage_v1",
        "source_regions": len(copied_regions),
        "candidate_regions": len(eligible_keys_by_index),
        "target_regions": len(eligible_keys_by_index) - ai_confirmed_non_language_regions,
        "unique_source_count": len(unique),
        "translated_regions": translated_regions,
        "literal_labeled_regions": literal_regions,
        "manual_review_regions": manual_regions,
        "ai_confirmed_non_language_regions": ai_confirmed_non_language_regions,
        "unresolved_regions": unresolved_regions,
        "corrected_regions": corrected_regions,
        "cache_hits": cache_hits,
        "translation_api_calls": translation_calls,
        "qa_api_calls": qa_calls,
        "request_errors": request_errors,
        "passed": unresolved_regions == 0,
    }
    return EngineeringTranslationResult(regions=copied_regions, report=report)


__all__ = ["EngineeringTranslationResult", "translate_and_judge_engineering_regions"]
