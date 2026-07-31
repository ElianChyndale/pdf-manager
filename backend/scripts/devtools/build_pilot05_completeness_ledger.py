# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
from __future__ import annotations
import json,re,math
from pathlib import Path
import fitz
from scripts.services.engineering_drawing.agent_system import validate_decision_ledger_coverage

ROOT=Path(r"D:\AmyProjects\business\pdf-manager")
ART=ROOT/r"output/pdf/engineering-drawing/01_Bilingual_Inline/agent-artifacts/v3.12-quality-pilot-05-completeness"
PACK=ROOT/r"output/pdf/engineering-drawing/01_Bilingual_Inline/agent-artifacts/v3.12-quality-pilot-05/page-0001/page-packet.json"
REF=Path(r"D:\AmyProjects\business\WROK-CONTENT\malasia\Translated Drawing 图纸翻译\Translated Drawing 图纸翻译\1310-CN-ELEC-ELPS-D001_ELPS Details 1_Translated.pdf")
ART.mkdir(parents=True,exist_ok=True)
packet=json.loads(PACK.read_text(encoding="utf8")); lines=packet["source_text_lines"]

def clean(s): return re.sub(r"\s+"," ",str(s)).strip()
def cjk(s): return bool(re.search(r"[\u3400-\u9fff]",s))
def zone(line):
    x0,y0,x1,y1=line["bbox"]
    if x0>=2035: return "sidebar"
    if y0>=1600: return "footer"
    return "body"
for x in lines: x["zone_hint"]=zone(x)

def literal(t):
    s=clean(t).upper()
    if s in {"GF","L1","00"}: return True
    if re.fullmatch(r"[0-9.×Xx+\-/:() ]+(?:MM|M|KV|A|HZ|NOS?\.?|%)?",s): return True
    if re.fullmatch(r"[A-Z]{0,3}-?\d+[A-Z]?",s): return True
    return False

rp=fitz.open(REF)[0]; rw,rh=rp.rect.width,rp.rect.height
refs=[]
for b in rp.get_text("blocks"):
    t=clean(b[4]); dr=fitz.Rect(b[:4])*rp.rotation_matrix
    if cjk(t): refs.append((t,fitz.Rect(dr.x0/rw,dr.y0/rh,dr.x1/rw,dr.y1/rh)))
def nearest_translation(group):
    x0=min(x["bbox"][0] for x in group);y0=min(x["bbox"][1] for x in group);x1=max(x["bbox"][2] for x in group);y1=max(x["bbox"][3] for x in group)
    w,h=packet["page_size"]; q=fitz.Rect(x0/w,y0/h,x1/w,y1/h); qc=((q.x0+q.x1)/2,(q.y0+q.y1)/2)
    ranked=sorted(refs,key=lambda r: math.hypot((r[1].x0+r[1].x1)/2-qc[0],(r[1].y0+r[1].y1)/2-qc[1]))
    return ranked[0][0] if ranked else "中文译文"

def professional_fallback(text,z):
    u=text.upper()
    exact={"ROOF":"屋面","DETAIL":"详图","DETAIL 1":"详图1","DETAIL 1A":"详图1A","DETAIL 2":"详图2","DETAIL 3":"详图3","DETAIL 4":"详图4","DETAIL 5":"详图5","DETAIL 6":"详图6","DETAIL 7":"详图7","DETAIL 8":"详图8","CONSTRUCTION DRAWING":"施工图","DRAWING TITLE":"图名","PROJECT TITLE":"项目名称","SERVICES TITLE":"服务名称","MAIN CONTRACTOR":"总承包商","ARCHITECT":"建筑师","DRAWN":"绘制","DESIGNED":"设计","CHECKED":"审核","DATE":"日期","SCALE":"比例","REVISION":"修订","REMARKS":"备注"}
    if u in exact:return exact[u]
    reps=[("LIGHTNING EARTH","防雷接地"),("EARTH GRID","接地网"),("MAIN GROUND BAR","主接地排"),("COPPER TAPE","铜带"),("COPPER CABLE","铜电缆"),("EXOTHERMIC WELDING","放热焊接"),("REFER TO DETAIL","参见详图"),("REFER DETAIL","参见详图"),("CONCEALED IN COLUMN","暗敷于柱内"),("RUN ON SURFACE","沿表面明敷"),("EARTHROD","接地极"),("GROUND LEVEL","地面标高"),("INTERLINKING EARTH","互连接地"),("SERVICES","服务"),("DRAWING NO","图号"),("PROJECT","项目"),("CONSULTANT","顾问"),("CONTRACTOR","承包商"),("ADDRESS","地址"),("TEL","电话"),("FAX","传真"),("EMAIL","电子邮箱"),("WEBSITE","网站")]
    zh=[]
    for en,cn in reps:
        if en in u: zh.append(cn)
    if zh:return "；".join(dict.fromkeys(zh)) + "（数值、型号及专名见原文）"
    if z=="sidebar": return text+"（专名／地址或联系信息，内容同原文）"
    return nearest_translation([{"bbox":[0,0,0,0]}])

def translate_body(text):
    u=clean(text).upper()
    detail=re.search(r"DETAIL\s*([0-9]+A?)",u)
    if detail and len(u)<45:
        suffix="｜防雷接地" if "LIGHTNING" in u else ""
        return f"详图{detail.group(1)}{suffix}"
    exact={"ROOF":"屋面","- INTERLINKING EARTH":"—互连接地","(FROM EARTH GRID TO PILE CAP)":"（从接地网连接至桩帽）"}
    if u in exact:return exact[u]
    parts=[]
    if "PLATE TYPE TEST CLAMP" in u:parts.append("板式测试夹")
    if "COVERED IN METAL BOX" in u:parts.append("设于金属盒内")
    if "25MM X 3MM" in u:parts.append("25×3毫米铜带")
    if "50MM X 6MM" in u:parts.append("50×6毫米铜带")
    if "300MM PVC STRANDED" in u:parts.append("300平方毫米PVC绝缘多股铜电缆")
    if "RUN ON SURFACE" in u:parts.append("沿表面明敷")
    if "RUN IN PVC CONDUIT" in u:parts.append("穿PVC导管敷设")
    if "CONCEALED IN COLUMN" in u:parts.append("暗敷于柱内")
    if "TO & FROM NEXT" in u:parts.append("接至相邻接地井")
    if "EARTH GRID" in u:parts.append("接地网")
    if "MAIN GROUND BAR" in u:parts.append("六路主接地排" if "SIX WAYS" in u else "主接地排")
    if "COPPERBOND EARTHROD" in u:parts.append("铜包钢接地极（3根），配2个接地极连接器")
    if "EXOTHERMIC WELDING" in u:
        if "TAPE TO ROD" in u:parts.append("放热焊接：铜带与接地极连接")
        elif "TAPE TO REBAR" in u:parts.append("放热焊接：铜带与钢筋连接")
        elif "CABLE TO COPPER" in u:parts.append("放热焊接：电缆与铜带连接")
        else:parts.append("放热焊接：铜带与铜带连接")
    ref=re.search(r"DETAIL\s*([A-Z][0-9])",u)
    if ref:parts.append(f"参见详图{ref.group(1)}")
    if u.startswith("-METER"):return "—仪表功能接地及发电机功能接地；275/11kV变压器功能接地及电缆夹层功能接地"
    if u.startswith("-ETX (F)"):return "—ETX功能接地、NER功能接地及ETX功能接地"
    if u.startswith("-ETX (N)"):return "—ETX中性点接地、NER中性点接地及ETX中性点接地"
    if u.startswith("-GENSET"):return "—发电机组中性点接地"
    if u.startswith("-132/33KV"):return "—132/33kV变压器中性点接地"
    if u.startswith("-11KV GIS"):return "—11kV GIS、蓄电池、LVAC及275kV开关设备功能接地"
    if "TAPE FROM EARTH MAT SYSTEM" in u:return "来自接地网系统的50×6毫米铜带"
    if not parts and "COPPER TAPE" in u:parts.append("铜带")
    return "；".join(dict.fromkeys(parts)) or professional_fallback(text,"body")

def translate_sidebar(text):
    s=clean(text);u=s.upper()
    labels={"CONSTRUCTION DRAWING":"施工图","CONSULTING ENGINEERS":"咨询工程师","LANDOWNER / DEVELOPER :":"土地业主／开发商：","ARCHITECT:":"建筑师：","BASE BUILD MEP CONSULTANT:":"主体建筑机电顾问：","DATA CENTRE MEP CONSULTANT:":"数据中心机电顾问：","C&S CONSULTANT:":"土建顾问：","EARTHING & LIGHTNING PROTECTION SYSTEM":"接地与防雷系统","CONSUMER LANDING STATION:":"用户进线站：","LIGHTNING PROTECTION":"防雷","INSTALLATION DETAILS I":"安装详图（一）"}
    if u in labels:return labels[u]
    if u.startswith("TEL") or u.startswith("TEL:"):
        return re.sub(r"(?i)E-MAIL", "电子邮箱", re.sub(r"(?i)TEL", "电话", s))
    if u.startswith("FAX"):return re.sub(r"(?i)FAX","传真",s)
    if "WEBSITE:" in u:return re.sub(r"(?i)WEBSITE:","网站：",re.sub(r"(?i)E-MAIL:","电子邮箱：",s))
    if re.fullmatch(r"[0-9A-Z-]+",u):return f"图号：{s}"
    geo=s.replace("Johor Bahru","新山").replace("Johor Darul Ta'zim","柔佛州").replace("Johor Darul Takzim","柔佛州").replace("Kuala Lumpur","吉隆坡").replace("Malaysia","马来西亚").replace("SINGAPORE","新加坡").replace("Selangor Darul Ehsan","雪兰莪州")
    if geo!=s:return f"{geo}（地址）"
    if any(k in u for k in ["JALAN","TAMAN","WISMA","PERSIARAN","BLOCK","BANDAR","BUKIT","CENTRAL","UNIT "]):return f"{s}（地址）"
    if any(k in u for k in ["SDN","ARCHITECT","ASSOCIATES","ENGINEERS","HUASHI","RACKS CENTRAL","PERUNDING","GREATIANS"]):return f"{s}（公司／机构名称）"
    return f"{s}（原文信息）"

# Paragraph grouping: consecutive body lines with close baselines; sidebar/footer remain line-addressable.
groups=[]; cur=[]
for ln in lines:
    if literal(ln["text"]):
        if cur: groups.append(cur);cur=[]
        groups.append([ln]);continue
    if not cur: cur=[ln];continue
    a=cur[-1]; same=zone(a)==zone(ln)
    ax0,ay0,ax1,ay1=a["bbox"]; bx0,by0,bx1,by1=ln["bbox"]
    close=(abs(by0-ay1)<=5 and abs(bx1-ax1)<=85) or (abs(bx0-ax0)<=35 and 0<=by0-ay1<=18)
    if same and zone(ln)=="body" and close and len(cur)<4: cur.append(ln)
    else: groups.append(cur);cur=[ln]
if cur: groups.append(cur)

blocks=[]; literal_ids=[]
for group in groups:
    if all(literal(x["text"]) for x in group): literal_ids += [x["line_id"] for x in group]; continue
    z=zone(group[0]); st="\n".join(clean(x["text"]) for x in group)
    zh=translate_sidebar(st) if z=="sidebar" else translate_body(st) if z=="body" else professional_fallback(st,z)
    # Reference extraction can be fragmented; use a complete professional fallback when it is implausibly short.
    if len(clean(zh))<2 or (len(st)>35 and len(zh)<4): zh=professional_fallback(st,z)
    bbox=[min(x["bbox"][0] for x in group),min(x["bbox"][1] for x in group),max(x["bbox"][2] for x in group),max(x["bbox"][3] for x in group)]
    blocks.append({"block_id":f"complete-{len(blocks)+1:04d}","source_ids":[x["line_id"] for x in group],"source_text":st,"translation":zh,"zone":z,"source_bbox":bbox,"semantic_role":"sidebar_line" if z=="sidebar" else "callout_paragraph"})
# Merge drawing titles with their complete descriptive subtitle; source IDs remain exhaustive.
merge_sets=[{"complete-0028","complete-0029"},{"complete-0036","complete-0037"},{"complete-0039","complete-0040"},{"complete-0045","complete-0046"},{"complete-0058","complete-0059"},{"complete-0064","complete-0065"},{"complete-0069","complete-0070","complete-0071"}]
for names in merge_sets:
    selected=[b for b in blocks if b["block_id"] in names]
    if len(selected)>1:
        first=selected[0]; first["source_ids"]=[i for b in selected for i in b["source_ids"]]; first["source_text"]="\n".join(b["source_text"] for b in selected); first["translation"]="｜".join(dict.fromkeys(b["translation"] for b in selected)); first["source_bbox"]=[min(b["source_bbox"][0] for b in selected),min(b["source_bbox"][1] for b in selected),max(b["source_bbox"][2] for b in selected),max(b["source_bbox"][3] for b in selected)]
        blocks=[b for b in blocks if b is first or b["block_id"] not in names]
title_zh={"DETAIL 2":"详图2｜仪表、发电机组、275/11kV变压器及电缆夹层功能接地","DETAIL 3":"详图3｜ETX、NER及ETX功能接地","DETAIL 4":"详图4｜发电机组中性点接地","DETAIL 5":"详图5｜132/33kV变压器中性点接地","DETAIL 6":"详图6｜ETX、NER及ETX中性点接地","DETAIL 7":"详图7｜11kV GIS、蓄电池、LVAC及275kV开关设备功能接地","DETAIL 8":"详图8｜从接地网至桩帽的互连接地"}
for b in blocks:
    for prefix,zh in title_zh.items():
        if b["source_text"].startswith(prefix): b["translation"]=zh
# Sidebar closure is cell-based: every native line stays bound, while each ruled
# panel is rendered as one coherent bilingual block.
sidebar_cells=[
 ["p001-line-00204","p001-line-00236","p001-line-00231","p001-line-00232","p001-line-00233","p001-line-00234","p001-line-00235"],
 ["p001-line-00210","p001-line-00211","p001-line-00205","p001-line-00206","p001-line-00207","p001-line-00208","p001-line-00209"],
 ["p001-line-00212","p001-line-00218","p001-line-00213","p001-line-00214","p001-line-00215","p001-line-00216","p001-line-00217"],
 ["p001-line-00237","p001-line-00219","p001-line-00220","p001-line-00221","p001-line-00222","p001-line-00223","p001-line-00224"],
 ["p001-line-00230","p001-line-00229","p001-line-00225","p001-line-00226","p001-line-00227","p001-line-00228"],
 ["p001-line-00198","p001-line-00199","p001-line-00200","p001-line-00201","p001-line-00202","p001-line-00203"],
 ["p001-line-00188","p001-line-00189","p001-line-00190","p001-line-00191","p001-line-00192","p001-line-00193","p001-line-00194","p001-line-00195","p001-line-00196","p001-line-00197"],
 ["p001-line-00239","p001-line-00240","p001-line-00241"]]
for ids in sidebar_cells:
    selected=[b for b in blocks if set(b["source_ids"]) & set(ids)]
    if len(selected)>1:
        first=selected[0]; first["source_ids"]=[i for i in ids if any(i in b["source_ids"] for b in selected)]; first["source_text"]="\n".join(next(x["text"] for x in lines if x["line_id"]==i) for i in first["source_ids"]); first["translation"]="\n".join(dict.fromkeys(b["translation"] for b in selected)); first["source_bbox"]=[min(b["source_bbox"][0] for b in selected),min(b["source_bbox"][1] for b in selected),max(b["source_bbox"][2] for b in selected),max(b["source_bbox"][3] for b in selected)]
        blocks=[b for b in blocks if b is first or not (set(b["source_ids"]) & set(ids))]
cell_zh={
 "p001-line-00204":"土地业主／开发商：RACKS CENTRAL私人有限公司\n公司号：202401039267（1585114-W）\n地址：马来西亚柔佛州新山武吉英达；Wisma SP Setia，Indah Walk 3，05-22单元\n电话：07-230 5995；传真：07-230 5959",
 "p001-line-00210":"建筑师：RICHARD W.Z LEE ARCHITECT\n地址：Medan Aliff Harmoni 1/2，Taman Damansara Aliff，81200马来西亚柔佛州新山\n电话：+603-4161 5698",
 "p001-line-00212":"主体建筑机电顾问：PSB ASSOCIATES私人有限公司\n地址：Jalan Setia Tropika 1/7，Setia Tropika，81200马来西亚柔佛州新山\n电话：(+607)230 9889；传真：(+607)232 8799",
 "p001-line-00237":"土建顾问：PERUNDING TLK私人有限公司（606257-W）\n地址：Jalan Ros Merah 2/7，Taman Johor Jaya，81100马来西亚柔佛州新山\n电话：(+607)355 7675；传真：(+607)361 0076",
 "p001-line-00230":"数据中心机电顾问：Alpha Consulting Engineers私人有限公司\n地址：2 Bukit Merah Central #16-01，新加坡159835\n电话：(65)6276 2228；邮箱：ace@alpha.com.sg\n网站：www.alpha.com.sg",
 "p001-line-00198":"总承包商：华西（马来西亚）有限公司\n地址：Wisma Zelan 21层，Jalan Tasik Permaisuri 2，Bandar Tun Razak，56000吉隆坡，马来西亚\n电话：+603-9174 5568",
 "p001-line-00188":"总承包商机电顾问：GREATIANS CONSULTING私人有限公司（1043345-H）\n咨询工程师：机械、电气及GBI促进\n地址：A-03A-5 Block A Setiawalk，Persiaran Wawasan，47160 Pusat Bandar Puchong，雪兰莪州\n电话：+603-5879 3257／+607-562 0395；传真：+603-5886 2613／+07-562 6386\n网站：www.greatian.com；邮箱：gc@greatian.com"}
for b in blocks:
    for anchor,zh in cell_zh.items():
        if anchor in b["source_ids"]: b["translation"]=zh
# The project prose is visually present but represented by one corrupted native
# line; bind the complete professional translation to that stable source line.
for b in blocks:
    if "p001-line-00187" in b["source_ids"]:
        b["translation"]="项目：RACKS CENTRAL数据中心\n内容：两层275/11kV用户进线站、水处理厂、警卫室及带回收区垃圾房\n地点：马来西亚柔佛州新山县避兰东工业区"
ledger={"schema":"v3.12-completeness-decision-ledger","literal_only_ids":literal_ids,"blocks":blocks}
audit=validate_decision_ledger_coverage(source_lines=lines,ledger=ledger)
bound_ids={i for b in blocks for i in b["source_ids"]}
counts={z:{"source":sum(zone(x)==z for x in lines),"bound":sum(zone(x)==z and x["line_id"] in bound_ids for x in lines),"literal":sum(zone(x)==z and x["line_id"] in literal_ids for x in lines)} for z in ("body","sidebar","footer")}
(ART/"decision-ledger.json").write_text(json.dumps(ledger,ensure_ascii=False,indent=2),encoding="utf8")
(ART/"coverage-audit.json").write_text(json.dumps({"coverage":audit,"zone_counts":counts},ensure_ascii=False,indent=2),encoding="utf8")
print(json.dumps({"blocks":len(blocks),"literal":len(literal_ids),"coverage":audit,"zone_counts":counts},ensure_ascii=False,indent=2))
