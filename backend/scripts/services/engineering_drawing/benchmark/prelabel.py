from __future__ import annotations

import json
from typing import Callable

from services.translation.llm.shared.response_parsing import extract_json_text


PRELABEL_SCHEMA = "engineering-drawing-prelabel-v1"
PRELABEL_PROMPT_VERSION = "2026-07-benchmark-block-v1"


def build_prelabel_request(
    *,
    sample_id: str,
    image_data_url: str,
    regions: list[dict],
) -> list[dict]:
    rules = (
        "Group complete notes and specifications by meaning, not individual words. "
        "Keep equipment IDs, table cells, legend entries, dimensions, and title rows separate. "
        "Preserve all numbers, units, models, IDs, and source rotation. "
        "Propose allowed whitespace regions and forbidden source/dimension/line zones. "
        "Prefer right, then below, then above; use an orthogonal leader only for dense CAD labels."
    )
    return [
        {"role": "system", "content": rules},
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {"sample_id": sample_id, "regions": regions}, ensure_ascii=False
                    ),
                },
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ],
        },
    ]


def parse_prelabel_response(content: str, sample_id: str) -> dict:
    payload = json.loads(extract_json_text(content))
    blocks = []
    seen = set()
    for raw in payload.get("blocks", []):
        item = dict(raw)
        block_id = str(item.get("block_id") or "")
        if not block_id.startswith(f"{sample_id}-b") or block_id in seen:
            raise ValueError("block_id must be stable and unique")
        seen.add(block_id)
        target = str(item.get("gold_translation") or "")
        for token in item.get("literal_tokens", []):
            if str(token).replace(" ", "") not in target.replace(" ", ""):
                raise ValueError(f"literal token missing from translation: {token}")
        confidence = float(item.get("confidence", 0))
        if not 0 <= confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        blocks.append(item)
    return {
        "schema": PRELABEL_SCHEMA,
        "prompt_version": PRELABEL_PROMPT_VERSION,
        "sample_id": sample_id,
        "status": "prelabeled",
        "blocks": blocks,
    }


def select_adjudication_queue(prelabel: dict) -> list[dict]:
    high_value_flags = {
        "identifier_boundary",
        "number_or_unit",
        "unreadable",
        "layout_collision",
        "leader_route",
        "table_boundary",
    }
    return [
        block
        for block in prelabel.get("blocks", [])
        if float(block.get("confidence", 0)) < 0.8
        or bool(high_value_flags.intersection(block.get("risk_flags", [])))
    ]


def request_prelabels(
    *,
    sample_id: str,
    image_data_url: str,
    regions: list[dict],
    page: dict[str, float | int],
    api_key: str,
    model: str,
    base_url: str,
    request_fn: Callable[..., str],
) -> dict:
    content = request_fn(
        api_key=api_key,
        model=model,
        base_url=base_url,
        messages=build_prelabel_request(
            sample_id=sample_id,
            image_data_url=image_data_url,
            regions=regions,
        ),
        request_label="engineering-benchmark-prelabel",
    )
    result = parse_prelabel_response(content, sample_id)
    result["page"] = dict(page)
    return result


def parse_visual_review_response(content: str, sample_id: str, model: str) -> dict:
    payload = json.loads(extract_json_text(content))
    layout = float(payload.get("layout_association", -1))
    readability = float(payload.get("page_readability", -1))
    if not 0 <= layout <= 20 or not 0 <= readability <= 15:
        raise ValueError("visual review scores are outside their allowed ranges")
    findings = []
    for raw in payload.get("findings", []):
        item = dict(raw)
        if not str(item.get("code") or "") or not str(item.get("reason") or ""):
            raise ValueError("every visual finding requires code and reason")
        findings.append(item)
    return {
        "schema": "engineering-drawing-visual-review-v1",
        "prompt_version": "2026-07-benchmark-visual-v1",
        "sample_id": sample_id,
        "model": model,
        "layout_association": layout,
        "page_readability": readability,
        "findings": findings,
    }


def request_visual_review(
    *,
    sample_id: str,
    source_image_data_url: str,
    candidate_image_data_url: str,
    api_key: str,
    model: str,
    base_url: str,
    request_fn: Callable[..., str],
) -> dict:
    messages = [
        {
            "role": "system",
            "content": (
                "Compare the source and bilingual candidate as an engineering drawing. "
                "Score layout association from 0 to 20 and whole-page readability from 0 to 15. "
                "Check missing translations, semantic fragmentation, source overlap, unsafe font size, "
                "unclear source-target association, and leader obstruction. Return JSON only."
            ),
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": json.dumps({"sample_id": sample_id})},
                {"type": "image_url", "image_url": {"url": source_image_data_url}},
                {
                    "type": "image_url",
                    "image_url": {"url": candidate_image_data_url},
                },
            ],
        },
    ]
    content = request_fn(
        api_key=api_key,
        model=model,
        base_url=base_url,
        messages=messages,
        request_label="engineering-benchmark-visual-review",
    )
    return parse_visual_review_response(content, sample_id, model)
