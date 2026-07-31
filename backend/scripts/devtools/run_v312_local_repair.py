# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
import json,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
import run_verified_samples as run
ROOT=run.SAMPLE_ROOT;ART=ROOT/"agent-artifacts/v3.12-human-audit-repair";OUT=ROOT/"translated/v3.12-human-audit-repair-candidates/local-repair"
records=json.loads((ART/"sample-records.json").read_text(encoding="utf8"))["records"];results=[]
for x in records:
 work=Path(x["artifact_dir"]);src=Path(x["source"]);candidate=OUT/(x["slug"]+".pdf");candidate.parent.mkdir(parents=True,exist_ok=True);status={"sample_index":x["index"],"source_pdf":str(src),"status":"started"}
 try:
  ok,msg=run.command(["v3-render","--source",str(src),"--plan",str(work/"supervisor-plan.local-repair.json"),"--regions-json",str(work/"ocr/ocr.json"),"--output",str(candidate),"--agent-manifest",str(work/"agent-manifest.json"),"--supervisor-bundle",str(work/"supervisor-run-local-repair")])
  if not ok:raise RuntimeError(msg)
  audit=candidate.with_suffix(".inline-placement.json");qa=run.analyze_visual_qa(output_pdf_path=candidate,placement_audit_path=audit);status.update({"status":"candidate_ready_for_joint_review","candidate_pdf":str(candidate),"placement_audit":str(audit),"deterministic_visual_qa":qa})
 except Exception as e:status.update({"status":"blocked","error":str(e)})
 run.write_json(work/"local-repair-status.json",status);results.append(status)
run.write_json(ART/"local-repair-summary.json",{"records":results});print(json.dumps(results,ensure_ascii=False))
