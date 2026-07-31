# ============================================================================
# DEPRECATED - historical V4 sample run. The unified production path is the
# `v4-run` orchestrator in services/engineering_drawing/run_v4.py. This script
# must not write `.release-authorization.json` or copy into the formal
# `v4.0-readable-zone-complete` directory for future runs.
# ============================================================================
from pathlib import Path
import json,re

BASE=Path(r"D:\AmyProjects\business\pdf-manager\output\pdf\engineering-drawing\01_Bilingual_Inline")
rec=json.loads((BASE/r"agent-artifacts/v3.12-human-audit-repair/sample-records.json").read_text(encoding="utf8"))["records"][1]
old=json.loads(Path(rec["old"]).read_text(encoding="utf8")); by={b["block_id"]:b for b in old["semantic_blocks"]}
work=BASE/r"agent-artifacts/v4.0-readable-zone-complete/02";work.mkdir(parents=True,exist_ok=True)
groups=[
([1],"施工图",[1570,70,1625,315],12.0,90,"heading"),
([2,3],"拟拆除并重建雪兰莪州巴生县加埔甘榜托穆达阿依善清真寺",[159,628,1511,716],14.0,0,"project_heading"),
([4,5],"建筑图纸清单｜施工图",[610,796,1200,892],16.0,0,"heading"),
([6],"施工图",[160,952,1510,1002],14.0,0,"table_heading"),
([7],"序号",[160,1015,260,1062],10.0,0,"column_heading"),
([9],"标题",[262,1015,1130,1062],10.0,0,"column_heading"),
([10],"图纸编号",[1130,1015,1460,1062],10.0,0,"column_heading"),
([8],"比例",[1460,1015,1540,1062],10.0,0,"column_heading"),
([11],"总平面图",[262,1062,1130,1112],11.0,0,"category"),
([12],"节点详图、区位图及总平面图",[262,1112,1130,1154],9.5,0,"row"),
([13],"清真寺",[262,1154,1130,1204],11.0,0,"category"),
([14],"地下层平面图",[262,1204,1130,1245],9.5,0,"row"),
([15],"屋面详图1、塔楼详图1与2、整体屋面图",[262,1245,1130,1292],9.2,0,"row"),
([17],"正立面图、背立面图、右侧立面图及左侧立面图",[262,1292,1130,1338],9.0,0,"row"),
([21],"A-A、B-B、C-C、D-D及E-E剖面图",[262,1338,1130,1384],9.0,0,"row"),
([23],"办公楼",[262,1384,1130,1434],11.0,0,"category"),
([24],"地下层平面图及屋面图",[262,1434,1130,1475],9.5,0,"row"),
([25],"正立面图、右侧立面图、背立面图、左侧立面图、X-X及Y-Y剖面图",[262,1475,1130,1520],8.6,0,"row"),
([26],"附属设施",[262,1520,1130,1570],11.0,0,"category"),
([27],"垃圾池、泵房、吸污池及TNB配电站",[262,1570,1130,1614],9.2,0,"row"),
]
used=set();blocks=[]
for n,(ids,zh,cell,fs,rot,role) in enumerate(groups,1):
    src=[by[f"p001-c{i:04d}"] for i in ids];used.update(ids)
    blocks.append({"block_id":f"v4-p001-cell-{n:03d}","page":1,"source_ids":[x["member_ids"][0] for x in src],"source_text":"\n".join(x["source_text"] for x in src),"translation":zh,"zone":"directory_index","role":role,"usable_bbox":cell,"chosen_font_size":fs,"largest_fit_font_size":fs,"padding_points":2.0,"target_height_utilization":0.80,"rotation":rot,"color":"black","preserve_source":True})
blocks[2]["source_text"]="LIST OF ARCHITECTURAL DRAWINGS\nWORKING DRAWING"
blocks[2]["source_ids"].append("p001-visual-list-heading")
literal=[]
for i,b in enumerate(old["semantic_blocks"],1):
    if i not in used:literal.extend(b["member_ids"])
ledger={"schema":"v4.0-directory-cell-ledger","workflow_version":"v4.0-readable-zone-complete","source_pdf":rec["source"],"reference_pdf":rec["reference"],"literal_only_ids":literal,"blocks":blocks,"gates":{"directory_min_pt":6.8,"directory_preferred_min_pt":7.2,"padding_pt":[1.5,3.0],"target_height_utilization":[0.72,0.90],"whole_page_closure":1.0,"directory_index_closure":1.0}}
(work/r"decision-ledger.json").write_text(json.dumps(ledger,ensure_ascii=False,indent=2),encoding="utf8")
print(json.dumps({"blocks":len(blocks),"literal":len(literal),"minimum_planned_font":min(b["chosen_font_size"] for b in blocks),"ledger":str(work/r"decision-ledger.json")},ensure_ascii=False,indent=2))
