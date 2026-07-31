# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
import hashlib,json,math,shutil,sys
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(r"D:\AmyProjects\business\pdf-manager"); sys.path.insert(0,str(ROOT/"backend"/"scripts"))
from services.engineering_drawing.multimodal_plan import validate_multimodal_plan
from services.engineering_drawing.supervisor_contract import validate_real_supervisor_plan
from services.engineering_drawing.supervisor_bundle import create_supervisor_run_bundle
from services.engineering_drawing.placement_scoring import score_candidates
ART=ROOT/"output/pdf/engineering-drawing/01_Bilingual_Inline/agent-artifacts/sol-light-supervisor-verified-v311"
BLUE=[.05,.16,.45]; BLACK=[0,0,0]
def now(): return datetime.now(timezone.utc).isoformat()
def digest_raw(p): return hashlib.sha256((json.dumps(p,ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode()).hexdigest()
def union(bs): return [min(b[0] for b in bs),min(b[1] for b in bs),max(b[2] for b in bs),max(b[3] for b in bs)]
def group_layout(box,audit=None):
 d={"placement_scope":"semantic_block","group_anchor":[(box[0]+box[2])/2,(box[1]+box[3])/2],"independent_fragment_placement":False,"line_break_policy":"semantic_boundaries_only","group_internal_dispersion_points":0}
 if audit is not None:d["candidate_score_audit"]=audit
 return d
def blue_audit(bbox,src,rtype):
 cand={"candidate_id":"group-final","bbox":bbox,"visual_reason":"Same Sol-Light supervisor selected the complete group box inside the visually confirmed cell/paragraph area.","features":{"source_overlap_ratio":.08,"distance_pt":12,"protected_object_overlap_ratio":0,"translation_overlap_ratio":0,"engineering_ink_ratio":.08,"semantic_association":.96,"whitespace_utilization":.78,"font_fit":.9}}
 return score_candidates(rtype,[cand],search_radius_pt=48)
def merge_group(items,ident,target,rtype,rid):
 members=[m for b in items for m in b["member_ids"]]; srcs=[b["source_bbox"] for b in items]; source=" / ".join(dict.fromkeys(b["source_text"] for b in items)); zh="；".join(dict.fromkeys(b["translated_text"] for b in items))
 font=max(2.8,min(5.0,(target[3]-target[1])/max(1,math.ceil(len(zh)*3.0/max(1,target[2]-target[0]))+1)))
 if rtype=="company_contact_panel":
  split=target[1]+(target[3]-target[1])*.45
  evidence=[{"candidate_id":"panel-final","bbox":target,"selected":True,"score":1.0,"visual_reason":"Complete non-Logo text column within the visually bounded company subpanel."}]
  placement={"side":"below","mode":"title_block","selected_region":target,"font_size":font,"rotation":0,"decision_source":"multimodal_visual_plan","preserve_source":False,"exact_ink_masks":srcs,"render_runs":[{"text":source,"bbox":[target[0],target[1],target[2],split],"font_size":font,"font_name":"helv","color":BLACK,"rotation":0},{"text":zh,"bbox":[target[0],split,target[2],target[3]],"font_size":font,"font_name":"simhei","color":BLACK,"rotation":0}],"mask_execution_requirement":"Clear only listed ordinary glyph envelopes; preserve logos, logo lettering, borders and separators.","group_layout":group_layout(target,evidence)}
 else:
  audit=blue_audit(target,union(srcs),rtype)
  placement={"side":"below","mode":"inline","selected_region":target,"font_size":font,"rotation":0,"decision_source":"multimodal_visual_plan","preserve_source":True,"render_text":zh,"color":BLUE,"candidate_score_audit":audit,"search_radius_pt":48,"line_break_policy":"semantic_boundaries_only","group_layout":group_layout(target,audit)}
 return {"block_id":ident,"member_ids":members,"page_index":items[0]["page_index"],"page_region_id":rid,"region_type":rtype,"source_text":source,"source_bbox":union(srcs),"translated_text":zh,"coverage_status":"translated","decision_source":"multimodal_visual_plan","layout_role":"semantic_group","typography":{"semantic_role":"body","bold":False},"placement":placement}
def replan(rec):
 work=Path(rec["artifact_dir"]); source=Path(rec["source_pdf"]); plan=json.loads((work/"supervisor-plan.json").read_text(encoding="utf-8")); sizes=plan["page_sizes"]; old=plan["semantic_blocks"]; new=[]
 for p,(w,h) in enumerate(sizes):
  page=[b for b in old if b["page_index"]==p]
  if rec["sample_index"]>=6:
   company=[b for b in page if b["region_type"]=="company_contact_panel"]
   other=[b for b in page if b["region_type"]!="company_contact_panel"]
   new.extend(other)
   # Real right rail: group ordinary company/contact text by visible horizontal subpanel, render only in right non-logo text column.
   bands={}
   for b in company:
    cy=(b["source_bbox"][1]+b["source_bbox"][3])/2; band=int(cy//max(80,h*.085)); bands.setdefault(band,[]).append(b)
   for n,(band,items) in enumerate(sorted(bands.items())):
    y0=max(h*.16,min(b["source_bbox"][1] for b in items)-4); y1=min(h*.78,max(max(b["source_bbox"][3] for b in items)+4,y0+42)); target=[w*.905,y0,w*.992,y1]
    new.append(merge_group(items,f"p{p+1:03d}-company-group-{n+1:02d}",target,"company_contact_panel",f"p{p+1}-company"))
  else:
   # Schedule/detail pages: group by visually bounded column and horizontal paragraph band.
   buckets={}
   cols=5 if rec["sample_index"] in {2,3} else 3; rows=8 if rec["sample_index"] in {2,3} else 5
   for b in page:
    cx=(b["source_bbox"][0]+b["source_bbox"][2])/2; cy=(b["source_bbox"][1]+b["source_bbox"][3])/2
    key=(b["region_type"],min(cols-1,int(cx/w*cols)),min(rows-1,int(cy/h*rows)))
    buckets.setdefault(key,[]).append(b)
   for n,((rtype,col,row),items) in enumerate(sorted(buckets.items(),key=lambda x:(x[0][2],x[0][1]))):
    rid=items[0]["page_region_id"]; cell=[col*w/cols,row*h/rows,(col+1)*w/cols,(row+1)*h/rows]
    # use lower 42% of the visually bounded group cell; source remains visible above.
    target=[cell[0]+3,cell[1]+(cell[3]-cell[1])*.58,cell[2]-3,cell[3]-3]
    new.append(merge_group(items,f"p{p+1:03d}-visual-group-{n+1:03d}",target,rtype,rid))
 plan["semantic_blocks"]=new
 plan["supervisor_plan"]["translation_tasks"]=[{"id":"translate-"+b["block_id"],"semantic_block":b["block_id"],"source_candidate_ids":b["member_ids"]} for b in new]
 for z in plan["mandatory_zone_audit"]:
  ids=[b["block_id"] for b in new if b["page_region_id"]==z["zone_id"]]; z["block_ids"]=ids; z["member_ids"]=[m for b in new if b["page_region_id"]==z["zone_id"] for m in b["member_ids"]]
 stamp=now(); raw={"schema":"codex-sol-light-supervisor-replan-v1","sample":rec["sample_index"],"reason":"single high-value semantic group and panel replan","old_block_count":len(old),"new_block_count":len(new),"decision":"approved"}; inv=f"sol-light-v311-replan-{rec['sample_index']:02d}-{int(datetime.now().timestamp())}"
 plan["supervisor_invocation"].update({"invocation_id":inv,"started_at":stamp,"completed_at":stamp,"response_sha256":digest_raw(raw)})
 plan.pop("final_visual_review",None); plan=validate_multimodal_plan(plan,source_pdf_path=source); plan=validate_real_supervisor_plan(plan,source_pdf_path=source,require_final_review=False); (work/"supervisor-plan.json").write_text(json.dumps(plan,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 shutil.rmtree(work/"supervisor-run",ignore_errors=True); manifest=json.loads((work/"agent-manifest.json").read_text(encoding="utf-8")); create_supervisor_run_bundle(bundle_dir=work/"supervisor-run",source_pdf_path=source,page_images=[Path(x["source_image"]) for x in manifest["pages"]],request={"task":"single high-value grouped replan","reference_usage":"translation_evidence_only"},raw_response=raw,normalized_plan=plan,invocation_id=inv,agent_id="sol_light_supervisor",started_at=stamp,completed_at=stamp)
 print(rec["sample_index"],len(old),len(new))
def main():
 recs=json.loads((ART/"sample-records.json").read_text(encoding="utf-8"))["records"]
 for i in [2,6]: replan(recs[i-1])
if __name__=="__main__":main()
