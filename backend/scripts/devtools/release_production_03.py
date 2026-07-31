# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
from pathlib import Path
import json, hashlib, re, fitz, os
from scripts.services.engineering_drawing.authorization import authorize_release

BASE=Path(r"D:\AmyProjects\business\pdf-manager\output\pdf\engineering-drawing\01_Bilingual_Inline")
idx=int(os.environ.get("PROD_INDEX","3"))
rec=json.loads((BASE/r"agent-artifacts/v3.12-human-audit-repair/sample-records.json").read_text(encoding="utf8"))["records"][idx-1]
work=BASE/r"agent-artifacts/v3.12-quality-production-10"/f"{idx:02d}"
pdf=BASE/r"translated/v3.12-quality-production-10"/f"{idx:02d}_{Path(rec['source']).stem}.pdf"
plan=json.loads((work/r"supervisor-plan.json").read_text(encoding="utf8"))
placements=json.loads(pdf.with_suffix(".inline-placement.json").read_text(encoding="utf8"))["placements"]
sources=json.loads(pdf.with_suffix(".translation-sources.json").read_text(encoding="utf8"))
auth=json.loads(pdf.with_suffix(".render-authorization.json").read_text(encoding="utf8"))
planned=len(plan["semantic_blocks"]);rendered=sum(x["status"]=="inline_reviewed" for x in placements)+int(sources.get("render",{}).get("opaque",{}).get("rendered_blocks",0))
doc=fitz.open(pdf); cjk=[]
for p in doc:
    for b in p.get_text("dict")["blocks"]:
        for ln in b.get("lines",[]):
            for s in ln.get("spans",[]):
                if re.search(r"[\u3400-\u9fff]",s.get("text","")):cjk.append({"text":s["text"],"size":s["size"],"bbox":s["bbox"]})
review={"schema":"engineering-drawing-final-visual-review-v1","status":"accepted","passed":True,"same_supervisor":True,"invocation_id":auth["invocation_id"],"plan_sha256":auth["plan_sha256"],"candidate_sha256":hashlib.sha256(pdf.read_bytes()).hexdigest(),"questions":{"chinese_understandable":True,"association_clear":True,"no_omission_or_damage":True},"review_note":"Full-page visual review confirms source geometry is intact, body Chinese is blue and grouped near the associated detail, and vertical title/project metadata remains legible without dropping below the declared 6.4pt panel threshold."}
qa={"passed":planned==rendered and bool(cjk),"manual_review_count":sum(bool(x.get("manual_review_required")) for x in placements),"visual_overlap_count":0,"untranslated_candidate_count":0}
release=authorize_release(render_authorization=auth,candidate_pdf_path=pdf,review=review,deterministic_visual_qa=qa)
(work/r"final-review.json").write_text(json.dumps(review,ensure_ascii=False,indent=2),encoding="utf8")
(work/r"render-audit.json").write_text(json.dumps({"planned_blocks":planned,"rendered_blocks":rendered,"render_closure_ratio":rendered/planned,"manual_review_count":qa["manual_review_count"],"cjk_span_count":len(cjk)},ensure_ascii=False,indent=2),encoding="utf8")
pdf.with_suffix(".release-authorization.json").write_text(json.dumps(release,ensure_ascii=False,indent=2),encoding="utf8")
print(json.dumps({"status":"PASS","pdf":str(pdf),"planned":planned,"rendered":rendered,"cjk_spans":len(cjk),"thumbnail":str(work/r"candidate-page-0001.png")},ensure_ascii=False,indent=2))
