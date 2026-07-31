from services.engineering_drawing.semantic_grouping import build_semantic_groups


def _region(
    region_id: str,
    source_text: str,
    translated_text: str,
    bbox: list[float],
    *,
    rotation: int = 0,
) -> dict:
    return {
        "region_id": region_id,
        "page_index": 0,
        "source_text": source_text,
        "translated_text": translated_text,
        "bbox": bbox,
        "rotation": rotation,
    }


def test_groups_rotated_technical_fragments_into_one_atomic_label() -> None:
    regions = [
        _region(
            "voltage",
            "275/11/11kV",
            "275/11/11kV",
            [100, 230, 112, 300],
            rotation=90,
        ),
        _region("hv", "HV", "高压", [100, 195, 112, 225], rotation=90),
        _region(
            "transformer",
            "TRANSFORMER B-2",
            "变压器 B-2",
            [100, 100, 112, 190],
            rotation=90,
        ),
    ]

    groups = build_semantic_groups(regions)

    assert len(groups) == 1
    group = groups[0]
    assert group["source_group_text"] == "275/11/11kV HV TRANSFORMER B-2"
    assert group["translated_text"] == "275/11/11kV 高压变压器 B-2"
    assert group["source_group_bbox"] == [100.0, 100.0, 112.0, 300.0]
    assert group["rotation"] == 90
    assert group["member_region_ids"] == ["voltage", "hv", "transformer"]
    assert group["covered_region_ids"] == ["voltage", "hv", "transformer"]
    assert group["semantic_group_kind"] == "inline_technical_label"
    assert [member["source_text"] for member in group["members"]] == [
        "275/11/11kV",
        "HV",
        "TRANSFORMER B-2",
    ]


def test_groups_wrapped_technical_label_but_not_adjacent_title_block_rows() -> None:
    regions = [
        _region("raw-water", "RAW WATER", "原水", [30, 20, 100, 32]),
        _region("tank", "TANK", "水箱", [30, 35, 70, 47]),
        _region("drawn", "DRAWN:", "绘制：", [30, 90, 80, 102]),
        _region("checked", "CHECKED:", "审核：", [30, 105, 95, 117]),
    ]

    groups = build_semantic_groups(regions)

    by_members = {tuple(group["member_region_ids"]): group for group in groups}
    technical = by_members[("raw-water", "tank")]
    assert technical["source_group_text"] == "RAW WATER TANK"
    assert technical["translated_text"] == "原水水箱"
    assert technical["semantic_group_kind"] == "stacked_technical_label"
    assert ("drawn",) in by_members
    assert ("checked",) in by_members


def test_keeps_separate_labels_and_does_not_mutate_region_input() -> None:
    regions = [
        _region("pump-a", "PUMP A", "水泵 A", [20, 20, 70, 32]),
        _region("pump-b", "PUMP B", "水泵 B", [150, 20, 200, 32]),
        _region("ungrounded", "NOTE", "备注", [20, 100, 50, 112]),
    ]
    original = [dict(region) for region in regions]

    groups = build_semantic_groups(regions)

    assert [group["source_group_text"] for group in groups] == [
        "PUMP A",
        "PUMP B",
        "NOTE",
    ]
    assert all(group["member_count"] == 1 for group in groups)
    assert regions == original


def test_marks_partial_translation_without_dropping_any_member() -> None:
    regions = [
        _region("hv", "HV", "高压", [20, 20, 42, 32]),
        _region("cable", "CABLE", "", [47, 20, 92, 32]),
    ]

    groups = build_semantic_groups(regions)

    assert len(groups) == 1
    assert groups[0]["source_group_text"] == "HV CABLE"
    assert groups[0]["translated_text"] == "高压"
    assert groups[0]["translation_status"] == "partial"
    assert groups[0]["coverage_status"] == "partial"
    assert groups[0]["member_region_ids"] == ["hv", "cable"]


def test_repairs_split_legacy_chinese_glyphs_with_duplicate_source_anchor() -> None:
    regions = [
        _region(
            "p001-legacy-0072",
            "TRANSFORMER B-2",
            "变",
            [975, 1253.9968, 981, 1259.9968],
            rotation=270,
        ),
        _region(
            "p001-legacy-0073",
            "TRANSFORMER B-2",
            "压",
            [975, 1260.8408, 981, 1266.8408],
            rotation=270,
        ),
        _region(
            "p001-legacy-0074",
            "TRANSFORMER B-2",
            "器",
            [975, 1267.6848, 984, 1273.6848],
            rotation=270,
        ),
    ]

    groups = build_semantic_groups(regions)

    assert len(groups) == 1
    assert groups[0]["source_group_text"] == "TRANSFORMER B-2"
    assert groups[0]["translated_text"] == "变压器"
    assert groups[0]["member_region_ids"] == [
        "p001-legacy-0072",
        "p001-legacy-0073",
        "p001-legacy-0074",
    ]


def test_repairs_tight_source_less_cjk_column_without_merging_next_label() -> None:
    regions = [
        _region("p001-legacy-0019", "", "保温", [350, 1401.7007, 360, 1406.7007]),
        _region("p001-legacy-0020", "", "冷凝", [350, 1407.4037, 360, 1412.4037]),
        _region("p001-legacy-0021", "", "水管", [350, 1413.1067, 360, 1418.1067]),
        # This complete legend entry is nearby in the same column, but its
        # wider vertical gap must keep it out of the split-glyph group.
        _region("p001-legacy-0022", "", "风机盘管", [350, 1432, 385, 1440]),
    ]

    groups = build_semantic_groups(regions)

    by_members = {tuple(group["member_region_ids"]): group for group in groups}
    repaired = by_members[
        ("p001-legacy-0019", "p001-legacy-0020", "p001-legacy-0021")
    ]
    assert repaired["source_group_text"] == ""
    assert repaired["translated_text"] == "保温冷凝水管"
    assert repaired["semantic_group_kind"] == "split_cjk_label"
    assert ("p001-legacy-0022",) in by_members


def test_source_less_cjk_group_does_not_jump_to_a_shifted_adjacent_column() -> None:
    regions = [
        _region("pipe-1", "", "管", [929, 980, 935, 986]),
        _region("pipe-2", "", "道", [929, 987, 935, 993]),
        # The next label begins only a few points lower, but it belongs to a
        # visibly shifted column and must not become "管道排水".
        _region("drain", "", "排水", [935, 997, 943, 1001]),
    ]

    groups = build_semantic_groups(regions)

    by_members = {tuple(group["member_region_ids"]): group for group in groups}
    assert by_members[("pipe-1", "pipe-2")]["translated_text"] == "管道"
    assert ("drain",) in by_members


def test_groups_wrapped_note_as_one_newline_preserving_paragraph_block() -> None:
    regions = [
        _region("roof-title", "ROOF SYSTEM :", "屋面系统：", [30, 20, 140, 32]),
        _region(
            "roof-1",
            "- CUT TO LENGTH SEL. KLIPLOK OPTIMA 0.48MM BMT",
            "按长度定制 KLIPLOK OPTIMA 0.48MM BMT",
            [30, 36, 250, 48],
        ),
        _region(
            "roof-2",
            "(0.54MM TC) IN AZ200 G550 COLORBOND ULTRA STEEL",
            "（0.54MM TC），AZ200 G550 COLORBOND ULTRA 钢板",
            [30, 52, 240, 64],
        ),
        _region(
            "roof-3",
            "FIXED KL98 CLIPS C/W 43MM RIB HEIGHT AND 980MM COVER WIDTH.",
            "采用 KL98 夹具，肋高 43MM，覆盖宽度 980MM。",
            [30, 68, 260, 80],
        ),
        _region("drawn", "DRAWN:", "绘制：", [30, 110, 80, 122]),
        _region("checked", "CHECKED:", "审核：", [30, 126, 95, 138]),
    ]

    groups = build_semantic_groups(regions)

    by_members = {tuple(group["member_region_ids"]): group for group in groups}
    block = by_members[("roof-title", "roof-1", "roof-2", "roof-3")]
    assert block["semantic_group_kind"] == "paragraph_block"
    assert block["translation_unit"] == "one_block"
    assert block["block_translation_required"] is True
    assert block["translated_text"].splitlines() == [
        "屋面系统：",
        "按长度定制 KLIPLOK OPTIMA 0.48MM BMT",
        "（0.54MM TC），AZ200 G550 COLORBOND ULTRA 钢板",
        "采用 KL98 夹具，肋高 43MM，覆盖宽度 980MM。",
    ]
    assert ("drawn",) in by_members
    assert ("checked",) in by_members


def test_paragraph_group_does_not_merge_independent_literal_rows() -> None:
    regions = [
        _region("code", "AHU-01", "空气处理机编号：AHU-01", [30, 20, 75, 32]),
        _region("dimension", "1500 mm", "1500 mm", [30, 36, 90, 48]),
        _region("room", "PUMP ROOM", "水泵房", [30, 52, 110, 64]),
        _region("note", "INSTALL EQUIPMENT AS SHOWN ON DRAWING.", "按图纸安装设备。", [30, 68, 250, 80]),
    ]

    groups = build_semantic_groups(regions)

    by_members = {tuple(group["member_region_ids"]): group for group in groups}
    assert ("code",) in by_members
    assert ("dimension",) in by_members
    assert ("room",) in by_members
    assert ("note",) in by_members
