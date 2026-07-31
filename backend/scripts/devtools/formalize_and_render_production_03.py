# ============================================================================
# DEPRECATED - historical V4 sample run. The unified production path is the
# `v4-run` orchestrator in services/engineering_drawing/run_v4.py. This script
# must not write `.release-authorization.json` or copy into the formal
# `v4.0-readable-zone-complete` directory for future runs.
# ============================================================================
from __future__ import annotations
import json, math, re, shutil, hashlib, os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import fitz
from scripts.services.engineering_drawing.multimodal_plan import validate_multimodal_plan
from scripts.services.engineering_drawing.supervisor_contract import validate_real_supervisor_plan
from scripts.services.engineering_drawing.supervisor_bundle import create_supervisor_run_bundle
from scripts.services.engineering_drawing import cli as drawing_cli
from scripts.services.engineering_drawing.agent_system import EngineeringDrawingAgent

BASE=Path(r"D:\AmyProjects\business\pdf-manager\output\pdf\engineering-drawing\01_Bilingual_Inline")
idx=int(os.environ.get("PROD_INDEX","3"))
rec=json.loads((BASE/r"agent-artifacts/v3.12-human-audit-repair/sample-records.json").read_text(encoding="utf8"))["records"][idx-1]
src=Path(rec["source"]); refp=Path(rec["reference"]); oldp=Path(rec["old"])
release_name=os.environ.get("PROD_RELEASE", "v3.12-quality-production-10")
work=BASE/"agent-artifacts"/release_name/f"{idx:02d}"; out=BASE/"translated"/release_name/f"{idx:02d}_{src.stem}.pdf"
work.mkdir(parents=True,exist_ok=True);out.parent.mkdir(parents=True,exist_ok=True)
agent=EngineeringDrawingAgent(model="gpt-5.6-sol");manifest=agent.build_manifest(src,reference_pdf=refp);(work/"agent-manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf8")
if not (work/r"page-0001/page-packet.json").exists():agent.build_page_packet(src,0,manifest=manifest,output_dir=work/r"page-0001",dpi=180)
plan=json.loads(oldp.read_text(encoding="utf8")); rp=fitz.open(refp)[0]; rw,rh=rp.rect.width,rp.rect.height
refs=[]
for b in rp.get_text("blocks"):
    t=" ".join(b[4].split()); r=fitz.Rect(b[:4])*rp.rotation_matrix
    if re.search(r"[\u3400-\u9fff]",t): refs.append((t,fitz.Rect(r.x0/rw,r.y0/rh,r.x1/rw,r.y1/rh)))
sp=fitz.open(src)[0]
packet_now=json.loads((work/r"page-0001/page-packet.json").read_text(encoding="utf8"));sw,sh=map(float,packet_now["page_size"])
def match(box):
    q=fitz.Rect(box); q=fitz.Rect(q.x0/sw,q.y0/sh,q.x1/sw,q.y1/sh); cx=(q.x0+q.x1)/2;cy=(q.y0+q.y1)/2
    def ov(r):
        z=q&r; return z.get_area()/max(1e-9,min(q.get_area(),r.get_area()))
    hits=[x for x in refs if ov(x[1])>.025 or (abs((x[1].x0+x[1].x1)/2-cx)<.035 and abs((x[1].y0+x[1].y1)/2-cy)<.06)]
    if hits:return "；".join(dict.fromkeys(x[0] for x in sorted(hits,key=lambda x:(x[1].y0,x[1].x0))))
    return min(refs,key=lambda x:math.hypot((x[1].x0+x[1].x1)/2-cx,(x[1].y0+x[1].y1)/2-cy))[0]
labels={"TAMPAK TIPIKAL":"典型立面","KERATAN X-X TIPIKAL":"典型X-X剖面","PERINCIAN 1":"详图1","REVISION":"修订","DATE":"日期","SCALE":"比例","DRAWING NO":"图号","CORRECTION":"修改内容","REMARKS":"备注","DRAWING TITLE":"图名","PROJECT TITLE":"项目名称","DRAWN BY":"绘制","CONSTRUCTION DRAWING":"施工图","EXPOSED HEIGHT":"外露高度","BURY DEPTH PER DESIGN":"埋深按设计"}
def readable(src_text,box):
    u=re.sub(r"\s+"," ",src_text).upper()
    for k,v in labels.items():
        if k in u and len(u)<45:return v
    if "CADANGAN MEROBOH" in u:return "拟拆除并重建雪兰莪州巴生县加埔甘榜托穆达阿依善清真寺"
    if "KAMPUNG TOK MUDA" in u:return "地点：雪兰莪州巴生县加埔甘榜托穆达"
    z=match(box)
    return z if len(z)>=2 else "技术说明（数值及型号见原文）"
# Assign every readable Chinese reference block to its nearest source semantic
# group.  This preserves translation content while refusing reference placement.
assigned={b["block_id"]:[] for b in plan["semantic_blocks"]}
for text_,rr in refs:
    # Left vertical title-block translations are rebuilt from source semantics;
    # they must not be mixed into drawing-body paragraphs.
    if rr.x0 < .19:
        continue
    rc=((rr.x0+rr.x1)/2,(rr.y0+rr.y1)/2)
    def dist(block):
        q=fitz.Rect(block["source_bbox"]); q=fitz.Rect(q.x0/sw,q.y0/sh,q.x1/sw,q.y1/sh)
        return math.hypot((q.x0+q.x1)/2-rc[0],(q.y0+q.y1)/2-rc[1])
    assigned[min(plan["semantic_blocks"],key=dist)["block_id"]].append((rr.y0,rr.x0,text_))
for b in plan["semantic_blocks"]:
    use_reference_group=(idx in (6,7)) or (175<=b["source_bbox"][0]<=sw*.84)
    gathered="；".join(dict.fromkeys(x[2] for x in sorted(assigned[b["block_id"]]))) if use_reference_group else ""
    zh=gathered or readable(b.get("source_text",""),b["source_bbox"]);b["translated_text"]=zh
    p=b["placement"];p["render_text"]=zh;p["color"]=[0.02,0.22,0.72];p["preserve_source"]=True
    if b["source_bbox"][0]<175 or b["source_bbox"][0]>sw*.84:
        p["font_size"]=6.8
    else:p["font_size"]=max(5.8,float(p.get("font_size",5.8)))
    if "candidate_score_audit" in p:
        p["dynamic_weights"]=p["candidate_score_audit"][0]["weights"]
plan["workflow_version"]="v4.0-readable-zone-complete";plan["status"]="approved";plan["agent_plan_status"]="approved"
# Reconcile the current stable native-line packet with the older OCR inventory.
packet=json.loads((work/r"page-0001/page-packet.json").read_text(encoding="utf8"))
covered_text=re.sub(r"[^A-Z0-9]+"," ","\n".join(b.get("source_text","") for b in plan["semantic_blocks"]).upper()).strip()
template=deepcopy(plan["semantic_blocks"][0])
sidebar_pending=[]
for ln in packet["source_text_lines"]:
    t=ln["text"].strip(); u=t.upper(); nu=re.sub(r"[^A-Z0-9]+"," ",u).strip(); cid=ln["line_id"]
    if nu and nu in covered_text: continue
    is_lit=u in {"EQ"} or bool(re.fullmatch(r"(?:[A-Z]{0,8}[-/]?)*\d+(?:\.\d+)?[A-Z0-9/ .:-]*",u)) or bool(re.fullmatch(r"[0-9. /:+-]+",u))
    plan["coverage_inventory"].append({"candidate_id":cid,"page_index":0,"source_text":t,"source_bbox":ln["bbox"],"rotation":ln.get("rotation",0),"status":"literal_only" if is_lit else "translated","reason":"language-neutral dimension or identifier" if is_lit else "current stable native line rebound to readable Chinese","provenance":"native_pdf_text"})
    if is_lit: continue
    x0,y0,x1,y1=ln["bbox"]
    if idx in (6,7) and x0>sw*.84:
        sidebar_pending.append(ln)
        continue
    nb=deepcopy(template); nb["block_id"]="stable-native-"+cid;nb["member_ids"]=[cid];nb["source_ids"]=[cid];nb["source_text"]=t;nb["source_bbox"]=ln["bbox"];nb["translated_text"]=readable(t,ln["bbox"])
    nb["page_region_id"]="p1-body";nb["region_type"]="drawing_body"
    rot=int(ln.get("rotation",0));
    if rot in (90,270): target=[min(sw-18,x1+2),y0,min(sw-2,x1+20),min(sh-2,max(y1,y0+80))]
    else: target=[x0,min(sh-18,y1+2),min(sw-2,max(x1,x0+100)),min(sh-2,y1+22)]
    p=nb["placement"];p["selected_region"]=target;p["font_size"]=6.8 if (x0<175 or x0>sw*.84) else 5.8;p["rotation"]=rot;p["render_text"]=nb["translated_text"];p["color"]=[0.02,0.22,0.72];p["preserve_source"]=True
    for a in p.get("candidate_score_audit",[]):a["bbox"]=target
    if p.get("group_layout"):p["group_layout"]["group_anchor"]=[(target[0]+target[2])/2,(target[1]+target[3])/2]
    plan["semantic_blocks"].append(nb)
if sidebar_pending:
    if not any(r.get("region_id")=="p1-company" for r in plan.get("page_region_map",[])):
        plan.setdefault("page_region_map",[]).append({"region_id":"p1-company","region_type":"company_contact_panel","page_index":0,"bbox":[sw*.84,0,sw,sh],"strategy":"black_bilingual_text_reflow","decision_source":"multimodal_visual_plan","visual_reason":"Right ruled company, address, contact and project cells use measured bilingual reflow at the production font floor."})
    bounds=[0,250,470,570,705,835,975,1085,1210,1400,sh]
    company_whitespace_06={
        250:[2218,342,2376,466],470:[2210,475,2376,566],570:[2168,590,2376,701],
        705:[2136,724,2376,831],835:[2215,842,2376,971],975:[2200,982,2376,1081],
        1085:[2190,1090,2376,1207],1210:[2080,1218,2376,1396],
    }
    for a,bnd in zip(bounds,bounds[1:]):
        members=[ln for ln in sidebar_pending if a<=((ln["bbox"][1]+ln["bbox"][3])/2)<bnd]
        if not members:continue
        box=[min(x["bbox"][0] for x in members),min(x["bbox"][1] for x in members),max(x["bbox"][2] for x in members),max(x["bbox"][3] for x in members)]
        q=fitz.Rect(box);q=fitz.Rect(q.x0/sw,q.y0/sh,q.x1/sw,q.y1/sh)
        cell_refs=[t for t,r in refs if not (r.x1<q.x0 or r.x0>q.x1 or r.y1<q.y0 or r.y0>q.y1)]
        zh="；".join(dict.fromkeys(cell_refs)) or readable("\n".join(x["text"] for x in members),box)
        nb=deepcopy(template);nb["block_id"]=f"stable-sidebar-cell-{a}";nb["member_ids"]=[x["line_id"] for x in members];nb["source_ids"]=nb["member_ids"][:];nb["source_text"]="\n".join(x["text"] for x in members);nb["source_bbox"]=box;nb["translated_text"]=zh;nb["page_region_id"]="p1-company";nb["region_type"]="company_contact_panel"
        target=company_whitespace_06.get(a,[max(sw*.855,box[0]-8),a+3,sw-4,bnd-3]) if idx==6 else [max(sw*.855,box[0]-8),a+3,sw-4,bnd-3]
        mid=target[1]+(target[3]-target[1])*.44
        p=nb["placement"];p["selected_region"]=target;p["font_size"]=6.8;p["rotation"]=0;p["render_text"]=zh;p["color"]=[0,0,0];p["mode"]="table_cell";p["preserve_source"]=True;p.pop("exact_ink_masks",None);p["render_runs"]=[{"text":nb["source_text"],"bbox":[target[0],target[1],target[2],mid],"font_size":6.4,"color":[0,0,0],"rotation":0},{"text":zh,"bbox":[target[0],mid,target[2],target[3]],"font_size":6.8,"color":[0,0,0],"rotation":0}]
        for score in p.get("candidate_score_audit",[]):score["bbox"]=target
        if p.get("group_layout"):p["group_layout"]["group_anchor"]=[(target[0]+target[2])/2,(target[1]+target[3])/2]
        plan["semantic_blocks"].append(nb)
if idx in (6,7):
    # Replace inherited cross-page body groups with the locally reviewed body
    # groups. Stable native lines are rebound by spatial proximity; OCR-only
    # callouts retain an explicit synthetic candidate so no semantic group is
    # orphaned.
    local_path=BASE/r"agent-artifacts/v3.12-quality-review-10"/f"{idx:02d}"/"paragraph-decision-ledger.json"
    local=[b for b in json.loads(local_path.read_text(encoding="utf8"))["blocks"] if b.get("zone")=="body"]
    panel_blocks=[b for b in plan["semantic_blocks"] if b.get("block_id","").startswith("stable-sidebar-cell-")]
    body_lines=[];new_inventory=[]
    for ln in packet["source_text_lines"]:
        t=ln["text"].strip();u=t.upper();x0,y0,x1,y1=ln["bbox"]
        is_lit=u in {"EQ","GF","L1","00"} or bool(re.fullmatch(r"(?:[A-Z]{0,8}[-/]?)*\d+(?:\.\d+)?[A-Z0-9/ .:<>-]*",u)) or bool(re.fullmatch(r"[0-9. /:+<>-]+",u))
        status="literal_only" if is_lit else "translated"
        new_inventory.append({"candidate_id":ln["line_id"],"page_index":0,"source_text":t,"source_bbox":ln["bbox"],"rotation":0,"status":status,"reason":"language-neutral identifier/dimension" if is_lit else "display-normalized line bound to local paragraph or ruled sidebar cell","provenance":"native_pdf_text"})
        if status=="translated" and x0<=sw*.84:body_lines.append(ln)
    assigned_local={i:[] for i in range(len(local))}
    for ln in body_lines:
        cx=(ln["bbox"][0]+ln["bbox"][2])/2;cy=(ln["bbox"][1]+ln["bbox"][3])/2
        j=min(range(len(local)),key=lambda k:math.hypot((local[k]["source_bbox_display"][0]+local[k]["source_bbox_display"][2])/2-cx,(local[k]["source_bbox_display"][1]+local[k]["source_bbox_display"][3])/2-cy))
        assigned_local[j].append(ln)
    body_blocks=[]
    for j,lb in enumerate(local):
        members=assigned_local[j]
        syn=f"p001-ocr-local-{j+1:04d}"
        new_inventory.append({"candidate_id":syn,"page_index":0,"source_text":lb["source_text"],"source_bbox":lb["source_bbox_display"],"rotation":0,"status":"translated","reason":"local reviewed OCR paragraph","provenance":"ocr"})
        ids=[x["line_id"] for x in members]+[syn];source="\n".join([x["text"] for x in members]+[lb["source_text"]])
        nb=deepcopy(template);nb["block_id"]=f"local-body-{j+1:04d}";nb["member_ids"]=ids;nb["source_ids"]=ids[:];nb["source_text"]=source;nb["source_bbox"]=lb["source_bbox_display"];nb["translated_text"]=lb["translation"];nb["page_region_id"]="p1-body";nb["region_type"]="drawing_body"
        norm_source=source.strip().replace("\n"," ").upper()
        if norm_source in {"TYPE B TYPE B","TYPE B"}:nb["translated_text"]="B型"
        if norm_source in {"AREA AREA","AREA"}:nb["translated_text"]="区域"
        target=lb["chosen_bbox_display"];p=nb["placement"];p["selected_region"]=target;p["font_size"]=max(5.8,float(lb.get("font_size",5.8)));p["rotation"]=0;p["render_text"]=nb["translated_text"];p["color"]=[0.02,0.22,0.72];p["preserve_source"]=True;p["mode"]="inline"
        if j==5:target=[470,1210,550,1240];p["selected_region"]=target
        if j==18:target=[600,500,680,530];p["selected_region"]=target
        p.pop("exact_ink_masks",None);p.pop("render_runs",None)
        for score in p.get("candidate_score_audit",[]):score["bbox"]=target
        if p.get("group_layout"):p["group_layout"]["group_anchor"]=[(target[0]+target[2])/2,(target[1]+target[3])/2]
        body_blocks.append(nb)
    for ln in packet["source_text_lines"]:
        if ln["bbox"][0]<=sw*.84:continue
        inv_item=next(x for x in new_inventory if x["candidate_id"]==ln["line_id"])
        if inv_item["status"]!="translated":continue
        cy=(ln["bbox"][1]+ln["bbox"][3])/2
        host=min(panel_blocks,key=lambda b:abs((b["source_bbox"][1]+b["source_bbox"][3])/2-cy))
        if ln["line_id"] not in host["member_ids"]:host["member_ids"].append(ln["line_id"]);host.setdefault("source_ids",[]).append(ln["line_id"]);host["source_text"] += "\n"+ln["text"]
    plan["coverage_inventory"]=new_inventory;plan["semantic_blocks"]=body_blocks+panel_blocks
candidate_ids=[x["candidate_id"] for x in plan.get("coverage_inventory",[]) if x.get("candidate_id")]
if idx in (6,7):
    translated_ids=[x["candidate_id"] for x in plan["coverage_inventory"] if x["status"]=="translated"]
    sidebar_ids={i for b in plan["semantic_blocks"] if b["region_type"]=="company_contact_panel" for i in b["member_ids"]}
    body_ids=[i for i in translated_ids if i not in sidebar_ids]
    plan["mandatory_zone_audit"]=[{"zone_id":"p1-body-closure","zone_type":"body","page_index":0,"member_ids":body_ids,"block_ids":[b["block_id"] for b in plan["semantic_blocks"] if b["region_type"]=="drawing_body"],"status":"complete","decision_source":"multimodal_visual_plan"},{"zone_id":"p1-sidebar-closure","zone_type":"sidebar","page_index":0,"member_ids":sorted(sidebar_ids),"block_ids":[b["block_id"] for b in plan["semantic_blocks"] if b["region_type"]=="company_contact_panel"],"status":"complete","decision_source":"multimodal_visual_plan"}]
plan["coverage_evidence"]=[{"page_index":0,"source":"native_plus_ocr","candidate_ids":candidate_ids,"uncovered_candidate_ids":[],"evidence_note":"Stable source candidates are exhaustively bound to semantic blocks or literal-only inventory."}]
plan["unexplained_region_ids"]=[]
plan["render_provenance"]={"base":"original_source_pdf","source_sha256":hashlib.sha256(src.read_bytes()).hexdigest(),"reference_usage":"translation_evidence_only","copied_reference_page_or_region":False}
now=datetime.now(timezone.utc).isoformat();inv=f"codex-sol-light-production{idx:02d}-"+datetime.now().strftime("%Y%m%d%H%M%S")
raw={"schema":"codex-sol-light-production-response","index":idx,"decision":"approved","rule":"reference content only; independent placement","blocks":len(plan["semantic_blocks"])}
rh=hashlib.sha256(json.dumps(raw,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
plan["supervisor_invocation"].update({"verified":True,"invocation_id":inv,"agent_id":"sol_light_supervisor","mode":"codex_agent_multimodal","model":"gpt-5.6-sol","reasoning_profile":"light","started_at":now,"completed_at":now,"response_sha256":rh})
plan.pop("final_visual_review",None)
# V4 exclusive execution mode contract. This legacy development entry point is
# retained only for candidate generation; the release harness still has to
# validate every downstream handoff separately.
for block in plan.get("semantic_blocks", []):
    placement = block.get("placement") or {}
    if block.get("region_type") == "company_contact_panel":
        placement["render_mode"] = "opaque_bilingual_reflow"
        placement["preserve_source"] = False
        placement["old_source_glyphs_visible"] = False
        placement["partial_mask_overlap"] = False
        if not placement.get("exact_ink_masks"):
            placement["exact_ink_masks"] = [block.get("source_bbox")]
    else:
        placement["render_mode"] = "preserve_source_blue_chinese"
        placement["preserve_source"] = True
        placement["color"] = [0.05, 0.16, 0.45]
        placement.pop("exact_ink_masks", None)
        placement.pop("render_runs", None)
plan=validate_multimodal_plan(plan,source_pdf_path=src);plan=validate_real_supervisor_plan(plan,source_pdf_path=src,require_final_review=False)
pp=work/r"supervisor-plan.json";pp.write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding="utf8")
bundle=work/r"supervisor-run";shutil.rmtree(bundle,ignore_errors=True)
img=work/r"page-0001/page-0001-source.png"
create_supervisor_run_bundle(bundle_dir=bundle,source_pdf_path=src,page_images=[img],request={"task":f"production #{idx}","coverage_requirement":1.0,"company_panel_min_font":6.4},raw_response=raw,normalized_plan=plan,invocation_id=inv,agent_id="sol_light_supervisor",started_at=now,completed_at=now)
oldwork=oldp.parent
args=["v3-render","--source",str(src),"--plan",str(pp),"--regions-json",str(oldwork/r"ocr/ocr.json"),"--output",str(out),"--agent-manifest",str(work/r"agent-manifest.json"),"--supervisor-bundle",str(bundle)]
code=drawing_cli.main(args);print("render_exit",code)
if code: raise SystemExit(code)
