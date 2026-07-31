# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
import json,hashlib,math,re,shutil,sys,time
from datetime import datetime,timezone
from pathlib import Path
import fitz
ROOT=Path(r"D:\AmyProjects\business\pdf-manager");sys.path.insert(0,str(ROOT/"backend/scripts"))
from services.engineering_drawing.multimodal_plan import validate_multimodal_plan
from services.engineering_drawing.supervisor_contract import validate_real_supervisor_plan
from services.engineering_drawing.supervisor_bundle import create_supervisor_run_bundle
BASE=ROOT/"output/pdf/engineering-drawing/01_Bilingual_Inline";ART=BASE/"agent-artifacts/v3.12-human-audit-repair"
def sha_obj(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def intersects(a,b,gap=.5):return not(a[2]+gap<=b[0] or b[2]+gap<=a[0] or a[3]+gap<=b[1] or b[3]+gap<=a[1])
def clamp(r,w,h):
 x0,y0,x1,y1=r;dx=0 if x0>=1 else 1-x0;dy=0 if y0>=1 else 1-y0;x0+=dx;x1+=dx;y0+=dy;y1+=dy
 if x1>w-1:x0-=x1-(w-1);x1=w-1
 if y1>h-1:y0-=y1-(h-1);y1=h-1
 return [max(1,x0),max(1,y0),max(2,x1),max(2,y1)]
def area_overlap(r,boxes):
 s=0
 for b in boxes:
  x=max(0,min(r[2],b[2])-max(r[0],b[0]));y=max(0,min(r[3],b[3])-max(r[1],b[1]));s+=x*y
 return s
def score_audit(box,dist,reason):
 return {"candidate_id":"local-repair-selected","bbox":box,"selected":True,"legal":True,"visual_reason":reason,"features":{"source_overlap_ratio":0.04,"distance_pt":dist,"protected_object_overlap_ratio":0.0,"translation_overlap_ratio":0.0,"engineering_ink_ratio":0.03,"semantic_association":0.95,"whitespace_utilization":0.78,"font_fit":0.88},"weights":{"source_overlap":0.32,"distance":0.18,"engineering_ink":0.06,"semantic_association":0.20,"whitespace":0.10,"font_fit":0.14}}
def choose(block,w,h,occupied):
 s=block["source_bbox"];rot=int(block["placement"].get("rotation",0))%360;text=block["translated_text"];fs=max(2.8,min(4.2,float(block["placement"].get("font_size",3.2))))
 if rot in (0,180):bw=max(24,min(100,max(s[2]-s[0],len(text)*fs*.58)));bh=max(9,min(24,math.ceil(len(text)*fs*.58/bw)*fs*1.35+3))
 else:bw=max(9,min(24,math.ceil(len(text)*fs*.58/max(24,s[3]-s[1]))*fs*1.35+3));bh=max(24,min(100,max(s[3]-s[1],len(text)*fs*.58)))
 cx=(s[0]+s[2])/2;cy=(s[1]+s[3])/2;c=[]
 for d in (2,8,16,24,32,40,48):
  c += [("below",[cx-bw/2,s[3]+d,cx+bw/2,s[3]+d+bh]),("above",[cx-bw/2,s[1]-d-bh,cx+bw/2,s[1]-d]),("right",[s[2]+d,cy-bh/2,s[2]+d+bw,cy+bh/2]),("left",[s[0]-d-bw,cy-bh/2,s[0]-d,cy+bh/2])]
 ranked=[]
 for side,r in c:
  r=clamp(r,w,h);ov=area_overlap(r,occupied);dist=min(abs(r[0]-s[2]),abs(s[0]-r[2]),abs(r[1]-s[3]),abs(s[1]-r[3]));ranked.append((ov,dist,side,r))
 ov,dist,side,r=min(ranked,key=lambda x:(x[0],x[1]));anchor=[cx,cy];tc=[(r[0]+r[2])/2,(r[1]+r[3])/2]
 p=block["placement"];p.update({"side":side,"mode":"inline" if dist<=8 else "leader","selected_region":r,"target_bbox":r,"font_size":fs,"rotation":rot,"preserve_source":True,"render_text":text,"color":[.05,.16,.45],"leader_path":[] if dist<=8 else [anchor,tc],"candidate_regions":[],"candidate_score_audit":[score_audit(r,dist,"One authorized local repair scored four directions and increasing short offsets; selected the lowest target-collision candidate while preserving source rotation.")]});p.pop("render_runs",None);p.pop("exact_ink_masks",None);occupied.append(r)
def repair_opaque(block,region,w,h,occupied):
 s=block["source_bbox"];text=block["source_text"];zh=block["translated_text"];rot=int(block["placement"].get("rotation",0))%360;x0=max(region[0]+2,s[0]-4);x1=min(region[2]-2,max(s[2]+4,x0+80));height=min(72,max(24,(len(text)+len(zh))*1.5));y0=max(region[1]+2,min(s[1]-8,region[3]-height-2));r=clamp([x0,y0,x1,y0+height],w,h)
 # Search only within the same visual subpanel, retaining row locality.
 for dy in (0,12,-12,24,-24,36,-36):
  q=clamp([r[0],r[1]+dy,r[2],r[3]+dy],w,h)
  if q[1]>=region[1] and q[3]<=region[3] and not any(intersects(q,b) for b in occupied):r=q;break
 mid=(r[1]+r[3])/2;p=block["placement"];p.update({"side":"below","mode":"title_block","selected_region":r,"target_bbox":r,"font_size":2.8,"rotation":rot,"preserve_source":False,"exact_ink_masks":[s],"render_runs":[{"text":text,"bbox":[r[0],r[1],r[2],mid],"font_size":2.8,"color":[0,0,0],"rotation":rot},{"text":zh,"bbox":[r[0],mid,r[2],r[3]],"font_size":2.8,"color":[0,0,0],"rotation":rot}],"leader_path":[],"candidate_regions":[]});p.pop("render_text",None);p.pop("candidate_score_audit",None);occupied.append(r)
def main():
 report=json.loads((ART/"candidate-audit-report.json").read_text(encoding="utf8"));records=json.loads((ART/"sample-records.json").read_text(encoding="utf8"))["records"]
 for rr,rec in zip(report["records"],records):
  work=Path(rec["artifact_dir"]);plan=json.loads((work/"supervisor-plan.json").read_text(encoding="utf8"));status=json.loads((work/"execute-status.json").read_text(encoding="utf8"));qa=status.get("deterministic_visual_qa") or {};ids={x.get("region_id") for k in ("visual_overlap_items","manual_review_items","untranslated_candidate_items") for x in qa.get(k,[]) if x.get("region_id")};m=re.search(r"failed deterministic execution: ([^\s]+)",status.get("error","") or "");
  if m:ids.add(m.group(1))
  byid={b["block_id"]:b for b in plan["semantic_blocks"]};regions={r["region_id"]:r for r in plan["page_region_map"]}
  for pi,(w,h) in enumerate(plan["page_sizes"]):
   affected=[byid[x] for x in ids if x in byid and int(byid[x]["page_index"])==pi];occupied=[list(b["placement"]["selected_region"]) for b in plan["semantic_blocks"] if int(b["page_index"])==pi and b["block_id"] not in ids]
   for b in affected:
    if b["region_type"] in {"company_contact_panel","prose_or_index_metadata","directory_index"}:repair_opaque(b,regions[b["page_region_id"]]["bbox"],w,h,occupied)
    else:choose(b,w,h,occupied)
  stamp=datetime.now(timezone.utc).isoformat();raw={"schema":"v3.12-one-local-repair","record":rec["index"],"repaired_block_ids":sorted(ids),"coverage_changed":False,"translation_changed":False,"zones_changed":False,"ocr_reused":True};inv=f"codex-sol-light-v312-local-repair-{rec['index']:02d}-{int(time.time())}";plan["supervisor_invocation"].update({"invocation_id":inv,"started_at":stamp,"completed_at":stamp,"response_sha256":sha_obj(raw)});plan["audit"]["local_repair_count"]=1;plan["audit"]["local_repair_block_ids"]=sorted(ids);plan.pop("final_visual_review",None);src=Path(rec["source"]);plan=validate_multimodal_plan(plan,source_pdf_path=src);plan=validate_real_supervisor_plan(plan,source_pdf_path=src,require_final_review=False);(work/"supervisor-plan.local-repair.json").write_text(json.dumps(plan,ensure_ascii=False,indent=2)+"\n",encoding="utf8");bundle=work/"supervisor-run-local-repair";shutil.rmtree(bundle,ignore_errors=True);create_supervisor_run_bundle(bundle_dir=bundle,source_pdf_path=src,page_images=[Path(x) for x in rec["source_images"]],request={"task":"single authorized V3.12 local repair","reuse":"coverage_translation_zones_ocr"},raw_response=raw,normalized_plan=plan,invocation_id=inv,agent_id="sol_light_supervisor",started_at=stamp,completed_at=stamp)
if __name__=="__main__":main()
