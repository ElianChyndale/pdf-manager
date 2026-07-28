import json

import pytest

from services.engineering_drawing.benchmark.prelabel import (
    build_prelabel_request,
    parse_prelabel_response,
    parse_visual_review_response,
    request_prelabels,
    request_visual_review,
    select_adjudication_queue,
)


PAGE = {"width": 400, "height": 300, "rotation": 0}
REGIONS = [
    {
        "id": "ocr-1",
        "text": "KL98 0.48MM BMT",
        "bbox": [10, 10, 100, 30],
        "rotation": 0,
    },
    {
        "id": "ocr-2",
        "text": "ROOF SYSTEM",
        "bbox": [110, 10, 200, 30],
        "rotation": 0,
    },
    {
        "id": "ocr-3",
        "text": "KL98 0.48MM BMT",
        "bbox": [260, 10, 350, 30],
        "rotation": 0,
    },
]


def _block(block_id="core-03-b001", member_ids=None):
    return {
        "block_id": block_id,
        "member_ids": ["ocr-1"] if member_ids is None else member_ids,
        "source_text": "KL98 0.48MM BMT",
        "source_language": "en",
        "source_bbox": [10, 10, 100, 30],
        "rotation": 0,
        "reading_order": 1,
        "merge_decision": "single",
        "gold_translation": "KL98 型号，0.48MM BMT 基板厚度",
        "literal_tokens": ["KL98", "0.48MM BMT"],
        "allowed_regions": [[110, 40, 250, 70]],
        "forbidden_zones": [[10, 10, 100, 30]],
        "font_size_range": [3.2, 5.8],
        "leader": {
            "allowed": True,
            "required": False,
            "color": "dark_blue",
            "width_points": 0.32,
            "route": "orthogonal",
            "arrow": False,
        },
        "confidence": 0.9,
        "risk_flags": [],
    }


def _content(*blocks):
    return json.dumps({"blocks": list(blocks)})


def _parse(content, **kwargs):
    return parse_prelabel_response(
        content,
        "core-03",
        regions=REGIONS,
        page=PAGE,
        **kwargs,
    )


def test_prelabel_keeps_paragraph_together_and_ids_separate():
    paragraph = _block("core-03-b001", ["ocr-1", "ocr-2"])
    paragraph["source_text"] = "KL98 0.48MM BMT ROOF SYSTEM"
    paragraph["source_bbox"] = [10, 10, 200, 30]
    paragraph["merge_decision"] = "merge_paragraph"
    separate_id = _block("core-03-b002", ["ocr-3"])
    separate_id["source_bbox"] = [260, 10, 350, 30]
    separate_id["merge_decision"] = "separate_identifier"
    separate_id["confidence"] = 0.72
    separate_id["risk_flags"] = ["identifier_boundary"]

    prelabel = _parse(_content(paragraph, separate_id))
    queue = select_adjudication_queue(prelabel)

    assert len(prelabel["blocks"][0]["member_ids"]) == 2
    assert [item["block_id"] for item in queue] == ["core-03-b002"]


@pytest.mark.parametrize("content", ["[]", "{}", '{"blocks": []}', '{"blocks": "bad"}'])
def test_prelabel_requires_a_json_object_with_nonempty_blocks(content):
    with pytest.raises(ValueError):
        _parse(content)


@pytest.mark.parametrize(
    "field",
    [
        "block_id",
        "member_ids",
        "source_text",
        "source_language",
        "source_bbox",
        "rotation",
        "reading_order",
        "merge_decision",
        "gold_translation",
        "literal_tokens",
        "allowed_regions",
        "forbidden_zones",
        "font_size_range",
        "leader",
        "confidence",
        "risk_flags",
    ],
)
def test_prelabel_rejects_missing_required_block_fields(field):
    block = _block()
    del block[field]

    with pytest.raises(ValueError):
        _parse(_content(block))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda block: block.update(block_id=1),
        lambda block: block.update(member_ids="ocr-1"),
        lambda block: block.update(source_text=[]),
        lambda block: block.update(source_language=[]),
        lambda block: block.update(source_bbox="bad"),
        lambda block: block.update(rotation=0.0),
        lambda block: block.update(reading_order=True),
        lambda block: block.update(merge_decision=[]),
        lambda block: block.update(gold_translation="KL98 0.48MM BMT"),
        lambda block: block.update(literal_tokens="KL98"),
        lambda block: block.update(allowed_regions="bad"),
        lambda block: block.update(forbidden_zones="bad"),
        lambda block: block.update(font_size_range="bad"),
    ],
)
def test_prelabel_rejects_malformed_required_block_field_types(mutate):
    block = _block()
    mutate(block)

    with pytest.raises(ValueError):
        _parse(_content(block))


@pytest.mark.parametrize("member_ids", [[], ["ocr-1", "ocr-1"], ["missing"]])
def test_prelabel_rejects_empty_duplicate_or_unknown_members(member_ids):
    with pytest.raises(ValueError):
        _parse(_content(_block(member_ids=member_ids)))


def test_prelabel_rejects_members_reused_across_blocks():
    second = _block("core-03-b002")
    second["source_bbox"] = [10, 10, 100, 30]

    with pytest.raises(ValueError, match="member"):
        _parse(_content(_block(), second))


def test_prelabel_derives_literals_from_member_source_not_model_tokens():
    block = _block()
    block["literal_tokens"] = ["KL98"]
    block["gold_translation"] = "KL98 型号"

    with pytest.raises(ValueError, match="derived literal"):
        _parse(_content(block))


def test_prelabel_derives_standalone_numbers_from_member_source():
    regions = [dict(REGIONS[0], text="KL98 600")]
    block = _block()
    block["source_text"] = "KL98 600"
    block["literal_tokens"] = ["KL98"]
    block["gold_translation"] = "KL98 型号"

    with pytest.raises(ValueError, match="derived literal"):
        parse_prelabel_response(
            _content(block),
            "core-03",
            regions=regions,
            page=PAGE,
        )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda block: block.update(source_bbox=[12, 12, 98, 28]),
        lambda block: block.update(allowed_regions=[[390, 10, 410, 20]]),
        lambda block: block.update(forbidden_zones=[[10, 10, float("inf"), 20]]),
        lambda block: block.update(rotation=90),
    ],
)
def test_prelabel_rejects_inconsistent_or_invalid_geometry_and_rotation(mutate):
    block = _block()
    mutate(block)

    with pytest.raises(ValueError):
        _parse(_content(block))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda block: block.update(font_size_range=[3.1, 5.8]),
        lambda block: block.update(font_size_range=[5.8, 3.2]),
        lambda block: block.update(font_size_range=[3.2, float("nan")]),
        lambda block: block.update(leader={"allowed": True}),
        lambda block: block.update(risk_flags="identifier_boundary"),
        lambda block: block.update(confidence=True),
        lambda block: block.update(confidence="0.9"),
    ],
)
def test_prelabel_rejects_invalid_font_leader_risk_or_confidence_fields(mutate):
    block = _block()
    mutate(block)

    with pytest.raises(ValueError):
        _parse(_content(block))


def test_request_prelabels_uses_deterministic_transport_and_persists_audit_metadata():
    calls = []

    def fake_request(**kwargs):
        calls.append(kwargs)
        return _content(_block())

    result = request_prelabels(
        sample_id="core-03",
        image_data_url="data:image/png;base64,source",
        regions=REGIONS,
        page=PAGE,
        api_key="test-key",
        model="test-model",
        base_url="https://example.test/v1",
        request_fn=fake_request,
    )

    assert result["schema"] == "engineering-drawing-prelabel-v1"
    assert result["prompt_version"] == "2026-07-benchmark-block-v1"
    assert result["model"] == "test-model"
    assert result["page"] == PAGE
    assert calls[0]["temperature"] == 0.0
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert calls[0]["messages"] == build_prelabel_request(
        sample_id="core-03",
        image_data_url="data:image/png;base64,source",
        regions=REGIONS,
    )


def test_high_value_risk_flag_is_queued_even_with_high_confidence():
    block = _block()
    block["risk_flags"] = ["table_boundary"]
    prelabel = _parse(_content(block))

    assert select_adjudication_queue(prelabel) == prelabel["blocks"]


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"layout_association": True, "page_readability": 12, "findings": []},
        {"layout_association": "17", "page_readability": 12, "findings": []},
        {"layout_association": -0.1, "page_readability": 12, "findings": []},
        {"layout_association": 17, "page_readability": 15.1, "findings": []},
        {"layout_association": 17, "page_readability": 12, "findings": {}},
    ],
)
def test_visual_review_rejects_invalid_top_level_scores_and_findings(payload):
    with pytest.raises(ValueError):
        parse_visual_review_response(
            json.dumps(payload),
            sample_id="core-03",
            model="test-model",
            candidate_region_ids=["core-03-b001"],
        )


@pytest.mark.parametrize(
    "finding",
    [
        {"region_id": "core-03-b001", "reason": "reason"},
        {"code": "code", "reason": "reason"},
        {"code": "code", "region_id": "core-03-b001"},
        {"code": "code", "region_id": "unknown", "reason": "reason"},
        {"code": " ", "region_id": "core-03-b001", "reason": "reason"},
    ],
)
def test_visual_review_rejects_missing_or_unknown_auditable_findings(finding):
    with pytest.raises(ValueError):
        parse_visual_review_response(
            json.dumps(
                {"layout_association": 17, "page_readability": 12, "findings": [finding]}
            ),
            sample_id="core-03",
            model="test-model",
            candidate_region_ids=["core-03-b001"],
        )


def test_visual_review_accepts_boundary_scores_and_known_auditable_findings():
    result = parse_visual_review_response(
        json.dumps(
            {
                "layout_association": 20,
                "page_readability": 15,
                "findings": [
                    {
                        "code": "leader_route",
                        "region_id": "core-03-b001",
                        "reason": "引线绕开原文且关联明确",
                    }
                ],
            }
        ),
        sample_id="core-03",
        model="test-model",
        candidate_region_ids=["core-03-b001"],
    )

    assert result["layout_association"] == 20
    assert result["page_readability"] == 15
    assert result["findings"][0]["reason"]


def test_request_visual_review_uses_known_candidate_ids_and_deterministic_transport():
    calls = []

    def fake_request(**kwargs):
        calls.append(kwargs)
        return json.dumps(
            {
                "layout_association": 20,
                "page_readability": 15,
                "findings": [
                    {
                        "code": "leader_route",
                        "region_id": "core-03-b001",
                        "reason": "clear route",
                    }
                ],
            }
        )

    result = request_visual_review(
        sample_id="core-03",
        source_image_data_url="data:image/png;base64,source",
        candidate_image_data_url="data:image/png;base64,candidate",
        candidate_region_ids=["core-03-b001"],
        api_key="test-key",
        model="test-model",
        base_url="https://example.test/v1",
        request_fn=fake_request,
    )

    image_urls = [
        item["image_url"]["url"]
        for item in calls[0]["messages"][1]["content"]
        if item["type"] == "image_url"
    ]
    assert calls[0]["temperature"] == 0.0
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert image_urls == [
        "data:image/png;base64,source",
        "data:image/png;base64,candidate",
    ]
    assert result["model"] == "test-model"
