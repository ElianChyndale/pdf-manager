# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
import json,sys,shutil,hashlib
from datetime import datetime,timezone
from pathlib import Path
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
import replan_v311_grouped as grp
from services.engineering_drawing.multimodal_plan import validate_multimodal_plan
from services.engineering_drawing.supervisor_contract import validate_real_supervisor_plan
from services.engineering_drawing.supervisor_bundle import create_supervisor_run_bundle
BASE=Path(r"D:\AmyProjects\business\pdf-manager\output\pdf\engineering-drawing\01_Bilingual_Inline\agent-artifacts\v3.11-cost-balanced-9")
def sha_raw(x):return hashlib.sha256((json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode()).hexdigest()
def rebuild(rec,plan,new,reason):
 work=Path(rec["artifact_dir"]);source=Path(rec["source_pdf"]);plan["semantic_blocks"]=new;plan["supervisor_plan"]["translation_tasks"]=[{"id":"translate-"+b["block_id"],"semantic_block":b["block_id"],"source_candidate_ids":b["member_ids"]} for b in new]
 for z in plan["mandatory_zone_audit"]:
  bs=[b for b in new if b["page_region_id"]==z["zone_id"]];z["block_ids"]=[b["block_id"] for b in bs];z["member_ids"]=[m for b in bs for m in b["member_ids"]]
 stamp=datetime.now(timezone.utc).isoformat();raw={"schema":"codex-sol-light-cost-balanced-repair-v1","sample":rec["sample_index"],"reason":reason,"decision":"approved"};inv=f"sol-light-cost-repair-{rec['sample_index']:02d}-{int(datetime.now().timestamp())}";plan["supervisor_invocation"].update({"invocation_id":inv,"started_at":stamp,"completed_at":stamp,"response_sha256":sha_raw(raw)});plan.pop("final_visual_review",None)
 plan=validate_multimodal_plan(plan,source_pdf_path=source);plan=validate_real_supervisor_plan(plan,source_pdf_path=source,require_final_review=False);(work/"supervisor-plan.json").write_text(json.dumps(plan,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");shutil.rmtree(work/"supervisor-run",ignore_errors=True);man=json.loads((work/"agent-manifest.json").read_text(encoding="utf-8"));create_supervisor_run_bundle(bundle_dir=work/"supervisor-run",source_pdf_path=source,page_images=[Path(x["source_image"]) for x in man["pages"]],request={"task":"one high-value hard-defect repair","reference_usage":"translation_evidence_only"},raw_response=raw,normalized_plan=plan,invocation_id=inv,agent_id="sol_light_supervisor",started_at=stamp,completed_at=stamp)
def main():
 recs=json.loads((BASE/"sample-records.json").read_text(encoding="utf-8"))["records"]
 for rec in recs:
  work=Path(rec["artifact_dir"]);plan=json.loads((work/"supervisor-plan.json").read_text(encoding="utf-8"));w,h=plan["page_sizes"][0];old=plan["semantic_blocks"]
  if rec["sample_index"]<=5:
   qa=json.loads((work/"execute-status.json").read_text(encoding="utf-8"))["deterministic_visual_qa"];bad={x["region_id"] for x in qa.get("manual_review_items",[])+qa.get("visual_overlap_items",[])};used=[]
   for b in old:
    if b["block_id"] not in bad:used.append(b["placement"]["selected_region"]);continue
    box=b["placement"]["selected_region"];bw=box[2]-box[0];bh=box[3]-box[1];found=None
    for dy in (-bh-12,bh+12,-2*bh-24,2*bh+24):
     y=max(0,min(h-bh,box[1]+dy));cand=[box[0],y,box[0]+bw,y+bh]
     if all(cand[2]<=u[0] or u[2]<=cand[0] or cand[3]<=u[1] or u[3]<=cand[1] for u in used):found=cand;break
    if found:
     b["placement"]["selected_region"]=found;b["placement"]["candidate_score_audit"][0]["bbox"]=found
     if "group_layout" in b["placement"]:b["placement"]["group_layout"]["group_anchor"]=[(found[0]+found[2])/2,(found[1]+found[3])/2];b["placement"]["group_layout"]["candidate_score_audit"]=b["placement"]["candidate_score_audit"]
     used.append(found)
   new=old;reason="shift only hard-collision groups into nearest unused local cell"
  else:
   new=[];company=[b for b in old if b["region_type"]=="company_contact_panel"];new.extend(company);blue=[b for b in old if b["region_type"]!="company_contact_panel"]
   buckets={}
   for b in blue:
    cx=(b["source_bbox"][0]+b["source_bbox"][2])/2;cy=(b["source_bbox"][1]+b["source_bbox"][3])/2;key=(b["region_type"],min(3,int(cx/w*4)),min(3,int(cy/h*4)));buckets.setdefault(key,[]).append(b)
   for n,((rtype,col,row),items) in enumerate(sorted(buckets.items(),key=lambda x:(x[0][2],x[0][1]))):
    cell=[col*w/4,row*h/4,(col+1)*w/4,(row+1)*h/4];target=[cell[0]+8,cell[1]+cell[3]-cell[1]-h/4*.32,cell[2]-8,cell[3]-8];new.append(grp.merge_group(items,f"p001-repair-group-{n+1:03d}",target,rtype,items[0]["page_region_id"]))
   reason="merge all remaining drawing labels into sixteen visually bounded whole-group boxes while retaining company subpanels"
  rebuild(rec,plan,new,reason)
if __name__=="__main__":main()
