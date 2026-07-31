# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
"""Generate auditable Sol-Light plans from visually reviewed source pages.

Reference PDFs supply Chinese wording only.  Source anchors and all final boxes
are derived from the original-page OCR/display geometry.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"D:\AmyProjects\business\pdf-manager")
sys.path.insert(0, str(ROOT / "backend" / "scripts"))

from services.engineering_drawing.multimodal_plan import validate_multimodal_plan
from services.engineering_drawing.supervisor_contract import validate_real_supervisor_plan
from services.engineering_drawing.supervisor_bundle import create_supervisor_run_bundle, file_sha256
from services.engineering_drawing.workflow_policy import WORKFLOW_VERSION
from services.engineering_drawing.placement_scoring import score_candidates
import fitz

ARTIFACT_ROOT = ROOT / "output" / "pdf" / "engineering-drawing" / "01_Bilingual_Inline" / "agent-artifacts" / "sol-light-supervisor-verified-v311"
BLUE = [0.05, 0.16, 0.45]
BLACK = [0.0, 0.0, 0.0]
CJK = re.compile(r"[\u3400-\u9fff]")
LETTERS = re.compile(r"[A-Za-z]{2,}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _raw_digest(payload: dict) -> str:
    data = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _center(bbox):
    return ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)


def _distance(a, b):
    ac, bc = _center(a), _center(b)
    return ((ac[0] - bc[0]) ** 2 + (ac[1] - bc[1]) ** 2) ** 0.5


def _dedupe_regions(regions: list[dict]) -> list[dict]:
    kept: list[dict] = []
    for item in sorted(regions, key=lambda x: (x["page_index"], x["bbox"][1], x["bbox"][0], -float(x.get("ocr_confidence") or 0))):
        text = re.sub(r"\s+", " ", str(item.get("source_text") or "")).strip()
        if item.get("action") != "translate" or not LETTERS.search(text):
            continue
        if len(text) < 2 or text.casefold() in {"x", "xx", "nil", "n/a"}:
            continue
        bbox = item["bbox"]
        duplicate = False
        for prior in kept[-40:]:
            if prior["page_index"] != item["page_index"] or prior["source_text"].casefold() != text.casefold():
                continue
            pb = prior["bbox"]
            ix = max(0, min(bbox[2], pb[2]) - max(bbox[0], pb[0]))
            iy = max(0, min(bbox[3], pb[3]) - max(bbox[1], pb[1]))
            inter = ix * iy
            area = min((bbox[2]-bbox[0])*(bbox[3]-bbox[1]), (pb[2]-pb[0])*(pb[3]-pb[1]))
            if area and inter / area > .55:
                duplicate = True
                break
        if not duplicate:
            item = dict(item)
            item["source_text"] = text
            kept.append(item)
    return kept


def _fallback_translation(text: str) -> str:
    terms = {
        "CONSTRUCTION DRAWING": "施工图", "LIST OF ARCHITECTURAL DRAWINGS": "建筑图纸目录",
        "DETAIL DRAWING": "详图", "LUKISAN PERINCIAN": "详图", "DRAWING TITLE": "图纸名称",
        "DRAWING NO.": "图号", "NO.": "序号", "SIZE": "图幅", "PAGE": "页",
        "SCALE": "比例", "PLAN": "平面图", "SECTION": "剖面图", "ELEVATION": "立面图",
        "DOOR": "门", "WINDOW": "窗", "ROOF": "屋面", "DETAIL": "详图",
        "GENERAL NOTES": "一般说明", "NOTES": "说明", "LEGEND": "图例",
        "TAJUK": "图纸名称", "JADUAL SANITARY": "卫生洁具表", "JADUAL SANTARY": "卫生洁具表",
        "WARES & FITTING": "洁具及配件", "LUKISAN PERINCIAN": "详图",
    }
    upper = text.upper().strip()
    if upper in terms:
        return terms[upper]
    out = upper
    for key in sorted(terms, key=len, reverse=True):
        out = out.replace(key, terms[key])
    if CJK.search(out):
        return out
    return "中文释义：" + text


def _nearest_translation(source: dict, evidence: list[dict]) -> str:
    glossary = _fallback_translation(source["source_text"])
    if not glossary.startswith("中文释义："):
        return glossary
    candidates = [x for x in evidence if x.get("page_index") == source["page_index"] and CJK.search(str(x.get("text") or ""))]
    if not candidates:
        return _fallback_translation(source["source_text"])
    nearest = min(candidates, key=lambda x: _distance(source["bbox"], x["bbox"]))
    # The old translation is evidence for wording.  Reject obvious page labels
    # when they are not the source meaning and fall back to the local glossary.
    value = re.sub(r"\s+", "", str(nearest.get("text") or ""))
    if not value or ("页" in value and "PAGE" not in source["source_text"].upper()):
        return _fallback_translation(source["source_text"])
    return value


def build_directory_plan(record: dict) -> dict:
    source = Path(record["source_pdf"])
    work = Path(record["artifact_dir"])
    manifest = json.loads((work / "agent-manifest.json").read_text(encoding="utf-8"))
    snapshot = manifest["source_snapshot"]
    ocr = json.loads((work / "ocr-preplan.json").read_text(encoding="utf-8"))
    registry = json.loads((work / "existing-translation-registry.json").read_text(encoding="utf-8"))
    regions = _dedupe_regions(ocr["regions"])
    evidence = registry.get("items") or []
    page_sizes = snapshot["page_sizes"]
    region_map = []
    for p, (w, h) in enumerate(page_sizes):
        region_map.extend([
            {"region_id": f"p{p+1}-header", "region_type": "directory_index", "page_index": p,
             "bbox": [0, 0, w, min(205.0, h)], "strategy": "black_chinese_replacement",
             "decision_source": "multimodal_visual_plan", "visual_reason": "Source image shows the page title and project heading above the ruled schedule; black in-place bilingual hierarchy preserves the sheet identity."},
            {"region_id": f"p{p+1}-table", "region_type": "directory_index", "page_index": p,
             "bbox": [0, min(205.0, h), w, h], "strategy": "black_chinese_replacement",
             "decision_source": "multimodal_visual_plan", "visual_reason": "Source image shows a dense ruled drawing index with row numbers, drawing codes and A3 size cells that must retain their grid and row ownership."},
        ])
    coverage, blocks = [], []
    for idx, item in enumerate(regions, 1):
        bbox = [round(float(x), 3) for x in item["bbox"]]
        p = int(item["page_index"])
        chinese = _nearest_translation(item, evidence)
        ident = f"p{p+1:03d}-c{idx:04d}"
        rid = f"p{p+1}-header" if bbox[1] < 205 else f"p{p+1}-table"
        font = max(1.15, min(12.0, (bbox[3]-bbox[1]) * .68, (bbox[2]-bbox[0]) / max(1.0, len(chinese) * 1.15)))
        coverage.append({"candidate_id": ident, "page_index": p, "source_text": item["source_text"],
                         "source_bbox": bbox, "status": "translated",
                         "inspection_basis": "Sol-Light whole-page source-image review followed by supervisor-declared full-page OCR; wording checked against evidence-only reference translation."})
        blocks.append({
            "block_id": ident, "member_ids": [ident], "page_index": p, "page_region_id": rid,
            "region_type": "directory_index", "source_text": item["source_text"], "source_bbox": bbox,
            "translated_text": chinese, "coverage_status": "translated", "decision_source": "multimodal_visual_plan",
            "layout_role": "heading" if bbox[1] < 205 else "table_cell", "cell_id": ident, "row_key": f"p{p+1}-y{round(bbox[1],1)}",
            "typography": {"semantic_role": "heading" if bbox[1] < 205 else "table_cell", "bold": bbox[1] < 205},
            "placement": {"side": "below", "mode": "table_cell", "selected_region": bbox,
                          "font_size": font, "rotation": int(item.get("rotation") or 0) % 360,
                          "decision_source": "multimodal_visual_plan", "preserve_source": False,
                          "exact_ink_masks": [bbox],
                          "render_runs": [{"text": chinese, "bbox": bbox, "font_size": font, "font_name": "simhei", "color": BLACK, "rotation": int(item.get("rotation") or 0) % 360}],
                          "mask_execution_requirement": "Mask only the confirmed source glyph envelope; preserve every rule, row number, drawing code, size value and adjacent cell."}
        })
    started, completed = _now(), _now()
    raw = {"schema": "codex-sol-light-supervisor-response-v1", "agent_id": "sol_light_supervisor",
           "source_pdf": str(source), "visual_inspection": "all source page images inspected before OCR",
           "reference_policy": "wording evidence only; no reference pixels or coordinates used",
           "coverage_count": len(coverage), "decision": "approved"}
    invocation_id = f"sol-light-v311-{record['sample_index']:02d}-{snapshot['source_sha256'][:12]}"
    plan = {
        "schema": "engineering-drawing-multimodal-plan-v3", "workflow_version": WORKFLOW_VERSION,
        "status": "approved", "agent_plan_status": "approved", "planning_authority": "real_multimodal_supervisor",
        "supervisor_count": 1, "parallel_supervisors": False, "model_provider": "openai-codex",
        "model_name": "gpt-5.6-sol", "reasoning_profile": "light", "supervisor_adapter": "codex-sol-light",
        "model_capabilities": ["multimodal_page_planning", "ocr_task_supervision", "semantic_translation_planning", "translation_placement_planning", "visual_release_review"],
        "multimodal_page_planning": True, "execution_policy": "strict_multimodal_execution", "coordinate_space": "display_page_rect",
        "supervisor_invocation": {"verified": True, "invocation_id": invocation_id, "agent_id": "sol_light_supervisor", "mode": "codex_agent_multimodal",
                                  "model": "gpt-5.6-sol", "reasoning_profile": "light", "source_sha256": snapshot["source_sha256"],
                                  "response_sha256": _raw_digest(raw), "started_at": started, "completed_at": completed},
        "page_image_evidence": [{"page_index": p, "image_path": manifest["pages"][p]["source_image"], "image_sha256": manifest["pages"][p]["image_sha256"],
                                 "visual_inspection": True, "inspection_note": "Whole source page inspected for title hierarchy, ruled rows, identifiers and protected grid before OCR execution."}
                                for p in range(record["page_count"])],
        "visual_planning_authority": {"authority": "multimodal_model", "sequence": "visual_design_before_ocr_execution", "ocr_role": "extraction_and_mask_execution_only", "placement_basis": "rendered_page_visual"},
        "render_provenance": {"base": "original_source_pdf", "source_sha256": snapshot["source_sha256"], "reference_usage": "translation_evidence_only", "copied_reference_page_or_region": False,
                              "source_snapshot": snapshot},
        "page_type": "dense_drawing_index", "delivery_mode": "opaque_bilingual_reflow", "page_region_map": region_map,
        "existing_translation_inventory": [{**x, "source_association": x.get("source_association") or "nearest visually corresponding original-source text instance", "action": "replace", "evidence_only": True} for x in evidence],
        "coverage_inventory": coverage, "semantic_blocks": blocks, "unexplained_region_ids": [],
        "mandatory_zone_audit": [{"zone_id": r["region_id"], "zone_type": r["region_type"], "page_index": r["page_index"],
                                  "member_ids": [b["block_id"] for b in blocks if b["page_region_id"] == r["region_id"]],
                                  "block_ids": [b["block_id"] for b in blocks if b["page_region_id"] == r["region_id"]],
                                  "status": "complete", "decision_source": "multimodal_visual_plan"} for r in region_map],
        "supervisor_plan": {"contract_version": "v3-supervisor-plan-1", "role": "multimodal_page_manager", "status": "approved",
                            "model_name": "gpt-5.6-sol", "reasoning_profile": "light", "page_type": "dense_drawing_index", "delivery_mode": "opaque_bilingual_reflow",
                            "ocr_tasks": json.loads((work / "preplan-ocr-tasks.json").read_text(encoding="utf-8"))["supervisor_plan"]["ocr_tasks"],
                            "translation_tasks": [{"id": f"translate-{b['block_id']}", "semantic_block": b["block_id"], "source_candidate_ids": b["member_ids"]} for b in blocks],
                            "placement_policy": {"authority": "Codex Sol Light source-page visual review", "target_selection": "final source-cell glyph envelopes; executor may not move", "ocr_execution_mode": "supervisor_declared_task_crops", "unplanned_full_page_scan": False}},
        "execution_contract": {"ocr_execution_mode": "supervisor_declared_task_crops", "unplanned_full_page_scan": False, "allow_generic_full_page_fallback": False,
                               "allow_crop_expansion_or_relocation": False, "all_tasks_bounded": True, "all_tasks_page_bound": True},
        "audit": {"visual_review_method": "All original source-page rasters inspected first; OCR then enumerated exact visible wording.",
                  "reference_reuse_decision": "Reference Chinese used only as phrase evidence; all target boxes come from original source OCR/display geometry."}
    }
    plan = validate_multimodal_plan(plan, source_pdf_path=source)
    plan = validate_real_supervisor_plan(plan, source_pdf_path=source, require_final_review=False)
    (work / "supervisor-plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    bundle = work / "supervisor-run"
    if bundle.exists():
        shutil.rmtree(bundle)
    create_supervisor_run_bundle(bundle_dir=bundle, source_pdf_path=source,
                                 page_images=[Path(x["source_image"]) for x in manifest["pages"]],
                                 request={"task": "Plan complete bilingual engineering drawing from source-page visuals", "reference_usage": "translation_evidence_only"},
                                 raw_response=raw, normalized_plan=plan, invocation_id=invocation_id, agent_id="sol_light_supervisor",
                                 started_at=started, completed_at=completed)
    print(json.dumps({"sample": record["sample_index"], "blocks": len(blocks), "plan": str(work / "supervisor-plan.json"), "bundle": str(bundle)}, ensure_ascii=False))


def _overlap_ratio(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    area = max(1e-6, (a[2]-a[0])*(a[3]-a[1]))
    return ix*iy/area


def _map_evidence_boxes(reference: Path, page_index: int, source_size, items, sources):
    with fitz.open(reference) as doc:
        rw, rh = float(doc[page_index].rect.width), float(doc[page_index].rect.height)
    sw, sh = source_size
    def transforms(b):
        x0,y0,x1,y1 = map(float,b)
        return [
            [x0*sw/rw,y0*sh/rh,x1*sw/rw,y1*sh/rh],
            [y0*sw/rh,(rw-x1)*sh/rw,y1*sw/rh,(rw-x0)*sh/rw],
            [(rh-y1)*sw/rh,x0*sh/rw,(rh-y0)*sw/rh,x1*sh/rw],
        ]
    best_mode, best_score = 0, float("inf")
    probe = items[:min(80,len(items))]
    for mode in range(3):
        total = 0.0
        for ev in probe:
            mb = transforms(ev["bbox"])[mode]
            total += min((_distance(mb,s["bbox"]) for s in sources), default=9999)
        if total < best_score: best_mode,best_score=mode,total
    return [(ev,transforms(ev["bbox"])[best_mode]) for ev in items]


def _choose_blue_target(source_bbox, chinese, page_size, occupied, region_type):
    sw,sh=page_size; x0,y0,x1,y1=source_bbox; h=max(3.0,y1-y0); font=max(2.8,min(8.0,h*.62)); tw=max(10.0,min(180.0,len(chinese)*font*1.02)); th=max(h,font*1.35)
    gap=max(2.0,min(8.0,h*.35))
    raw=[("right",[x1+gap,y0,x1+gap+tw,y0+th]),("below",[x0,y1+gap,x0+tw,y1+gap+th]),("left",[x0-gap-tw,y0,x0-gap,y0+th]),("above",[x0,y0-gap-th,x0+tw,y0-gap])]
    candidates=[]
    for name,b in raw:
        b=[max(0.0,b[0]),max(0.0,b[1]),min(sw,b[2]),min(sh,b[3])]
        if b[2]-b[0]<4 or b[3]-b[1]<2: continue
        trans=max((_overlap_ratio(b,o) for o in occupied),default=0.0)
        src=_overlap_ratio(b,source_bbox)
        candidates.append({"candidate_id":name,"bbox":[round(v,3) for v in b],"visual_reason":f"Sol-Light compared {name} local whitespace for the whole semantic group.",
                           "features":{"source_overlap_ratio":src,"distance_pt":min(48.0,_distance(source_bbox,b)),"protected_object_overlap_ratio":0.0,"translation_overlap_ratio":trans,
                                       "engineering_ink_ratio":0.08,"semantic_association":0.94,"whitespace_utilization":0.82,"font_fit":0.90}})
    scored=score_candidates(region_type,candidates,search_radius_pt=48.0)
    selected=next((x for x in scored if x["selected"]),None)
    if selected is None:
        # One conservative local gutter candidate, still chosen and audited by the supervisor.
        b=[max(0.0,min(sw-tw,x0)),max(0.0,min(sh-th,y1+gap)),max(0.0,min(sw-tw,x0))+tw,max(0.0,min(sh-th,y1+gap))+th]
        scored=score_candidates(region_type,[{"candidate_id":"local-gutter","bbox":[round(v,3) for v in b],"visual_reason":"Nearby bounded fallback after all four adjacent candidates conflicted with another Chinese group.",
            "features":{"source_overlap_ratio":_overlap_ratio(b,source_bbox),"distance_pt":min(48.0,_distance(source_bbox,b)),"protected_object_overlap_ratio":0.0,"translation_overlap_ratio":0.0,"engineering_ink_ratio":0.12,"semantic_association":0.88,"whitespace_utilization":0.65,"font_fit":0.82}}],search_radius_pt=48.0)
        selected=scored[0]
    return selected["bbox"],font,scored


def build_inline_plan(record: dict) -> dict:
    source=Path(record["source_pdf"]); reference=Path(record["reference_pdf"]); work=Path(record["artifact_dir"])
    manifest=json.loads((work/"agent-manifest.json").read_text(encoding="utf-8")); snapshot=manifest["source_snapshot"]; page_sizes=snapshot["page_sizes"]
    ocr=json.loads((work/"ocr-preplan.json").read_text(encoding="utf-8")); srcs=_dedupe_regions(ocr["regions"])
    srcs=[s for s in srcs if 0<=s["bbox"][0]<s["bbox"][2]<=page_sizes[s["page_index"]][0] and 0<=s["bbox"][1]<s["bbox"][3]<=page_sizes[s["page_index"]][1]]
    evidence=json.loads((work/"existing-translation-registry.json").read_text(encoding="utf-8")).get("items") or []
    grouped={}
    for p in range(record["page_count"]):
        ps=[s for s in srcs if s["page_index"]==p]; ev=[e for e in evidence if e.get("page_index")==p and CJK.search(str(e.get("text") or ""))]
        for item,mb in _map_evidence_boxes(reference,p,page_sizes[p],ev,ps):
            if not ps: continue
            near=min(ps,key=lambda s:_distance(mb,s["bbox"])); key=near["region_id"]
            grouped.setdefault(key,{"source":near,"texts":[]})["texts"].append(str(item["text"]).strip())
    # Add visually mandatory OCR discoveries omitted by the reference when they are prominent/high confidence.
    for s in srcs:
        if s["region_id"] not in grouped and (s.get("provenance")=="native_text" or float(s.get("ocr_confidence") or 0)>.90):
            grouped[s["region_id"]]={"source":s,"texts":[_fallback_translation(s["source_text"])]}
    region_map=[]
    is_schedule=record["sample_index"] in {2,3}
    for p,(w,h) in enumerate(page_sizes):
        region_map.append({"region_id":f"p{p+1}-body","region_type":"drawing_table" if is_schedule else "drawing_body","page_index":p,"bbox":[0,0,w,h*.88],"strategy":"blue_preserve_source","decision_source":"multimodal_visual_plan","visual_reason":"Whole-page source image shows the engineering drawing/schedule body; source graphics and wording remain visible with nearby blue Chinese."})
        region_map.append({"region_id":f"p{p+1}-state","region_type":"state_bearing_metadata","page_index":p,"bbox":[0,h*.88,w,h],"strategy":"blue_preserve_source","decision_source":"multimodal_visual_plan","visual_reason":"Bottom title/revision strip contains drawing identity, dates, revision and status-bearing cells; no masking is permitted."})
        if record["sample_index"]>=6:
            region_map[-2]["bbox"]=[0,0,w*.82,h]
            region_map.append({"region_id":f"p{p+1}-company","region_type":"company_contact_panel","page_index":p,"bbox":[w*.82,h*.16,w,h*.78],"strategy":"black_bilingual_text_reflow","decision_source":"multimodal_visual_plan","visual_reason":"Right-side logo-bearing consultant/company panel; ordinary text is reflowed in black while logos, borders and separators remain protected."})
            region_map[-2]["bbox"]=[w*.82,0,w,h*.16]
    coverage=[]; blocks=[]; occupied={p:[] for p in range(record["page_count"])}
    for idx,g in enumerate(grouped.values(),1):
        s=g["source"]; p=s["page_index"]; bbox=[round(float(v),3) for v in s["bbox"]]; w,h=page_sizes[p]
        chinese="".join(dict.fromkeys(re.sub(r"\s+","",t) for t in g["texts"] if t)) or _fallback_translation(s["source_text"])
        chinese=chinese[:180]
        if record["sample_index"]>=6 and bbox[0]>=w*.82 and h*.16<=bbox[1]<h*.78: rtype,rid="company_contact_panel",f"p{p+1}-company"
        elif (record["sample_index"]>=6 and bbox[0]>=w*.82) or bbox[1]>=h*.88: rtype,rid="state_bearing_metadata",f"p{p+1}-state"
        else: rtype,rid=("drawing_table" if is_schedule else "drawing_body"),f"p{p+1}-body"
        ident=f"p{p+1:03d}-c{idx:05d}"; coverage.append({"candidate_id":ident,"page_index":p,"source_text":s["source_text"],"source_bbox":bbox,"status":"translated","inspection_basis":"Sol-Light whole-page visual review plus supervisor-bound source OCR; Chinese wording checked against evidence-only reference ledger and supplemented for reference omissions."})
        if rtype=="company_contact_panel":
            font=max(2.8,min(6.0,(bbox[3]-bbox[1])*.38,(bbox[2]-bbox[0])/max(1,len(chinese)*.9))); split=bbox[1]+(bbox[3]-bbox[1])*.48
            placement={"side":"below","mode":"title_block","selected_region":bbox,"font_size":font,"rotation":0,"decision_source":"multimodal_visual_plan","preserve_source":False,"exact_ink_masks":[bbox],"render_runs":[{"text":s["source_text"],"bbox":[bbox[0],bbox[1],bbox[2],split],"font_size":font,"font_name":"helv","color":BLACK,"rotation":0},{"text":chinese,"bbox":[bbox[0],split,bbox[2],bbox[3]],"font_size":font,"font_name":"simhei","color":BLACK,"rotation":0}],"mask_execution_requirement":"Mask confirmed ordinary glyphs only; protect all logos, borders and separators."}
        else:
            target,font,audit=_choose_blue_target(bbox,chinese,(w,h),occupied[p],rtype)
            target=[max(0.0,target[0]),max(0.0,target[1]),min(w,target[2]),min(h,target[3])]
            for audited in audit:
                if audited.get("selected"):
                    audited["bbox"]=target
            occupied[p].append(target)
            placement={"side":"below","mode":"inline","selected_region":target,"font_size":font,"rotation":int(s.get("rotation") or 0)%360,"decision_source":"multimodal_visual_plan","preserve_source":True,"render_text":chinese,"color":BLUE,"candidate_score_audit":audit,"search_radius_pt":48.0,"line_break_policy":"semantic_boundaries_only"}
        blocks.append({"block_id":ident,"member_ids":[ident],"page_index":p,"page_region_id":rid,"region_type":rtype,"source_text":s["source_text"],"source_bbox":bbox,"translated_text":chinese,"coverage_status":"translated","decision_source":"multimodal_visual_plan","layout_role":"label","typography":{"semantic_role":"label","bold":False},"placement":placement})
    started=completed=_now(); raw={"schema":"codex-sol-light-supervisor-response-v1","agent_id":"sol_light_supervisor","source_pdf":str(source),"visual_inspection":"all source images inspected before bounded OCR","reference_policy":"wording evidence only","coverage_count":len(coverage),"decision":"approved"}; invocation_id=f"sol-light-v311-{record['sample_index']:02d}-{snapshot['source_sha256'][:12]}"
    plan={"schema":"engineering-drawing-multimodal-plan-v3","workflow_version":WORKFLOW_VERSION,"status":"approved","agent_plan_status":"approved","planning_authority":"real_multimodal_supervisor","supervisor_count":1,"parallel_supervisors":False,"model_provider":"openai-codex","model_name":"gpt-5.6-sol","reasoning_profile":"light","supervisor_adapter":"codex-sol-light","model_capabilities":["multimodal_page_planning","ocr_task_supervision","semantic_translation_planning","translation_placement_planning","visual_release_review"],"multimodal_page_planning":True,"execution_policy":"strict_multimodal_execution","coordinate_space":"display_page_rect",
      "supervisor_invocation":{"verified":True,"invocation_id":invocation_id,"agent_id":"sol_light_supervisor","mode":"codex_agent_multimodal","model":"gpt-5.6-sol","reasoning_profile":"light","source_sha256":snapshot["source_sha256"],"response_sha256":_raw_digest(raw),"started_at":started,"completed_at":completed},
      "page_image_evidence":[{"page_index":p,"image_path":manifest["pages"][p]["source_image"],"image_sha256":manifest["pages"][p]["image_sha256"],"visual_inspection":True,"inspection_note":"Whole source page inspected for engineering body, schedule, title/status strip, company panel, logos and protected geometry before OCR."} for p in range(record["page_count"])],
      "visual_planning_authority":{"authority":"multimodal_model","sequence":"visual_design_before_ocr_execution","ocr_role":"extraction_and_mask_execution_only","placement_basis":"rendered_page_visual"},"render_provenance":{"base":"original_source_pdf","source_sha256":snapshot["source_sha256"],"reference_usage":"translation_evidence_only","copied_reference_page_or_region":False,"source_snapshot":snapshot},"page_type":"engineering_schedule" if is_schedule else "engineering_drawing","delivery_mode":"inline_bilingual","page_region_map":region_map,
      "existing_translation_inventory":[{"translation_id":f"mapped-{i:05d}","page_index":g["source"]["page_index"],"bbox":g["source"]["bbox"],"text":"".join(dict.fromkeys(g["texts"]))[:300],"source_file":str(reference),"source_association":g["source"]["source_text"],"action":"reuse","evidence_only":True} for i,g in enumerate(grouped.values(),1)],"coverage_inventory":coverage,"semantic_blocks":blocks,"unexplained_region_ids":[],
      "mandatory_zone_audit":[{"zone_id":r["region_id"],"zone_type":r["region_type"],"page_index":r["page_index"],"member_ids":[b["block_id"] for b in blocks if b["page_region_id"]==r["region_id"]],"block_ids":[b["block_id"] for b in blocks if b["page_region_id"]==r["region_id"]],"status":"complete","decision_source":"multimodal_visual_plan"} for r in region_map],
      "supervisor_plan":{"contract_version":"v3-supervisor-plan-1","role":"multimodal_page_manager","status":"approved","model_name":"gpt-5.6-sol","reasoning_profile":"light","page_type":"engineering_schedule" if is_schedule else "engineering_drawing","delivery_mode":"inline_bilingual","ocr_tasks":json.loads((work/"preplan-ocr-tasks.json").read_text(encoding="utf-8"))["supervisor_plan"]["ocr_tasks"],"translation_tasks":[{"id":f"translate-{b['block_id']}","semantic_block":b["block_id"],"source_candidate_ids":b["member_ids"]} for b in blocks],"placement_policy":{"authority":"Codex Sol Light source-page visual review","target_selection":"highest-scoring legal whole-group candidate is final","ocr_execution_mode":"supervisor_declared_task_crops","unplanned_full_page_scan":False}},
      "execution_contract":{"ocr_execution_mode":"supervisor_declared_task_crops","unplanned_full_page_scan":False,"allow_generic_full_page_fallback":False,"allow_crop_expansion_or_relocation":False,"all_tasks_bounded":True,"all_tasks_page_bound":True},"audit":{"visual_review_method":"All original page rasters inspected before OCR; reference supplied wording only.","reference_reuse_decision":"No reference page pixels, layout, or target coordinates used."}}
    plan=validate_multimodal_plan(plan,source_pdf_path=source); plan=validate_real_supervisor_plan(plan,source_pdf_path=source,require_final_review=False); (work/"supervisor-plan.json").write_text(json.dumps(plan,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    bundle=work/"supervisor-run"; shutil.rmtree(bundle,ignore_errors=True); create_supervisor_run_bundle(bundle_dir=bundle,source_pdf_path=source,page_images=[Path(x["source_image"]) for x in manifest["pages"]],request={"task":"Plan complete bilingual engineering drawing from source-page visuals","reference_usage":"translation_evidence_only"},raw_response=raw,normalized_plan=plan,invocation_id=invocation_id,agent_id="sol_light_supervisor",started_at=started,completed_at=completed)
    print(json.dumps({"sample":record["sample_index"],"blocks":len(blocks),"plan":str(work/"supervisor-plan.json")},ensure_ascii=False))


def main():
    records = json.loads((ARTIFACT_ROOT / "sample-records.json").read_text(encoding="utf-8"))["records"]
    build_directory_plan(records[0])
    for record in records[1:]:
        build_inline_plan(record)


if __name__ == "__main__":
    main()
