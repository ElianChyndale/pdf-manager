from __future__ import annotations

import json

from services.engineering_drawing.translation_qa import translate_and_judge_engineering_regions


def _accepted_requester(messages: list[dict[str, str]], **_kwargs: object) -> str:
    payload = json.loads(messages[-1]["content"])
    if payload["stage"] == "engineering_translation":
        translations = []
        for item in payload["items"]:
            source = item["source_text"]
            target = {
                "Distribution Water Pump": "配水泵",
                "AHU-01": "空调处理机编号：AHU-01",
                "DEPOH LORI": "卡车车库",
            }[source]
            translations.append(
                {
                    "item_id": item["item_id"],
                    "translated_text": target,
                    "action": "keep_literal" if source == "AHU-01" else "translate",
                    "issues": [],
                }
            )
        return json.dumps({"translations": translations}, ensure_ascii=False)
    assert payload["stage"] == "engineering_translation_qa"
    return json.dumps(
        {
            "reviews": [
                {
                    "item_id": item["item_id"],
                    "verdict": "accepted",
                    "translated_text": item["translated_text"],
                    "issues": [],
                }
                for item in payload["items"]
            ]
        },
        ensure_ascii=False,
    )


def test_translation_qa_covers_translate_and_literal_regions_and_deduplicates_requests(tmp_path) -> None:
    regions = [
        {
            "region_id": "pump-a",
            "source_text": "Distribution Water Pump",
            "source_language": "en",
            "action": "translate",
            "qa_flags": [],
        },
        {
            "region_id": "pump-b",
            "source_text": "Distribution Water Pump",
            "source_language": "en",
            "action": "translate",
            "qa_flags": [],
        },
        {
            "region_id": "ahu",
            "source_text": "AHU-01",
            "source_language": "en",
            "action": "keep_literal",
            "qa_flags": [],
        },
        {
            "region_id": "depoh",
            "source_text": "DEPOH LORI",
            "source_language": "ms",
            "action": "translate",
            "qa_flags": [],
        },
        {
            "region_id": "chinese-only",
            "source_text": "中文原文",
            "source_language": "zh",
            "action": "review",
            "qa_flags": [],
        },
    ]

    result = translate_and_judge_engineering_regions(
        regions,
        api_key="test-key",
        cache_path=tmp_path / "cache.json",
        request_chat_content_fn=_accepted_requester,
    )

    by_id = {item["region_id"]: item for item in result.regions}
    assert by_id["pump-a"]["translated_text"] == "配水泵"
    assert by_id["pump-b"]["translated_text"] == "配水泵"
    assert by_id["ahu"]["translated_text"] == "空调处理机编号：AHU-01"
    assert by_id["ahu"]["coverage_status"] == "literal_labeled"
    assert by_id["depoh"]["translated_text"] == "卡车车库"
    assert by_id["chinese-only"]["coverage_status"] == "not_source_language"
    assert result.report["unique_source_count"] == 3
    assert result.report["translated_regions"] == 3
    assert result.report["literal_labeled_regions"] == 1
    assert result.report["unresolved_regions"] == 0
    assert result.report["passed"] is True


def test_translation_qa_blocks_rendering_when_model_omits_a_source_region(tmp_path) -> None:
    def incomplete_requester(messages: list[dict[str, str]], **_kwargs: object) -> str:
        payload = json.loads(messages[-1]["content"])
        if payload["stage"] == "engineering_translation":
            matching = [item for item in payload["items"] if item["source_text"] == "Distribution Water Pump"]
            if not matching:
                return json.dumps({"translations": []}, ensure_ascii=False)
            first = matching[0]
            return json.dumps(
                {
                    "translations": [
                        {
                            "item_id": first["item_id"],
                            "translated_text": "配水泵",
                            "action": "translate",
                            "issues": [],
                        }
                    ]
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "reviews": [
                    {
                        "item_id": item["item_id"],
                        "verdict": "accepted",
                        "translated_text": item["translated_text"],
                        "issues": [],
                    }
                    for item in payload["items"]
                ]
            },
            ensure_ascii=False,
        )

    result = translate_and_judge_engineering_regions(
        [
            {
                "region_id": "pump",
                "source_text": "Distribution Water Pump",
                "source_language": "en",
                "action": "translate",
                "qa_flags": [],
            },
            {
                "region_id": "tank",
                "source_text": "Distribution Storage Tank",
                "source_language": "en",
                "action": "translate",
                "qa_flags": [],
            },
        ],
        api_key="test-key",
        cache_path=tmp_path / "cache.json",
        request_chat_content_fn=incomplete_requester,
    )

    by_id = {item["region_id"]: item for item in result.regions}
    assert by_id["pump"]["translated_text"] == "配水泵"
    assert by_id["tank"]["translated_text"] == ""
    assert "ai_translation_missing" in by_id["tank"]["qa_flags"]
    assert by_id["tank"]["coverage_status"] == "missing_translation"
    assert result.report["unresolved_regions"] == 1
    assert result.report["passed"] is False


def test_translation_qa_uses_a_corrected_semantic_judgement(tmp_path) -> None:
    def correction_requester(messages: list[dict[str, str]], **_kwargs: object) -> str:
        payload = json.loads(messages[-1]["content"])
        item = payload["items"][0]
        if payload["stage"] == "engineering_translation":
            return json.dumps(
                {
                    "translations": [
                        {
                            "item_id": item["item_id"],
                            "translated_text": "水箱",
                            "action": "translate",
                            "issues": [],
                        }
                    ]
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "reviews": [
                    {
                        "item_id": item["item_id"],
                        "verdict": "corrected",
                        "translated_text": "净水箱",
                        "issues": ["term_conflict"],
                    }
                ]
            },
            ensure_ascii=False,
        )

    result = translate_and_judge_engineering_regions(
        [
            {
                "region_id": "tank",
                "source_text": "Treated Water Tank",
                "source_language": "en",
                "action": "translate",
                "qa_flags": [],
            }
        ],
        api_key="test-key",
        cache_path=tmp_path / "cache.json",
        request_chat_content_fn=correction_requester,
    )

    region = result.regions[0]
    assert region["translated_text"] == "净水箱"
    assert region["ai_judgement"] == "corrected"
    assert "term_conflict" in region["qa_flags"]
    assert result.report["corrected_regions"] == 1


def test_translation_qa_records_ai_confirmed_ocr_noise_without_counting_it_as_untranslated(tmp_path) -> None:
    def noise_requester(messages: list[dict[str, str]], **_kwargs: object) -> str:
        payload = json.loads(messages[-1]["content"])
        item = payload["items"][0]
        if payload["stage"] == "engineering_translation":
            return json.dumps(
                {
                    "translations": [
                        {
                            "item_id": item["item_id"],
                            "translated_text": "OCR 疑似噪声：ENAASAEEEEE",
                            "action": "review",
                            "issues": ["ocr_suspect"],
                        }
                    ]
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "reviews": [
                    {
                        "item_id": item["item_id"],
                        "verdict": "not_language",
                        "translated_text": "",
                        "issues": ["ocr_noise"],
                    }
                ]
            },
            ensure_ascii=False,
        )

    result = translate_and_judge_engineering_regions(
        [
            {
                "region_id": "noise",
                "source_text": "ENAASAEEEEE",
                "source_language": "en",
                "action": "review",
                "provenance": "paddle_ocr",
                "confidence": 0.20,
                "qa_flags": [],
            }
        ],
        api_key="test-key",
        cache_path=tmp_path / "cache.json",
        request_chat_content_fn=noise_requester,
    )

    assert result.regions[0]["coverage_status"] == "ai_confirmed_non_language"
    assert result.regions[0]["translated_text"] == ""
    assert result.report["ai_confirmed_non_language_regions"] == 1
    assert result.report["target_regions"] == 0
    assert result.report["unresolved_regions"] == 0
    assert result.report["passed"] is True


def test_translation_qa_does_not_discard_credible_native_text_as_noise(tmp_path) -> None:
    def noise_requester(messages: list[dict[str, str]], **_kwargs: object) -> str:
        payload = json.loads(messages[-1]["content"])
        item = payload["items"][0]
        if payload["stage"] == "engineering_translation":
            return json.dumps(
                {
                    "translations": [
                        {
                            "item_id": item["item_id"],
                            "translated_text": "OCR 疑似噪声：DEPOH LORI",
                            "action": "review",
                            "issues": [],
                        }
                    ]
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "reviews": [
                    {
                        "item_id": item["item_id"],
                        "verdict": "not_language",
                        "translated_text": "",
                        "issues": ["ocr_noise"],
                    }
                ]
            },
            ensure_ascii=False,
        )

    result = translate_and_judge_engineering_regions(
        [
            {
                "region_id": "depoh",
                "source_text": "DEPOH LORI",
                "source_language": "ms",
                "action": "translate",
                "provenance": "vector_outline",
                "qa_flags": ["fixed_regression_vector_outline"],
            }
        ],
        api_key="test-key",
        cache_path=tmp_path / "cache.json",
        request_chat_content_fn=noise_requester,
    )

    assert result.regions[0]["coverage_status"] == "manual_review"
    assert "ai_non_language_rejected_for_credible_source" in result.regions[0]["qa_flags"]
    assert result.report["passed"] is False


def test_translation_qa_turns_unchanged_literal_code_into_a_chinese_descriptor(tmp_path) -> None:
    def literal_requester(messages: list[dict[str, str]], **_kwargs: object) -> str:
        payload = json.loads(messages[-1]["content"])
        item = payload["items"][0]
        if payload["stage"] == "engineering_translation":
            return json.dumps(
                {
                    "translations": [
                        {
                            "item_id": item["item_id"],
                            "translated_text": "IN",
                            "action": "keep_literal",
                            "issues": [],
                        }
                    ]
                },
                ensure_ascii=False,
            )
        assert item["translated_text"] == "入口（原文：IN）"
        return json.dumps(
            {
                "reviews": [
                    {
                        "item_id": item["item_id"],
                        "verdict": "accepted",
                        "translated_text": item["translated_text"],
                        "issues": [],
                    }
                ]
            },
            ensure_ascii=False,
        )

    result = translate_and_judge_engineering_regions(
        [
            {
                "region_id": "in",
                "source_text": "IN",
                "source_language": "en",
                "action": "keep_literal",
                "qa_flags": [],
            }
        ],
        api_key="test-key",
        cache_path=tmp_path / "cache.json",
        request_chat_content_fn=literal_requester,
    )

    assert result.regions[0]["translated_text"] == "入口（原文：IN）"
    assert result.regions[0]["coverage_status"] == "literal_labeled"
    assert result.report["passed"] is True


def test_translation_qa_gives_ptd_and_malay_road_names_meaningful_chinese_companions(tmp_path) -> None:
    def literal_requester(messages: list[dict[str, str]], **_kwargs: object) -> str:
        payload = json.loads(messages[-1]["content"])
        if payload["stage"] == "engineering_translation":
            return json.dumps(
                {
                    "translations": [
                        {
                            "item_id": item["item_id"],
                            "translated_text": item["source_text"],
                            "action": "keep_literal",
                            "issues": [],
                        }
                        for item in payload["items"]
                    ]
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "reviews": [
                    {
                        "item_id": item["item_id"],
                        "verdict": "accepted",
                        "translated_text": item["translated_text"],
                        "issues": [],
                    }
                    for item in payload["items"]
                ]
            },
            ensure_ascii=False,
        )

    result = translate_and_judge_engineering_regions(
        [
            {"region_id": "ptd", "source_text": "PTD 238149", "source_language": "en", "action": "keep_literal"},
            {"region_id": "road", "source_text": "Jalan Felda Cahaya Baru", "source_language": "ms", "action": "keep_literal"},
        ],
        api_key="test-key",
        cache_path=tmp_path / "cache.json",
        request_chat_content_fn=literal_requester,
    )

    translated = {item["region_id"]: item["translated_text"] for item in result.regions}
    assert translated["ptd"] == "土地编号：PTD 238149"
    assert translated["road"] == "费尔达新光路（Jalan Felda Cahaya Baru）"


def test_translation_qa_repairs_english_only_candidate_before_semantic_qa(tmp_path) -> None:
    calls: list[str] = []

    def repair_requester(messages: list[dict[str, str]], **_kwargs: object) -> str:
        payload = json.loads(messages[-1]["content"])
        calls.append(payload["stage"])
        item = payload["items"][0]
        if payload["stage"] == "engineering_translation":
            return json.dumps(
                {
                    "translations": [
                        {
                            "item_id": item["item_id"],
                            "translated_text": "CADANGAN LALUAN SEHALA (6100MM LEBAR)",
                            "action": "translate",
                            "issues": [],
                        }
                    ]
                },
                ensure_ascii=False,
            )
        if payload["stage"] == "engineering_translation_repair":
            return json.dumps(
                {
                    "translations": [
                        {
                            "item_id": item["item_id"],
                            "translated_text": "建议单向通道（6100MM宽）",
                            "action": "translate",
                            "issues": ["forced_chinese_repair"],
                        }
                    ]
                },
                ensure_ascii=False,
            )
        assert payload["stage"] == "engineering_translation_qa"
        assert item["translated_text"] == "建议单向通道（6100MM宽）"
        return json.dumps(
            {
                "reviews": [
                    {
                        "item_id": item["item_id"],
                        "verdict": "accepted",
                        "translated_text": item["translated_text"],
                        "issues": [],
                    }
                ]
            },
            ensure_ascii=False,
        )

    result = translate_and_judge_engineering_regions(
        [
            {
                "region_id": "road",
                "source_text": "CADANGAN LALUAN SEHALA (6100MM LEBAR)",
                "source_language": "ms",
                "action": "translate",
                "qa_flags": [],
            }
        ],
        api_key="test-key",
        cache_path=tmp_path / "cache.json",
        request_chat_content_fn=repair_requester,
    )

    assert calls == ["engineering_translation", "engineering_translation_repair", "engineering_translation_qa"]
    assert result.regions[0]["translated_text"] == "建议单向通道（6100MM宽）"
    assert result.report["passed"] is True


def test_translation_qa_restores_required_literal_token_before_qa(tmp_path) -> None:
    def token_requester(messages: list[dict[str, str]], **_kwargs: object) -> str:
        payload = json.loads(messages[-1]["content"])
        item = payload["items"][0]
        if payload["stage"] == "engineering_translation":
            return json.dumps(
                {
                    "translations": [
                        {
                            "item_id": item["item_id"],
                            "translated_text": "退界线为 6 米",
                            "action": "translate",
                            "issues": [],
                        }
                    ]
                },
                ensure_ascii=False,
            )
        assert payload["stage"] == "engineering_translation_qa"
        assert "6M" in item["translated_text"]
        return json.dumps(
            {
                "reviews": [
                    {
                        "item_id": item["item_id"],
                        "verdict": "accepted",
                        "translated_text": item["translated_text"],
                        "issues": [],
                    }
                ]
            },
            ensure_ascii=False,
        )

    result = translate_and_judge_engineering_regions(
        [
            {
                "region_id": "setback",
                "source_text": "SETBACK 6M",
                "source_language": "en",
                "action": "translate",
                "qa_flags": [],
            }
        ],
        api_key="test-key",
        cache_path=tmp_path / "cache.json",
        request_chat_content_fn=token_requester,
    )

    assert "6M" in result.regions[0]["translated_text"]
    assert result.report["passed"] is True
