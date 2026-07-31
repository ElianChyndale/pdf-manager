# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
import json
from pathlib import Path

ROOT = Path(r"D:\AmyProjects\business\pdf-manager\output\pdf\engineering-drawing\01_Bilingual_Inline\agent-artifacts\sol-light-supervisor-verified-v311")
records = json.loads((ROOT / "sample-records.json").read_text(encoding="utf-8"))["records"]
for rec in records:
    work = Path(rec["artifact_dir"])
    tasks = [{"id": f"visual-page-{i+1:04d}-full", "page_index": i, "full_page": True,
              "engine": "technical_cad_ocr", "rotation": 0, "language_scope": ["ms", "en", "technical_codes"],
              "purpose": "Supervisor-confirmed full-page zone: enumerate visible natural-language rows and micro-labels"}
             for i in range(rec["page_count"])]
    payload = {"supervisor_plan": {"ocr_tasks": tasks}}
    (work / "preplan-ocr-tasks.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
