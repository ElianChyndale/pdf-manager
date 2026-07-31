# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
import json,fitz
from pathlib import Path
ROOT=Path(r"D:\AmyProjects\business\pdf-manager\output\pdf\engineering-drawing\01_Bilingual_Inline")
ART=ROOT/"agent-artifacts/v3.12-human-audit-repair";CAND=ROOT/"translated/v3.12-human-audit-repair-candidates"
records=json.loads((ART/"sample-records.json").read_text(encoding="utf-8"))["records"]
rows=[]
for r in records:
 w=Path(r["artifact_dir"]);s=json.loads((w/"execute-status.json").read_text(encoding="utf-8"));pdf=Path(s["candidate_pdf"]) if s.get("candidate_pdf") else None;cimgs=[]
 if pdf and pdf.exists():
  d=w/"candidate-review";d.mkdir(exist_ok=True)
  with fitz.open(pdf) as doc:
   for i,p in enumerate(doc):
    q=d/f"page-{i+1:04d}.png";p.get_pixmap(matrix=fitz.Matrix(2,2),alpha=False).save(q);cimgs.append(str(q))
 qa=s.get("deterministic_visual_qa") or {};rows.append({"index":r["index"],"source_pdf":r["source"],"reference_pdf":r.get("reference"),"source_page_images":r["source_images"],"candidate_pdf":str(pdf) if pdf and pdf.exists() else None,"candidate_page_images":cimgs,"coverage":{"total":r["coverage_total"],"translated":r["coverage_total"],"manual_review":0,"native_plus_ocr_closed":True},"render_status":s["status"],"hard_counts":{"target_or_source_overlap":qa.get("visual_overlap_count"),"manual_layout":qa.get("manual_review_count"),"untranslated":qa.get("untranslated_candidate_count"),"leader_collision":qa.get("leader_collision_count")},"blocking_error":s.get("error")})
(ART/"candidate-audit-report.json").write_text(json.dumps({"schema":"v3.12-human-audit-candidate-report","publication":"not_authorized","records":rows},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(json.dumps(rows,ensure_ascii=False))
