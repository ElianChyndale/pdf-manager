# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
import json,fitz
from pathlib import Path
ROOT=Path(r"D:\AmyProjects\business\pdf-manager\output\pdf\engineering-drawing\01_Bilingual_Inline");ART=ROOT/"agent-artifacts/v3.12-human-audit-repair";recs=json.loads((ART/"sample-records.json").read_text(encoding="utf8"))["records"];out=[]
for r in recs:
 w=Path(r["artifact_dir"]);s=json.loads((w/"local-repair-status.json").read_text(encoding="utf8"));p=Path(s["candidate_pdf"]);d=w/"local-repair-review";d.mkdir(exist_ok=True);imgs=[]
 with fitz.open(p) as doc:
  for i,page in enumerate(doc):q=d/f"page-{i+1:04d}.png";page.get_pixmap(matrix=fitz.Matrix(2,2),alpha=False).save(q);imgs.append(str(q))
 qa=s["deterministic_visual_qa"];out.append({"index":r["index"],"source_pdf":r["source"],"reference_pdf":r.get("reference"),"source_page_images":r["source_images"],"candidate_pdf":str(p),"candidate_page_images":imgs,"coverage_total":r["coverage_total"],"remaining":{"visual_overlap_count":qa.get("visual_overlap_count",0),"manual_review_count":qa.get("manual_review_count",0),"untranslated_candidate_count":qa.get("untranslated_candidate_count",0),"leader_collision_count":qa.get("leader_collision_count",0)},"publication":"not_authorized"})
(ART/"local-repair-audit-report.json").write_text(json.dumps({"schema":"v3.12-one-local-repair-report","repair_count":1,"records":out},ensure_ascii=False,indent=2)+"\n",encoding="utf8")
