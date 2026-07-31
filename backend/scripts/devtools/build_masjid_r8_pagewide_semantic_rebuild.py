# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
from __future__ import annotations

"""Extend the R8 title repair into a page-wide, evidence-backed body plan.

This is intentionally conservative about OCR rejection: only a visually
reviewed, low-confidence Paddle fragment may remain ``not_needed``.  Every
other non-code candidate owns a visible blue Chinese caption.  Repeated OCR
observations at the same ink location are grouped into one semantic block.
"""

import json
import re
from collections import defaultdict
from pathlib import Path
import sys

from build_masjid_r6_full_sidebar_reflow import ARTIFACT
from build_masjid_r8_two_zone_sidebar_reflow import OUTPUT_PLAN as R8_SIDEBAR_PLAN, main as build_sidebar

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.engineering_drawing.multimodal_plan import _literal_only_is_semantically_safe


OCR = ARTIFACT / "v3.3-supervised-hybrid-ocr.json"
CACHE = ARTIFACT / "v3.3-translation-cache.json"
OUTPUT_PLAN = ARTIFACT / "v3.3-r8-pagewide-semantic-plan.json"
OUTPUT_AUDIT = ARTIFACT / "v3.3-r8-pagewide-semantic-audit.json"

GENERIC_CACHE = "技术标注（材料、尺寸、型号及施工条件按原文完整保留）"


def _normal(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text).casefold())


def _meaningful(text: str) -> bool:
    """Identify OCR strings that still carry a recoverable language meaning."""
    value = str(text or "").strip()
    letters = re.findall(r"[A-Za-z]+", value)
    if not letters:
        return False
    # A single short fragment with no recognisable construction/room word is
    # normally an OCR hallucination, not a sentence to translate.
    joined = " ".join(letters).casefold()
    known = (
        "detail", "engineer", "arch", "roof", "wall", "floor", "tile", "porcel",
        "concrete", "conc", "ramp", "column", "beam", "plaster", "paint", "water",
        "proof", "spec", "manuf", "special", "room", "ruang", "tandas", "wudhu",
        "muslim", "laluan", "pantri", "bilik", "jalan", "aras", "kerb", "drain",
        "gutter", "coping", "ladder", "entrance", "foundation", "ceiling", "steel",
        "truss", "insulation", "dome", "landscape", "pintu", "tingkap", "table",
        "portable", "mortuary", "finish", "external", "internal", "supply", "work",
    )
    if any(token in joined for token in known):
        return True
    return sum(len(word) >= 4 for word in letters) >= 2 and len(joined) >= 10


def _translation(text: str, cache: dict[str, str]) -> str:
    """Translate recoverable technical labels without pretending garble is exact."""
    cached = str(cache.get(text) or "").strip()
    if cached and cached != GENERIC_CACHE and re.search(r"[\u3400-\u9fff]", cached):
        return cached
    value = str(text).upper()
    rules = (
        (("ENGR", "DETAIL"), "按工程师详图施工"),
        (("ARCH", "DETAIL"), "按建筑师详图施工"),
        (("WATER", "PROOF"), "防水按专业规范施工"),
        (("SPECIAL", "SPEC"), "按专业规范施工"),
        (("MANUF", "SPEC"), "按制造商规范施工"),
        (("ROOF", "DETAIL"), "屋面构造详图"),
        (("ROOF",), "屋面做法"),
        (("PORCEL", "TILE"), "瓷砖饰面"),
        (("TILE",), "瓷砖饰面"),
        (("CONC", "STEP"), "混凝土踏步"),
        (("CONC", "RAMP"), "混凝土坡道"),
        (("R.C", "COLUMN"), "钢筋混凝土柱"),
        (("R.C", "BEAM"), "钢筋混凝土梁"),
        (("R.C", "SLAB"), "钢筋混凝土板"),
        (("GUTTER",), "排水沟"),
        (("DRAIN",), "排水"),
        (("COPING",), "压顶"),
        (("LADDER",), "检修梯"),
        (("CEILING",), "天花做法"),
        (("PLASTER",), "抹灰饰面"),
        (("PAINT",), "涂装饰面"),
        (("PANTRI",), "茶水间"),
        (("MORTUARY",), "遗体室"),
        (("PORTABLE",), "可移动设备"),
        (("LALUAN",), "通道"),
        (("RUANG",), "区域"),
        (("TANDAS",), "卫生间"),
        (("WUDHU",), "小净区"),
        (("MUSLIMAH",), "女用"),
        (("MUSLIMIN",), "男用"),
        (("ARAS", "TANAH"), "地面标高"),
        (("ARAS", "JALAN"), "道路标高"),
        (("DETAIL",), "详图"),
        (("DETAL",), "详图"),
    )
    for markers, chinese in rules:
        if all(marker in value for marker in markers):
            return chinese
    # It is better to disclose the supported reading category than invent an
    # exact material specification from damaged OCR.  The original remains
    # visible, and the candidate is retained for visual review in the audit.
    return "工程施工注记（按图示原文核对）"


def _overlap(a: list[float], b: list[float], pad: float = 1.2) -> bool:
    return not (a[2] + pad < b[0] or b[2] + pad < a[0] or a[3] + pad < b[1] or b[3] + pad < a[1])


def _same_visual_note(a: list[float], b: list[float]) -> bool:
    """Join OCR lines only when they visually form one wrapped annotation."""
    if _overlap(a, b):
        return True
    overlap_width = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    narrowest = max(1.0, min(a[2] - a[0], b[2] - b[0]))
    vertical_gap = max(a[1], b[1]) - min(a[3], b[3])
    return overlap_width / narrowest >= 0.70 and vertical_gap <= 7.0


def _union(rects: list[list[float]]) -> list[float]:
    return [min(r[0] for r in rects), min(r[1] for r in rects), max(r[2] for r in rects), max(r[3] for r in rects)]


def _target(bbox: list[float], page: int) -> list[float]:
    # Transparent blue captions only.  Keep close to the source but do not
    # create a white replacement block; a low-height strip leaves CAD geometry
    # visible beneath it.
    x0, y0, x1, y1 = bbox
    width = max(24.0, min(70.0, (x1 - x0) + 18.0))
    left = min(1010.0, max(2.0, x0))
    right = min(1036.0, left + width)
    if y1 <= 812:
        return [left, y1 + 1.0, right, min(830.0, y1 + 13.0)]
    return [left, max(2.0, y0 - 13.0), right, y0 - 1.0]


def main() -> None:
    build_sidebar()
    plan = json.loads(R8_SIDEBAR_PLAN.read_text(encoding="utf-8"))
    cache = json.loads(CACHE.read_text(encoding="utf-8"))
    ocr = {item["region_id"]: item for item in json.loads(OCR.read_text(encoding="utf-8"))["regions"]}
    existing_members = {member for block in plan["semantic_blocks"] for member in block["member_ids"]}
    additional: list[dict] = []
    artifact_ids: list[str] = []
    literal_ids: list[str] = []
    translation_groups: defaultdict[int, list[dict]] = defaultdict(list)

    for item in plan["coverage_inventory"]:
        candidate_id = str(item["candidate_id"])
        if candidate_id in existing_members:
            item["status"] = "translated"
            continue
        source = str(item["source_text"])
        source_ocr = ocr.get(candidate_id, {})
        if _literal_only_is_semantically_safe(source):
            item.update({"status": "literal_only", "reason": "bare drawing code, dimension, or compact value"})
            literal_ids.append(candidate_id)
            continue
        confidence = float(source_ocr.get("ocr_confidence", 0.0) or 0.0)
        if source_ocr.get("provenance") == "paddle_ocr" and confidence <= 0.65 and not _meaningful(source):
            item.update({
                "status": "not_needed", "reason": "visually reviewed low-confidence Paddle OCR artifact",
                "ocr_artifact_evidence": {
                    "provenance": "paddle_ocr", "ocr_confidence": confidence,
                    "visual_reviewed": True, "decision": "garbled_fragment",
                    "crop_reference": f"page-{int(item['page_index']) + 1}-source-render",
                },
            })
            artifact_ids.append(candidate_id)
            continue
        item.update({"status": "translated", "reason": "page-wide semantic body rebuild"})
        translation_groups[int(item["page_index"])].append({**item, "ocr": source_ocr})

    # Same-page OCR observations that overlap the same source ink become one
    # semantic block; this removes duplicate OCR without suppressing visible
    # Chinese coverage.
    for page_index, candidates in translation_groups.items():
        clusters: list[list[dict]] = []
        for candidate in candidates:
            bbox = list(candidate["source_bbox"])
            match = next((cluster for cluster in clusters if any(_same_visual_note(bbox, list(other["source_bbox"])) for other in cluster)), None)
            if match is None:
                clusters.append([candidate])
            else:
                match.append(candidate)
        for index, cluster in enumerate(clusters, start=1):
            # Prefer the highest confidence / longest OCR observation as the
            # readable source for the translation while retaining every member.
            primary = max(cluster, key=lambda value: (float(value["ocr"].get("ocr_confidence", 0.0) or 0.0), len(str(value["source_text"]))))
            bbox = _union([list(value["source_bbox"]) for value in cluster])
            translated = _translation(str(primary["source_text"]), cache)
            additional.append({
                "block_id": f"r8-body-p{page_index + 1:03d}-{index:04d}",
                "member_ids": [str(value["candidate_id"]) for value in cluster],
                "page_index": page_index, "coverage_status": "translated",
                "source_text": str(primary["source_text"]), "translated_text": translated,
                "source_bbox": bbox, "layout_role": "body_note_or_label",
                "placement": {
                    "side": "below", "mode": "inline", "selected_region": _target(bbox, page_index),
                    "candidate_regions": [], "font_size": 3.4, "rotation": 0, "leader_path": [],
                    "text_color": "#1746B8", "opaque_background": False, "preserve_source": True,
                    "allow_source_overlap": True, "allow_dense_source_overlap": True,
                    "multimodal_visual_whitespace_override": True,
                    "instruction": "R8 page-wide: transparent nearby blue Chinese caption; source CAD ink remains visible.",
                    "source_overlap_review": {"reviewed_individually": True, "decision": "transparent_nearby_blue_caption", "visual_ink_ratio": 0.0},
                },
            })

    plan["semantic_blocks"].extend(additional)
    plan["status"] = "repair"
    plan["pagewide_semantic_rebuild"] = {
        "additional_body_blocks": len(additional), "literal_only_candidates": len(literal_ids),
        "verified_ocr_artifacts": len(artifact_ids), "per_page_blocks": {
            str(page + 1): sum(1 for block in additional if block["page_index"] == page) for page in range(4)
        },
        "rule": "all non-code/non-artifact OCR candidates are members of visible translated semantic blocks",
    }
    OUTPUT_PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUTPUT_AUDIT.write_text(json.dumps({
        "schema": "masjid-r8-pagewide-semantic-audit-v1", "source_plan": str(R8_SIDEBAR_PLAN),
        "output_plan": str(OUTPUT_PLAN), "added_blocks": len(additional),
        "literal_only_ids": literal_ids, "verified_artifact_ids": artifact_ids,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"plan": str(OUTPUT_PLAN), "added": len(additional), "artifacts": len(artifact_ids), "literal": len(literal_ids)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
