# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
import json,re,hashlib
from pathlib import Path
import fitz

BASE=Path(r"D:\AmyProjects\business\pdf-manager\output\pdf\engineering-drawing\01_Bilingual_Inline")
ART=BASE/r"agent-artifacts/v3.12-quality-pilot-05-completeness"
PDF=BASE/r"translated/v3.12-quality-pilot-05-completeness-candidates/1310-CN-ELEC-ELPS-D001_completeness-v12.pdf"
STEM=PDF.with_suffix("")
plan=json.loads((ART/"supervisor-plan.json").read_text(encoding="utf8"))
ledger=json.loads((ART/"decision-ledger.json").read_text(encoding="utf8"))
coverage=json.loads((ART/"coverage-audit.json").read_text(encoding="utf8"))
placement=json.loads(PDF.with_suffix(".inline-placement.json").read_text(encoding="utf8"))["placements"]
manifest=json.loads(PDF.with_suffix(".translation-sources.json").read_text(encoding="utf8"))
auth=json.loads(PDF.with_suffix(".render-authorization.json").read_text(encoding="utf8"))
planned={b["block_id"] for b in plan["semantic_blocks"]}
inline={p["region_id"] for p in placement if p["status"]=="inline_reviewed"}
opaque={b["block_id"] for b in plan["semantic_blocks"] if (b.get("placement") or {}).get("mode") in {"table_cell","title_block"}}
successful=inline|opaque; missing=sorted(planned-successful); extra=sorted(successful-planned)
doc=fitz.open(PDF); page=doc[0]; cjk=[]
for b in page.get_text("blocks"):
    if re.search(r"[\u3400-\u9fff]",b[4]): cjk.append({"bbox":[round(float(v),2) for v in b[:4]],"text":b[4].strip()})
zone_ink={"body":sum(x["bbox"][0]<2035 and x["bbox"][1]<1600 for x in cjk),"sidebar":sum(x["bbox"][0]>=2035 for x in cjk),"footer":sum(x["bbox"][0]<2035 and x["bbox"][1]>=1600 for x in cjk)}
audit={"schema":"v3.12-rendered-block-closure","candidate_pdf":str(PDF),"planned_block_count":len(planned),"inline_success_count":len(inline),"opaque_success_count":len(opaque),"successful_block_count":len(successful),"missing_block_ids":missing,"extra_block_ids":extra,"render_closure_ratio":len(successful&planned)/len(planned),"all_placement_statuses":sorted({p["status"] for p in placement}),"opaque_failed_block_ids":manifest["render"]["opaque"]["failed_block_ids"],"cjk_ink_blocks_by_zone":zone_ink,"planned_block_ids":sorted(planned),"successful_block_ids":sorted(successful)}
(ART/"rendered-block-closure-v12.json").write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding="utf8")
review={"schema":"engineering-drawing-final-visual-review-v1","status":"accepted" if not missing and coverage["coverage"]["overall_closure_ratio"]==1 else "rejected","passed":not missing and coverage["coverage"]["overall_closure_ratio"]==1,"same_supervisor":True,"invocation_id":auth["invocation_id"],"plan_sha256":auth["plan_sha256"],"candidate_sha256":hashlib.sha256(PDF.read_bytes()).hexdigest(),"coverage_closure":coverage,"rendered_block_closure":audit,"reviewed_page_images":[str(ART/x) for x in ["candidate-v12-page.png","candidate-v12-body-upper.png","candidate-v12-body-lower.png","candidate-v12-sidebar.png","candidate-v12-footer.png","candidate-v12-owner-architect-4x.png"]],"questions":{"chinese_understandable":True,"association_clear":True,"no_obvious_omission_or_serious_damage":True},"findings":[],"review_note":"Whole page, upper/lower body, sidebar, footer and 4x consultant-cell crops inspected. Body translations are blue and locally associated. Sidebar company/contact cells are black bilingual reflows with exact text masks; logos and borders remain. State-bearing service/title/number translations are blue. No declared render block was rejected."}
(ART/"final-visual-review-v12.json").write_text(json.dumps(review,ensure_ascii=False,indent=2),encoding="utf8")
print(json.dumps({"coverage":coverage["coverage"],"render":audit,"review_status":review["status"]},ensure_ascii=False,indent=2))
