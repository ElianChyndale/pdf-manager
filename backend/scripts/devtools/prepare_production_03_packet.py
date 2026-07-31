# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
from pathlib import Path
import json
from scripts.services.engineering_drawing.agent_system import EngineeringDrawingAgent

BASE=Path(r"D:\AmyProjects\business\pdf-manager\output\pdf\engineering-drawing\01_Bilingual_Inline")
records=json.loads((BASE/r"agent-artifacts/v3.12-human-audit-repair/sample-records.json").read_text(encoding="utf8"))["records"]
r=records[2]
work=BASE/r"agent-artifacts/v3.12-quality-production-10/03"
work.mkdir(parents=True,exist_ok=True)
agent=EngineeringDrawingAgent(model="gpt-5.6-sol")
manifest=agent.build_manifest(Path(r["source"]), reference_pdf=Path(r["reference"]))
(work/"agent-manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf8")
packet=agent.build_page_packet(Path(r["source"]),0,manifest=manifest,output_dir=work/r"page-0001",dpi=180)
print(json.dumps(packet["source_text_lines"],ensure_ascii=False,indent=2))
