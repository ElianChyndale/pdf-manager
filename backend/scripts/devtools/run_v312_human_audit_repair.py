# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
import argparse,json,sys,shutil
from pathlib import Path
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
import run_verified_samples as run
ROOT=run.SAMPLE_ROOT
run.ARTIFACT_ROOT=ROOT/"agent-artifacts/v3.12-human-audit-repair"
run.CANDIDATE_ROOT=ROOT/"translated/v3.12-human-audit-repair-candidates"
run.RELEASE_ROOT=ROOT/"translated/v3.12-human-audit-repair"
run.RECORDS_PATH=run.ARTIFACT_ROOT/"sample-records.json"
def load_records():
 data=json.loads(run.RECORDS_PATH.read_text(encoding="utf-8"))["records"]
 return [{**x,"sample_index":x["index"],"source_pdf":x["source"]} for x in data]
run.load_records=load_records
def execute_from_bound_evidence():
 out=[]
 for x in load_records():
  work=Path(x["artifact_dir"]);old=Path(x["old"]).parent;source=Path(x["source_pdf"]);status={"sample_index":x["sample_index"],"source_pdf":str(source),"status":"started"}
  try:
   shutil.copy2(old/"agent-manifest.json",work/"agent-manifest.json");(work/"ocr").mkdir(exist_ok=True)
   if (old/"ocr/ocr.json").exists(): shutil.copy2(old/"ocr/ocr.json",work/"ocr/ocr.json")
   else: raise RuntimeError("bound prior OCR evidence missing")
   plan=run.validate_real_supervisor_plan(json.loads((work/"supervisor-plan.json").read_text(encoding="utf-8")),source_pdf_path=source,require_final_review=False)
   candidate=run.CANDIDATE_ROOT/(x["slug"]+".pdf");candidate.parent.mkdir(parents=True,exist_ok=True)
   ok,msg=run.command(["v3-render","--source",str(source),"--plan",str(work/"supervisor-plan.json"),"--regions-json",str(work/"ocr/ocr.json"),"--output",str(candidate),"--agent-manifest",str(work/"agent-manifest.json"),"--supervisor-bundle",str(work/"supervisor-run")])
   if not ok: raise RuntimeError(msg)
   audit=candidate.with_suffix(".inline-placement.json");status.update({"status":"candidate_ready_for_joint_review","candidate_pdf":str(candidate),"placement_audit":str(audit),"coverage":{"total":len(plan["coverage_inventory"]),"translated":sum(z["status"]=="translated" for z in plan["coverage_inventory"]),"manual_review":sum(z["status"]=="manual_review" for z in plan["coverage_inventory"])},"deterministic_visual_qa":run.analyze_visual_qa(output_pdf_path=candidate,placement_audit_path=audit)})
  except Exception as e:status.update({"status":"blocked","error":str(e)})
  run.write_json(work/"execute-status.json",status);out.append(status)
 run.write_json(run.ARTIFACT_ROOT/"execute-summary.json",{"records":out});return out
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--phase",choices=("execute","publish"),required=True);a=p.parse_args();print(execute_from_bound_evidence() if a.phase=="execute" else run.publish())
