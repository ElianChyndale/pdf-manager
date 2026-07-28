import json

from services.engineering_drawing.benchmark.prelabel import (
    build_prelabel_request,
    parse_prelabel_response,
    parse_visual_review_response,
    request_prelabels,
    request_visual_review,
    select_adjudication_queue,
)


def test_prelabel_keeps_paragraph_together_and_ids_separate():
    content = json.dumps(
        {
            "blocks": [
                {
                    "block_id": "core-03-b001",
                    "member_ids": ["ocr-1", "ocr-2", "ocr-3"],
                    "source_text": "ROOF SYSTEM - CUT TO LENGTH KLIPLOK OPTIMA",
                    "source_language": "en",
                    "source_bbox": [10, 10, 250, 60],
                    "rotation": 0,
                    "reading_order": 1,
                    "merge_decision": "merge_paragraph",
                    "gold_translation": "屋面系统——按长度定制 KLIPLOK OPTIMA",
                    "literal_tokens": ["KLIPLOK OPTIMA"],
                    "allowed_regions": [[10, 70, 250, 105]],
                    "forbidden_zones": [[10, 10, 250, 60]],
                    "font_size_range": [3.2, 6.5],
                    "leader": {"allowed": False, "required": False},
                    "confidence": 0.92,
                    "risk_flags": [],
                },
                {
                    "block_id": "core-03-b002",
                    "member_ids": ["ocr-4"],
                    "source_text": "KL98",
                    "source_language": "en",
                    "source_bbox": [260, 10, 290, 25],
                    "rotation": 0,
                    "reading_order": 2,
                    "merge_decision": "separate_identifier",
                    "gold_translation": "KL98 型号",
                    "literal_tokens": ["KL98"],
                    "allowed_regions": [[260, 30, 295, 45]],
                    "forbidden_zones": [[260, 10, 290, 25]],
                    "font_size_range": [3.2, 5.8],
                    "leader": {"allowed": True, "required": False},
                    "confidence": 0.72,
                    "risk_flags": ["identifier_boundary"],
                },
            ]
        }
    )
    prelabel = parse_prelabel_response(content, "core-03")
    queue = select_adjudication_queue(prelabel)
    assert len(prelabel["blocks"][0]["member_ids"]) == 3
    assert [item["block_id"] for item in queue] == ["core-03-b002"]


def test_prelabel_rejects_missing_source_literal():
    content = json.dumps(
        {
            "blocks": [
                {
                    "block_id": "core-03-b001",
                    "member_ids": ["ocr-1"],
                    "source_text": "0.48MM BMT",
                    "source_language": "en",
                    "source_bbox": [1, 1, 30, 10],
                    "rotation": 0,
                    "reading_order": 1,
                    "merge_decision": "single",
                    "gold_translation": "基板厚度",
                    "literal_tokens": ["0.48MM BMT"],
                    "allowed_regions": [[35, 1, 80, 15]],
                    "forbidden_zones": [[1, 1, 30, 10]],
                    "font_size_range": [3.2, 5.8],
                    "leader": {"allowed": True, "required": False},
                    "confidence": 0.9,
                    "risk_flags": [],
                }
            ]
        }
    )
    try:
        parse_prelabel_response(content, "core-03")
    except ValueError as exc:
        assert "literal token" in str(exc)
    else:
        raise AssertionError("missing literal token must be rejected")


def test_visual_review_has_bounded_scores_and_auditable_findings():
    result = parse_visual_review_response(
        json.dumps(
            {
                "layout_association": 17,
                "page_readability": 12,
                "findings": [
                    {
                        "code": "leader_route",
                        "region_id": "core-03-b002",
                        "reason": "引线绕开原文且关联明确",
                    }
                ],
            }
        ),
        sample_id="core-03",
        model="gpt-5.6-sol",
    )
    assert result["layout_association"] == 17
    assert result["page_readability"] == 12
    assert result["findings"][0]["reason"]


def test_request_prelabels_uses_injected_request_function_and_preserves_page():
    calls = []

    def fake_request(**kwargs):
        calls.append(kwargs)
        return json.dumps({"blocks": []})

    result = request_prelabels(
        sample_id="core-03",
        image_data_url="data:image/png;base64,source",
        regions=[{"id": "ocr-1", "text": "NOTE"}],
        page={"width": 100, "height": 200},
        api_key="test-key",
        model="test-model",
        base_url="https://example.test/v1",
        request_fn=fake_request,
    )

    assert result["page"] == {"width": 100, "height": 200}
    assert calls[0]["request_label"] == "engineering-benchmark-prelabel"
    assert calls[0]["messages"] == build_prelabel_request(
        sample_id="core-03",
        image_data_url="data:image/png;base64,source",
        regions=[{"id": "ocr-1", "text": "NOTE"}],
    )


def test_request_visual_review_compares_two_images_with_injected_request_function():
    calls = []

    def fake_request(**kwargs):
        calls.append(kwargs)
        return json.dumps(
            {"layout_association": 20, "page_readability": 15, "findings": []}
        )

    result = request_visual_review(
        sample_id="core-03",
        source_image_data_url="data:image/png;base64,source",
        candidate_image_data_url="data:image/png;base64,candidate",
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
    assert calls[0]["request_label"] == "engineering-benchmark-visual-review"
    assert image_urls == [
        "data:image/png;base64,source",
        "data:image/png;base64,candidate",
    ]
    assert result["model"] == "test-model"
