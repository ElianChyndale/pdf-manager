# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
import json,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
import generate_v311_verified_plans as gen
import replan_v311_grouped as grp
BASE=Path(r"D:\AmyProjects\business\pdf-manager\output\pdf\engineering-drawing\01_Bilingual_Inline\agent-artifacts\v3.11-cost-balanced-final-3")
for rec in json.loads((BASE/"sample-records.json").read_text(encoding="utf-8"))["records"]:
 gen.build_inline_plan(rec);grp.replan(rec)
