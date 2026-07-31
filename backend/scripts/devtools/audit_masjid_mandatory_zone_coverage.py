# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
from __future__ import annotations

"""Audit semantic coverage of the user-mandated Masjid visual zones.

This is deliberately a diagnostic rather than a publishing gate bypass: a
zone is only complete when every readable OCR/native observation in it belongs
to a visible semantic block with a non-generic Chinese rendering.
"""

import json
import re
from pathlib import Path


ARTIFACT = Path(
    r"D:\AmyProjects\business\pdf-manager\output\pdf\engineering-drawing\01_Bilingual_Inline\batch-artifacts\03_CONSTRUCTION_DWG_MASJID_11_NOV_2025__01_Masjid_Tok_Muda_CONSTRUCTION__f8ffb95ffe"
)
OCR = ARTIFACT / "v3.3-supervised-hybrid-ocr.json"
PLAN = ARTIFACT / "v3.4-r11-left-companion-strict-plan.json"
OUTPUT = ARTIFACT / "v3.4-masjid-mandatory-zone-coverage.json"


ZONES = {
    "elevation_detail_callouts": r"ENGR|ARCH|DETAIL|ROOF|GUTTER|WATER.?PROOF|DOME|WALL|CONC|PLASTER|PAINT|CEMENT|PORCEL|TRUSS|SLAB|BEAM|COPING|RENDER",
    "general_notes": r"NOTA\s*UMUM|CONTRACTOR|DIMENSION|DRAWING|SPECIFICATION|WORK",
    "schedules": r"JADUAL|TABLE|PINTU|TINGKAP|KELUASAN|PENCAHAYAAN|PENGUDARAAN|KEMASAN",
    "tower_plans": r"PELAN\s*MENARA|MENARA|RASUK",
    "elevations_sections": r"PANDANGAN|ELEVATION|SECTION|ARAS\s*(RASUK|TANAH|JALAN)",
    "room_labels": r"RUANG|BILIK|TANDAS|WUDHU|MUSLIM|KORIDOR|LALUAN|PANTRI|JENAZAH",
}
GENERIC = re.compile(r"技术标注|工程施工注记|区域（数值|空间／设备标签", re.I)
CHINESE = re.compile(r"[\u3400-\u9fff]")


def readable(region: dict) -> bool:
    text = str(region.get("source_text") or "").strip()
    return bool(re.search(r"[A-Za-z]", text)) and float(region.get("ocr_confidence") or 0) >= 0.60


def main() -> None:
    ocr = json.loads(OCR.read_text(encoding="utf-8"))["regions"]
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    memberships: dict[str, dict] = {}
    for block in plan.get("semantic_blocks", []):
        for member in block.get("member_ids", []):
            memberships[str(member)] = block

    pages: dict[str, dict] = {}
    total = complete = 0
    for page_index in range(4):
        page: dict[str, list[dict]] = {}
        for zone, pattern in ZONES.items():
            entries: list[dict] = []
            for region in ocr:
                if int(region.get("page_index", -1)) != page_index or not readable(region):
                    continue
                source = str(region.get("source_text") or "")
                if not re.search(pattern, source, re.I):
                    continue
                total += 1
                block = memberships.get(str(region["region_id"]))
                translated = str((block or {}).get("translated_text") or "")
                render_text = str(((block or {}).get("placement") or {}).get("render_text") or translated)
                usable = bool(block) and bool(CHINESE.search(render_text)) and not GENERIC.search(render_text)
                if usable:
                    complete += 1
                entries.append(
                    {
                        "region_id": region["region_id"],
                        "source_text": source,
                        "bbox": region.get("bbox") or [],
                        "covered": usable,
                        "block_id": (block or {}).get("block_id", ""),
                        "render_text": render_text,
                        "reason": "covered_by_specific_chinese_block" if usable else "missing_or_generic_chinese",
                    }
                )
            page[zone] = entries
        pages[str(page_index + 1)] = page

    payload = {
        "schema": "masjid-mandatory-zone-coverage-v1",
        "plan": str(PLAN),
        "criterion": "every readable source observation must map to a specific non-generic Chinese render_text",
        "mandatory_zones": ZONES,
        "pages": pages,
        "summary": {"readable_observations": total, "specific_chinese_covered": complete, "missing_or_generic": total - complete},
        "publishable": total == complete,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), **payload["summary"], "publishable": payload["publishable"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
