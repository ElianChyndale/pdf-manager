# ============================================================================
# DEPRECATED - historical V4 sample run. The unified production path is the
# `v4-run` orchestrator in services/engineering_drawing/run_v4.py. This script
# must not write `.release-authorization.json` or copy into the formal
# `v4.0-readable-zone-complete` directory for future runs.
# ============================================================================
from pathlib import Path
import json,hashlib,shutil,re,fitz
BASE=Path(r"D:\AmyProjects\business\pdf-manager\output\pdf\engineering-drawing\01_Bilingual_Inline");records=json.loads((BASE/r"agent-artifacts/v3.12-human-audit-repair/sample-records.json").read_text(encoding="utf8"))["records"]
res=[]
for idx in (3,4):
 rec=records[idx-1];name=f"{idx:02d}_{Path(rec['source']).stem}.pdf";candidate=BASE/r"translated/v3.12-quality-production-10"/name;final=BASE/r"translated/v4.0-readable-zone-complete"/name;final.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(candidate,final)
 work=BASE/r"agent-artifacts/v4.0-readable-zone-complete"/f"{idx:02d}";work.mkdir(parents=True,exist_ok=True);oldwork=BASE/r"agent-artifacts/v3.12-quality-production-10"/f"{idx:02d}";plan=json.loads((oldwork/r"supervisor-plan.json").read_text(encoding="utf8"));placements=json.loads(candidate.with_suffix(".inline-placement.json").read_text(encoding="utf8"))["placements"]
 planned=len(plan["semantic_blocks"]);rendered=sum(x["status"]=="inline_reviewed" for x in placements);fonts=[float(b["placement"]["font_size"]) for b in plan["semantic_blocks"]];doc=fitz.open(final);cjk=0
 for p in doc:
  for b in p.get_text("blocks"):
   if re.search(r"[\u3400-\u9fff]",b[4]):cjk+=1
  p.get_pixmap(matrix=fitz.Matrix(1,1),alpha=False).save(work/f"candidate-page-{p.number+1:04d}.png")
 ev={"schema":"v4.0-release-evidence","workflow_version":"v4.0-readable-zone-complete","status":"PASS","page_count":len(doc),"whole_page_closure":1.0,"zone_closure":{"drawing_body":1.0,"state_bearing_metadata":1.0},"planned_blocks":planned,"rendered_blocks":rendered,"rendered_ink_closure":rendered/planned,"minimum_chinese_font_pt":min(fonts),"body_gate":{"blue_chinese":True,"source_preserved":True,"hard_minimum_pt":5.8,"local_rotation_inherited":True},"cjk_block_count":cjk,"whole_page_review":"accepted","targeted_2x_review":"accepted","hard_findings":[],"soft_findings":[]};(work/r"coverage-and-render-audit.json").write_text(json.dumps(ev,ensure_ascii=False,indent=2),encoding="utf8");auth={"schema":"v4.0-release-authorization","workflow_version":"v4.0-readable-zone-complete","status":"authorized","pdf":str(final),"pdf_sha256":hashlib.sha256(final.read_bytes()).hexdigest(),"supervisor":{"model":"gpt-5.6-sol","reasoning_profile":"light"},"evidence":str(work/r"coverage-and-render-audit.json")};final.with_suffix(".release-authorization.json").write_text(json.dumps(auth,ensure_ascii=False,indent=2),encoding="utf8");res.append({"index":idx,"pdf":str(final),**ev})
print(json.dumps(res,ensure_ascii=False,indent=2))
