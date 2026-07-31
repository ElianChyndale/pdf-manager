from __future__ import annotations

import json
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Mapping


KNOWLEDGE_SCHEMA = "engineering-drawing-semantic-knowledge-v1"
DEFAULT_KNOWLEDGE_PATH = (
    Path(__file__).resolve().parent
    / "knowledge"
    / "engineering_semantics_zh-CN.json"
)
DEFAULT_EXTENSION_PATH = (
    Path(__file__).resolve().parent
    / "knowledge"
    / "engineering_semantics_multidiscipline_zh-CN.json"
)
EXTENSION_SCHEMA = "engineering-drawing-semantic-extension-v1"


def _merge_dict(base: dict, extension: Mapping[str, object]) -> dict:
    merged = deepcopy(base)
    for key, value in extension.items():
        if key in {"schema", "locale", "purpose"}:
            continue
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = _merge_dict(dict(merged[key]), value)
        elif isinstance(value, list) and isinstance(merged.get(key), list):
            merged[key] = [*merged[key], *deepcopy(value)]
        else:
            merged[key] = deepcopy(value)
    return merged


@lru_cache(maxsize=4)
def load_engineering_semantic_knowledge(
    path: str | Path = DEFAULT_KNOWLEDGE_PATH,
    extension_path: str | Path | None = DEFAULT_EXTENSION_PATH,
) -> dict:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema") != KNOWLEDGE_SCHEMA:
        raise ValueError(f"engineering semantic knowledge must use {KNOWLEDGE_SCHEMA}")
    for key in (
        "drawing_families",
        "semantic_classes",
        "terminology",
        "instance_rules",
        "placement_rules",
    ):
        if key not in payload:
            raise ValueError(f"engineering semantic knowledge requires {key}")
    if extension_path is not None and Path(extension_path).exists():
        extension = json.loads(Path(extension_path).read_text(encoding="utf-8"))
        if extension.get("schema") != EXTENSION_SCHEMA:
            raise ValueError(
                f"engineering semantic extension must use {EXTENSION_SCHEMA}"
            )
        payload = _merge_dict(payload, extension)
    return payload


def supervisor_knowledge_context(
    *,
    page_type: str = "",
    path: str | Path = DEFAULT_KNOWLEDGE_PATH,
    extension_path: str | Path | None = DEFAULT_EXTENSION_PATH,
) -> dict:
    knowledge = load_engineering_semantic_knowledge(path, extension_path)
    selected_family: Mapping[str, object] | None = None
    normalized_type = str(page_type or "").casefold()
    for name, family in knowledge["drawing_families"].items():
        searchable = " ".join(
            [name, *[str(item) for item in family.get("page_types", [])]]
        ).casefold()
        if normalized_type and any(token in searchable for token in normalized_type.split("_")):
            selected_family = family
            break
    return {
        "schema": knowledge["schema"],
        "locale": knowledge["locale"],
        "page_type": page_type,
        "family_guidance": deepcopy(dict(selected_family or {})),
        "semantic_classes": deepcopy(knowledge["semantic_classes"]),
        "terminology": deepcopy(knowledge["terminology"]),
        "instance_rules": deepcopy(knowledge["instance_rules"]),
        "placement_rules": deepcopy(knowledge["placement_rules"]),
        "relation_types": deepcopy(knowledge.get("relation_types", {})),
        "supervisor_rules": deepcopy(knowledge.get("supervisor_rules", [])),
        "typography_rules": deepcopy(knowledge.get("typography_rules", [])),
        "source_references": deepcopy(knowledge.get("source_references", [])),
        "electrical_parameter_templates": deepcopy(
            knowledge.get("electrical_parameter_templates", {})
        ),
        "electrical_code_policy": deepcopy(
            knowledge.get("electrical_code_policy", {})
        ),
        "repetition_strategy": deepcopy(knowledge.get("repetition_strategy", {})),
        "reverse_reading_test": deepcopy(
            knowledge.get("reverse_reading_test", {})
        ),
    }


__all__ = [
    "DEFAULT_KNOWLEDGE_PATH",
    "DEFAULT_EXTENSION_PATH",
    "EXTENSION_SCHEMA",
    "KNOWLEDGE_SCHEMA",
    "load_engineering_semantic_knowledge",
    "supervisor_knowledge_context",
]
