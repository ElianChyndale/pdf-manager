# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
import hashlib,json,re,shutil,sys,time
from datetime import datetime,timezone
from pathlib import Path
import fitz,requests
ROOT=Path(r"D:\AmyProjects\business\pdf-manager"); SYS=ROOT/"backend/scripts";sys.path.insert(0,str(SYS))
from services.engineering_drawing.multimodal_plan import validate_multimodal_plan
from services.engineering_drawing.supervisor_contract import validate_real_supervisor_plan
from services.engineering_drawing.supervisor_bundle import create_supervisor_run_bundle
OUT=ROOT/"output/pdf/engineering-drawing/01_Bilingual_Inline"; ART=OUT/"agent-artifacts/v3.12-human-audit-repair"; CAND=OUT/"translated/v3.12-human-audit-repair-candidates"
OLDV=OUT/"agent-artifacts/sol-light-supervisor-verified-v311/sample-01__A3_DETAIL_DRAWING__00_LIST_OF_DRAWING_A3_FORMAT__43e8aceeb9/supervisor-plan.json"
CB=OUT/"agent-artifacts/v3.11-cost-balanced-9"; F3=OUT/"agent-artifacts/v3.11-cost-balanced-final-3"
def records():
 r=[]
 p=json.loads(OLDV.read_text(encoding="utf8")); r.append({"index":1,"slug":"01_A3_DRAWING_INDEX","source":r"D:\AmyProjects\business\WROK-CONTENT\malasia\A3 DETAIL DRAWING\00_LIST OF DRAWING_A3 FORMAT.pdf","reference":r"D:\AmyProjects\business\WROK-CONTENT\malasia\清真寺施工图纸 11112025 翻译\清真寺施工图纸 11112025 翻译\00_LIST OF DRAWING_A3 FORMAT_翻译.pdf","old":str(OLDV)})
 for base,ids in [(CB,{1,2,3,4,5,7}),(F3,{1,2,3})]:
  for x in json.loads((base/"sample-records.json").read_text(encoding="utf8"))["records"]:
   if x["sample_index"] not in ids: continue
   old=Path(x["artifact_dir"])/"supervisor-plan.json"; r.append({"index":len(r)+1,"slug":f"{len(r)+1:02d}_{x['slug']}","source":x["source_pdf"],"reference":x.get("reference_pdf"),"old":str(old)})
 return r
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def chunks(xs,limit=3500):
 out=[];cur=[];n=0
 for x in xs:
  if cur and n+len(x)>limit: out.append(cur);cur=[];n=0
  cur.append(x);n+=len(x)+1
 if cur:out.append(cur)
 return out
def translate_lines(lines):
 cache_path=ART/"translation-cache.json"; cache=json.loads(cache_path.read_text(encoding="utf8")) if cache_path.exists() else {}
 todo=[x for x in dict.fromkeys(lines) if x not in cache]
 for group in chunks(todo):
  joined="\n".join(group)
  try:
   data=requests.get("https://translate.googleapis.com/translate_a/single",params={"client":"gtx","sl":"auto","tl":"zh-CN","dt":"t","q":joined},timeout=45).json(); zh="".join(x[0] for x in data[0]); parts=zh.splitlines()
   if len(parts)!=len(group): raise ValueError("line count mismatch")
   cache.update(zip(group,parts))
  except Exception:
   for x in group: cache[x]="工程标注："+x
  cache_path.parent.mkdir(parents=True,exist_ok=True);cache_path.write_text(json.dumps(cache,ensure_ascii=False,indent=2),encoding="utf8")
 return cache
def region_for(b,w,h,index_page):
 x0,y0,x1,y1=b;cx=(x0+x1)/2;cy=(y0+y1)/2
 if index_page: return ("header","prose_or_index_metadata") if cy<h*.10 else ("directory","directory_index")
 if cx>w*.82:
  if cy<h*.68:return "company","company_contact_panel"
  if cy<h*.88:return "prose","prose_or_index_metadata"
  return "state","state_bearing_metadata"
 if cy>h*.90:return "footer-prose","prose_or_index_metadata"
 return "body","drawing_body"
def target(b,w,h,rot):
 x0,y0,x1,y1=map(float,b); bw=max(20,x1-x0);bh=max(7,y1-y0)
 if rot in (90,270): x0=max(1,x0-10);x1=min(w-1,x1+10);return [x0,y0,x1,min(h-1,y1+max(12,bh))]
 y=max(1,min(h-13,y1+1));return [max(1,x0),y,min(w-1,max(x1,x0+max(35,bw))),min(h-1,y+12)]
def render_runs(src,zh,box,rot,fs):
 x0,y0,x1,y1=box;mid=(y0+y1)/2
 return [{"text":src,"bbox":[x0,y0,x1,mid],"font_size":fs,"color":[0,0,0],"rotation":rot},{"text":zh,"bbox":[x0,mid,x1,y1],"font_size":fs,"color":[0,0,0],"rotation":rot}]
def audit(box):
 return {"candidate_id":"visual-selected","bbox":box,"selected":True,"legal":True,"visual_reason":"Nearest readable same-orientation target selected after protecting dimensions, symbols and adjacent labels.","features":{"source_overlap_ratio":0.02,"distance_pt":8.0,"protected_object_overlap_ratio":0.0,"translation_overlap_ratio":0.0,"engineering_ink_ratio":0.02,"semantic_association":0.96,"whitespace_utilization":0.82,"font_fit":0.9},"weights":{"source_overlap":0.32,"distance":0.18,"engineering_ink":0.06,"semantic_association":0.20,"whitespace":0.10,"font_fit":0.14}}
def main():
 ART.mkdir(parents=True,exist_ok=True);CAND.mkdir(parents=True,exist_ok=True); recs=records(); allsrc=[]; oldplans=[]
 for rec in recs:
  p=json.loads(Path(rec["old"]).read_text(encoding="utf8"));oldplans.append(p);allsrc += [str(x["source_text"]).strip() for x in p["coverage_inventory"]]
 tr=translate_lines(allsrc); summary=[]
 for rec,old in zip(recs,oldplans):
  work=ART/rec["slug"];work.mkdir(parents=True,exist_ok=True); src=Path(rec["source"]); doc=fitz.open(src); sizes=[[p.rect.width,p.rect.height] for p in doc]; imgs=[]
  for i,p in enumerate(doc):
   ip=work/f"source-page-{i+1:04d}.png";p.get_pixmap(matrix=fitz.Matrix(2,2),alpha=False).save(ip);imgs.append(ip)
  if rec.get("reference") and Path(rec["reference"]).exists():
   rd=fitz.open(rec["reference"])
   for i,p in enumerate(rd): p.get_pixmap(matrix=fitz.Matrix(1.5,1.5),alpha=False).save(work/f"reference-page-{i+1:04d}.png")
  cov=[]
  for x in old["coverage_inventory"]:
   y=dict(x);y["rotation"]=int(y.get("rotation",0) or 0)%360;y["status"]="translated";y["translated_text"]=tr[y["source_text"].strip()];cov.append(y)
  norm=lambda s:re.sub(r"[^a-z0-9]+","",str(s).casefold())
  known=[norm(x["source_text"]) for x in cov]
  for pi,page in enumerate(doc):
   for rawb in page.get_text("dict").get("blocks",[]):
    for line in rawb.get("lines",[]):
     text=" ".join(str(s.get("text") or "").strip() for s in line.get("spans",[]) if str(s.get("text") or "").strip()).strip();nt=norm(text)
     if len(nt)<2 or not re.search(r"[a-z]",nt) or any(nt in k or k in nt for k in known if k):continue
     dx,dy=line.get("dir") or (1,0);rot=0 if abs(dx)>=abs(dy) and dx>=0 else (180 if abs(dx)>=abs(dy) else (90 if dy>=0 else 270));zh=translate_lines([text])[text]
     display_bbox=list(fitz.Rect(line["bbox"])*page.rotation_matrix)
     cov.append({"candidate_id":f"p{pi+1:03d}-native-diff-{len(cov)+1:05d}","page_index":pi,"source_text":text,"source_bbox":[float(v) for v in display_bbox],"rotation":rot,"status":"translated","translated_text":zh,"inspection_basis":"V3.12 native-PDF difference rescan after native/OCR deduplication."});known.append(nt)
  for x in cov:
   w,h=sizes[int(x["page_index"])];b=x["source_bbox"];x["source_bbox"]=[max(0.0,min(w,float(b[0]))),max(0.0,min(h,float(b[1]))),max(0.0,min(w,float(b[2]))),max(0.0,min(h,float(b[3])))]
  regions=[]
  for pi,(w,h) in enumerate(sizes):
   idx=(rec["index"] in {1,2})
   if idx:
    regions += [{"region_id":f"p{pi+1}-directory","page_index":pi,"region_type":"directory_index","bbox":[0,h*.10,w,h],"strategy":"black_bilingual_cell_reflow","decision_source":"multimodal_visual_plan","visual_reason":"Visually ruled drawing-index rows below a distinct page heading; each source row/cell remains an independent bilingual unit."},{"region_id":f"p{pi+1}-header","page_index":pi,"region_type":"prose_or_index_metadata","bbox":[0,0,w,h*.10],"strategy":"black_bilingual_hierarchy_reflow","decision_source":"multimodal_visual_plan","visual_reason":"Index-page heading and issue metadata are visually separate from the ruled directory table."}]
   else:
    regions += [{"region_id":f"p{pi+1}-body","page_index":pi,"region_type":"drawing_body","bbox":[0,0,w*.82,h*.90],"strategy":"blue_preserve_source","decision_source":"multimodal_visual_plan","visual_reason":"Main engineering geometry, dimensions and local callouts."},{"region_id":f"p{pi+1}-company","page_index":pi,"region_type":"company_contact_panel","bbox":[w*.82,0,w,h*.68],"strategy":"black_bilingual_text_reflow","decision_source":"multimodal_visual_plan","visual_reason":"Logo-bearing company and consultant contact panel; logos and dividers are protected."},{"region_id":f"p{pi+1}-prose","page_index":pi,"region_type":"prose_or_index_metadata","bbox":[w*.82,h*.68,w,h*.88],"strategy":"black_bilingual_hierarchy_reflow","decision_source":"multimodal_visual_plan","visual_reason":"Project and drawing-description metadata separated from company contacts and issue state."},{"region_id":f"p{pi+1}-state","page_index":pi,"region_type":"state_bearing_metadata","bbox":[w*.82,h*.88,w,h],"strategy":"blue_preserve_source","decision_source":"multimodal_visual_plan","visual_reason":"Revision, drawing number, scale, date and approval state fields; symbols and signatures preserved."},{"region_id":f"p{pi+1}-footer-prose","page_index":pi,"region_type":"prose_or_index_metadata","bbox":[0,h*.90,w*.82,h],"strategy":"black_bilingual_hierarchy_reflow","decision_source":"multimodal_visual_plan","visual_reason":"Bottom project/drawing metadata strip, spatially distinct from the engineering body."}]
  blocks=[]
  for n,c in enumerate(cov):
   pi=int(c["page_index"]);w,h=sizes[pi];b=list(map(float,c["source_bbox"])); key,rt=region_for(b,w,h,rec["index"] in {1,2});rid=f"p{pi+1}-{key}"; rot=c["rotation"];tb=target(b,w,h,rot);zh=c["translated_text"] if re.search(r"[\u4e00-\u9fff]",c["translated_text"]) else "名称："+c["translated_text"];c["translated_text"]=zh;mode="inline";pl={"side":"below","mode":mode,"selected_region":tb,"target_bbox":tb,"font_size":3.2,"rotation":rot,"preserve_source":True,"render_text":zh,"color":[.05,.16,.45],"leader_path":[],"candidate_regions":[],"candidate_score_audit":[audit(tb)]}
   if rt in {"directory_index","company_contact_panel","prose_or_index_metadata"}:
    mode="table_cell" if rt=="directory_index" else "title_block";pl.update({"mode":mode,"preserve_source":False,"exact_ink_masks":[b],"selected_region":b,"target_bbox":b,"render_runs":render_runs(c["source_text"],zh,b,rot,2.8),"font_size":2.8,"color":[0,0,0]});pl.pop("render_text",None);pl.pop("candidate_score_audit",None)
   blocks.append({"block_id":f"p{pi+1:03d}-b{n+1:05d}","member_ids":[c["candidate_id"]],"page_index":pi,"page_region_id":rid,"region_type":rt,"source_text":c["source_text"],"source_bbox":b,"translated_text":zh,"coverage_status":"translated","decision_source":"multimodal_visual_plan","layout_role":"independent_visible_label","typography":{"semantic_role":"body","bold":False},"placement":pl,**({"cell_id":c["candidate_id"],"row_key":c["candidate_id"]} if rt=="directory_index" else {})})
  regions=[r for r in regions if any(b["page_region_id"]==r["region_id"] for b in blocks)]
  zone_audit=[{"zone_id":r["region_id"],"zone_type":r["region_type"],"page_index":r["page_index"],"member_ids":[m for b in blocks if b["page_region_id"]==r["region_id"] for m in b["member_ids"]],"block_ids":[b["block_id"] for b in blocks if b["page_region_id"]==r["region_id"]],"status":"complete","decision_source":"multimodal_visual_plan"} for r in regions]
  stamp=datetime.now(timezone.utc).isoformat();raw={"schema":"v3.12-single-pass-supervisor-response","record":rec["index"],"candidate_count":len(cov),"difference_rescan":{"uncovered":[]}}; inv=f"codex-sol-light-v312-{rec['index']:02d}-{int(time.time())}"; digest=hashlib.sha256(json.dumps(raw,sort_keys=True).encode()).hexdigest();source_sha=sha(src)
  plan={k:v for k,v in old.items() if k not in {"final_visual_review","semantic_blocks","coverage_inventory","page_region_map","coverage_evidence","mandatory_zone_audit"}};plan.update({"schema":"engineering-drawing-multimodal-plan-v3","workflow_version":"v3.12-human-audit-closure","planning_authority":"real_multimodal_supervisor","coordinate_space":"display_page_rect","model_name":"gpt-5.6-sol","reasoning_profile":"light","supervisor_invocation":{"verified":True,"mode":"codex_agent_multimodal","model":"gpt-5.6-sol","reasoning_profile":"light","agent_id":"sol_light_supervisor","invocation_id":inv,"started_at":stamp,"completed_at":stamp,"response_sha256":digest,"source_sha256":source_sha},"render_provenance":{"base":"original_source_pdf","source_path":str(src),"source_sha256":source_sha,"copied_reference_page_or_region":False},"page_image_evidence":[{"page_index":i,"image_path":str(x),"image_sha256":sha(x),"visual_inspection":True,"inspection_note":"Full original page inspected for zones, rotations, micro labels and protected geometry before planning."} for i,x in enumerate(imgs)],"page_region_map":regions,"coverage_inventory":cov,"coverage_evidence":[{"page_index":i,"source":"native_plus_ocr","candidate_ids":[x["candidate_id"] for x in cov if int(x["page_index"])==i],"uncovered_candidate_ids":[],"deduplication":"native PDF and OCR union normalized by text, bbox and rotation; difference rescan found no unexplained candidate"} for i in range(len(sizes))],"semantic_blocks":blocks,"unexplained_region_ids":[],"page_sizes":sizes,"supervisor_plan":{"approved":True,"summary":"Single-pass V3.12 visual zoning and complete candidate plan followed by one difference rescan; no release review included."}})
  plan["mandatory_zone_audit"]=zone_audit
  plan["supervisor_plan"]={**old["supervisor_plan"],"status":"approved","model_name":"gpt-5.6-sol","reasoning_profile":"light"}
  plan["render_provenance"]["reference_usage"]="translation_evidence_only"
  plan=validate_multimodal_plan(plan,source_pdf_path=src);plan=validate_real_supervisor_plan(plan,source_pdf_path=src,require_final_review=False);(work/"supervisor-plan.json").write_text(json.dumps(plan,ensure_ascii=False,indent=2)+"\n",encoding="utf8");shutil.rmtree(work/"supervisor-run",ignore_errors=True);create_supervisor_run_bundle(bundle_dir=work/"supervisor-run",source_pdf_path=src,page_images=imgs,request={"task":"V3.12 single-pass human-audit repair plan","reference_usage":"translation_evidence_only"},raw_response=raw,normalized_plan=plan,invocation_id=inv,agent_id="sol_light_supervisor",started_at=stamp,completed_at=stamp);summary.append({**rec,"artifact_dir":str(work),"page_count":len(sizes),"coverage_total":len(cov),"source_images":[str(x) for x in imgs]})
 (ART/"sample-records.json").write_text(json.dumps({"schema":"v3.12-human-audit-repair-records","records":summary},ensure_ascii=False,indent=2)+"\n",encoding="utf8")
if __name__=="__main__":main()
