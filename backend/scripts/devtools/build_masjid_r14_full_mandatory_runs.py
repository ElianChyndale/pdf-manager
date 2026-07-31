# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
from __future__ import annotations

"""R14 exact-glyph bilingual reflow for every native mandatory-zone paragraph."""

import json, re
from pathlib import Path
import fitz

from build_masjid_r13_masked_body import OUTPUT_PLAN as R13_PLAN, main as build_r13
from build_masjid_r12_mandatory_body import ZONES

ARTIFACT = R13_PLAN.parent
PDF = Path(r"D:\AmyProjects\business\WROK-CONTENT\malasia\03_CONSTRUCTION DWG_MASJID_11 NOV 2025\A1 WORKING DRAWING\01_Masjid Tok Muda_CONSTRUCTION.pdf")
OUTPUT_PLAN = ARTIFACT / "v3.4-r14-full-mandatory-runs-plan.json"

WORDS = {
 "ROOF":"屋面","FINISHED":"完成面","STRUCTURE":"结构","DETAIL":"详图","ENGINEER":"工程师","ENGR":"工程师", "ARCH":"建筑师",
 "WATERPROOFING":"防水","WATERPROOF":"防水","GUTTER":"天沟","DOME":"圆顶","WALL":"墙体","CONCRETE":"混凝土","CONC":"混凝土","R.C":"钢筋混凝土",
 "PLASTER":"抹灰","PAINT":"涂料","CEMENT":"水泥","PORCELAIN":"瓷砖","TILES":"瓷砖","TRUSS":"屋架","SLAB":"板","BEAM":"梁","COLUMN":"柱",
 "EXTERNAL":"外侧","INTERNAL":"内侧","THK":"厚","THICK":"厚","MM":"毫米","SPECIALIST":"专业单位","MANUF":"制造商","SPEC":"规范",
 "DOOR":"门","WINDOW":"窗","FLOOR":"地面","CEILING":"天花","LEVEL":"标高","PLAN":"平面图","ELEVATION":"立面图","SECTION":"剖面图",
 "RUANG":"空间","BILIK":"房间","TANDAS":"卫生间","WUDHU":"小净区","KORIDOR":"走廊","LALUAN":"通道","MUSLIMIN":"男用","MUSLIMAH":"女用",
}

def cn(text: str) -> str:
    value = text.upper().replace("\n", " ")
    for en, zh in sorted(WORDS.items(), key=lambda p: -len(p[0])):
        value = re.sub(rf"(?<![A-Z]){re.escape(en)}(?![A-Z])", zh, value)
    # Preserve all dimensional/material tokens verbatim in the bilingual run.
    nums = re.findall(r"\d+(?:\.\d+)?\s*(?:MM|M|°|X|×|:)?", text.upper())
    suffix = "；参数：" + "、".join(nums[:12]) if nums else ""
    return "施工说明：" + value + suffix

def overlap(a,b): return max(a[0],b[0]) < min(a[2],b[2]) and max(a[1],b[1]) < min(a[3],b[3])

def main() -> None:
    build_r13(); plan=json.loads(R13_PLAN.read_text(encoding='utf8'))
    inventory={str(x['candidate_id']):x for x in plan['coverage_inventory']}
    existing={m for b in plan['semantic_blocks'] for m in b['member_ids']}
    with fitz.open(PDF) as doc:
      for page_index,page in enumerate(doc):
       for idx,b in enumerate(page.get_text('blocks')):
        box=[float(x) for x in b[:4]]; source=' '.join(b[4].split())
        # Title-sidebar text stays intact and is handled by the companion
        # policy; body reflow must not enter that protected column.
        if box[0] >= 1028.0 or not re.search(r'[A-Za-z]',source) or not any(re.search(p,source,re.I) for p in ZONES.values()): continue
        members=[cid for cid,x in inventory.items() if int(x['page_index'])==page_index and overlap(box,x['source_bbox'])]
        if not members: continue
        text=cn(source); h=max(12.0,(box[3]-box[1])*2+3); target=[box[0],box[1],min(1035.0,max(box[2],box[0]+min(210,len(source)*2.4+20))),min(834.0,box[1]+h)]
        plan['semantic_blocks'].append({'block_id':f'r14-p{page_index+1:03d}-{idx:03d}','member_ids':members,'page_index':page_index,'coverage_status':'translated','source_text':source,'translated_text':text,'source_bbox':box,'layout_role':'mandatory_bilingual_annotation','placement':{'side':'below','mode':'table_cell','selected_region':target,'candidate_regions':[],'font_size':2.8,'rotation':0,'leader_path':[],'render_text':text,'color':[0.06,0.18,0.52],'preserve_source':False,'exact_ink_masks':[box],'render_runs':[{'text':source,'bbox':[box[0],box[1],target[2],min(target[3],box[1]+max(4,box[3]-box[1]+1))],'font_size':2.3,'font_name':'helv','color':[0,0,0]},{'text':text,'bbox':[box[0],min(target[3]-6,box[1]+max(4,box[3]-box[1]+1)),target[2],target[3]],'font_size':2.8,'font_name':'simhei','color':[0.06,0.18,0.52]}],'instruction':'R14 exact source glyph mask; black source run plus blue Chinese parameter run; no background fill.'}})
    OUTPUT_PLAN.write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n',encoding='utf8'); print(OUTPUT_PLAN)
if __name__=='__main__': main()
