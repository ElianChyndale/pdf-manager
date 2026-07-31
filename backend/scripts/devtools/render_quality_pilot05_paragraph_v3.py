# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
import fitz, json
from pathlib import Path

ROOT=Path(r"D:\AmyProjects\business\pdf-manager")
SRC=Path(r"D:\AmyProjects\business\WROK-CONTENT\malasia\报审图纸\275kV MEP Construction Drawing_260610\Construction Drawing\RCJM2 CN ELEC 20260610\Constrcution Drawing PDF\1310-CN-ELEC-ELPS-D001_ELPS Details 1.pdf")
ART=ROOT/r"output/pdf/engineering-drawing/01_Bilingual_Inline/agent-artifacts/v3.12-quality-pilot-05"
OUT=ROOT/r"output/pdf/engineering-drawing/01_Bilingual_Inline/translated/v3.12-quality-pilot-05-candidates"
FONT=r"C:\Windows\Fonts\msyh.ttc"

# Paragraph-level blocks. Each rect was selected in the rotated display coordinate system.
# Dimensions, GF/L1 marks and duplicate bare sizes are intentionally retained as language-neutral source.
G=[
('d1-title',[0],'详图1｜防雷接地',[300,830,500,854],'detail_title'),
('d1-clamp',[4],'板式测试夹，置于金属盒内（详见详图B1）',[205,493,350,520],'callout'),
('d1-surface',[5],'25×3毫米铜带，配40毫米uPVC线管（明敷）',[500,572,650,600],'callout'),
('d1-column',[6],'25×3毫米铜带（敷设在PVC导管内，暗敷于柱内）',[198,320,350,350],'callout'),
('d1-chamber',[8],'25×3毫米铜带，连接前后相邻接地井',[75,695,220,722],'callout'),
('d1-rodjoint',[9],'放热焊接：铜带与接地极连接（详见详图A2）',[70,595,235,623],'callout'),
('d1-tapejoint',[10],'放热焊接：铜带与铜带连接（详见详图A3）',[345,737,515,765],'callout'),
('d1-earthrod',[11],'铜包钢接地极3根，配接地极连接器2个',[50,800,230,828],'equipment_label'),
('d1a-title',[12],'详图1a｜防雷接地',[1015,855,1215,879],'detail_title'),
('d1a-clamp',[16],'板式测试夹，置于金属盒内（详见详图B1）',[845,493,990,520],'callout'),
('d1a-surface',[17],'25×3毫米铜带，配40毫米uPVC线管（明敷）',[1140,572,1290,600],'callout'),
('d1a-chamber',[18],'25×3毫米铜带，连接前后相邻接地井',[680,695,825,722],'callout'),
('d1a-rodjoint',[19],'放热焊接：铜带与接地极连接（详见详图A2）',[710,595,875,623],'callout'),
('d1a-tapejoint',[20],'放热焊接：铜带与铜带连接（详见详图A3）',[980,737,1150,765],'callout'),
('d1a-earthrod',[21],'铜包钢接地极3根，配接地极连接器2个',[915,800,1095,828],'equipment_label'),
('d1a-grid',[22],'50×6毫米铜带接地网',[675,735,815,755],'equipment_label'),
('d2-title',[33],'详图2｜电表、发电机组、275/11kV变压器及电缆夹层功能接地',[1440,835,1900,870],'detail_title'),
('d2-groundbar',[30,31],'六路主接地排',[1600,520,1780,540],'equipment_label'),
('d2-grid',[28],'50×6毫米铜带接地网',[1390,700,1545,720],'equipment_label'),
('d2-joint',[26],'放热焊接：铜带与铜带连接（详见详图A2）',[1710,755,1890,783],'callout'),
('d3-title',[43],'详图3｜ETX（F）、NER（F）及ETX（F）功能接地',[1440,402,1860,430],'detail_title'),
('d3-groundbar',[39,40],'六路主接地排',[1580,125,1760,145],'equipment_label'),
('d3-grid',[37],'50×6毫米铜带接地网',[1350,303,1510,323],'equipment_label'),
('d3-joint',[35],'放热焊接：铜带与铜带连接（详见详图A2）',[1665,360,1845,388],'callout'),
('d6-title',[70],'详图6｜ETX（N）、NER（N）及ETX（N）功能接地',[170,1260,590,1288],'detail_title'),
('d6-groundbar',[66,67],'六路主接地排',[270,985,450,1005],'equipment_label'),
('d6-grid',[64],'50×6毫米铜带接地网',[80,1160,235,1180],'equipment_label'),
('d6-joint',[62],'放热焊接：铜带与铜带连接（详见详图A2）',[390,1218,575,1246],'callout'),
('d5-title',[54],'详图5｜132/33kV变压器（N）功能接地',[950,1255,1350,1283],'detail_title'),
('d5-cable',[56,59],'300毫米PVC绞合铜缆',[1050,935,1240,955],'equipment_label'),
('d5-groundbar',[57,58],'六路主接地排',[1050,978,1230,998],'equipment_label'),
('d5-grid',[53],'50×6毫米铜带接地网',[855,1152,1010,1172],'equipment_label'),
('d5-joint',[60],'放热焊接：电缆与铜带连接（详见详图A4）',[1175,1210,1355,1238],'callout'),
('d4-title',[46],'详图4｜发电机组（N）接地',[950,1585,1135,1607],'detail_title'),
('d4-cable',[48],'300毫米PVC绞合铜缆',[835,1308,1015,1328],'equipment_label'),
('d4-groundbar',[49],'六路主接地排',[760,1355,930,1375],'equipment_label'),
('d4-grid',[45],'50×6毫米铜带接地网',[785,1540,945,1560],'equipment_label'),
('d4-joint',[50],'放热焊接：电缆与铜带连接（详见详图A4）',[1080,1585,1265,1613],'callout'),
('d7-title',[79],'详图7｜11kV GIS、蓄电池、LVAC及275kV开关设备功能接地',[1515,1580,1945,1615],'detail_title'),
('d7-groundbar',[74],'六路主接地排',[1870,1065,2020,1085],'equipment_label'),
('d7-grid',[78],'50×6毫米铜带接地网',[1510,1420,1670,1440],'equipment_label'),
('d7-joint',[77],'放热焊接：铜带与铜带连接（详见详图A2）',[1755,1478,1940,1506],'callout'),
('d8-title',[84],'详图8｜从接地网至桩帽的互连接地',[360,1640,640,1670],'detail_title'),
('d8-mat',[83],'来自接地网系统的50×6毫米铜带',[65,1428,275,1450],'callout'),
('d8-rebar',[81],'放热焊接：铜带与钢筋连接（详见详图A1）',[160,1550,335,1578],'callout'),
('d8-joint',[82],'放热焊接：铜带与铜带连接（详见详图A4）',[70,1490,275,1518],'callout'),
]

S=[
('state','施工图',[2190,198,2335,216],'state_bearing_metadata'),
('owner','土地业主／开发商',[2205,327,2338,340],'company_contact_panel'),
('architect','建筑师',[2290,472,2338,486],'company_contact_panel'),
('base-mep','主体建筑机电顾问',[2200,581,2338,595],'company_contact_panel'),
('cs','土建顾问',[2280,712,2338,726],'company_contact_panel'),
('dc-mep','数据中心机电顾问',[2200,837,2338,851],'company_contact_panel'),
('main-contractor','总承包商',[2280,960,2338,974],'company_contact_panel'),
('contractor-mep','总承包商机电顾问',[2190,1072,2338,1086],'company_contact_panel'),
('project','项目：RACKS CENTRAL数据中心；含用户进线站、水处理厂、警卫室及带回收区垃圾房',[2080,1374,2338,1397],'prose_or_index_metadata'),
('service','服务：接地与防雷',[2195,1398,2338,1410],'state_bearing_metadata'),
('drawing-title','图名：用户进线站防雷安装详图（一）',[2100,1510,2338,1530],'state_bearing_metadata'),
('number','图号：1310-CN-ELEC-ELPS-D001｜修订：00',[2080,1643,2338,1663],'state_bearing_metadata')]

doc=fitz.open(SRC); p=doc[0]
blocks=p.get_text('blocks')
def native(r): return fitz.Rect(r)*p.derotation_matrix
ledger=[]
for bid,srcids,zh,box,zone in G:
    src=' / '.join(blocks[i][4].strip().replace('\n',' / ') for i in srcids)
    rect=native(box); fs=8.2 if zone=='detail_title' else 7.2
    rc=p.insert_textbox(rect,zh,fontname='msyh',fontfile=FONT,fontsize=fs,color=(.02,.22,.72),rotate=270,align=1 if zone=='detail_title' else 0,lineheight=1.05)
    ledger.append({'block_id':bid,'source_ids':srcids,'source_text':src,'translation':zh,'zone':zone,'chosen_bbox':box,'font_size':fs,'fit_result':rc,'decision':'complete paragraph kept intact; placed in adjacent white space'})
for bid,zh,box,zone in S:
    rect=native(box)
    fs=4.6 if bid=='project' else 4.8 if bid=='service' else 5.6 if zone=='company_contact_panel' else 6.2
    rc=p.insert_textbox(rect,zh,fontname='msyh',fontfile=FONT,fontsize=fs,color=(0,0,0) if zone!='state_bearing_metadata' else (.02,.22,.72),rotate=270,align=0,lineheight=1.02)
    ledger.append({'block_id':'sidebar-'+bid,'source_text':'corresponding sidebar cell','translation':zh,'zone':zone,'chosen_bbox':box,'font_size':fs,'fit_result':rc,'decision':'preserve English, logo and cell border; add Chinese only in selected cell whitespace'})
OUT.mkdir(parents=True,exist_ok=True); ART.mkdir(parents=True,exist_ok=True)
pdf=OUT/'1310-CN-ELEC-ELPS-D001_quality-pilot-05-v3.pdf'
doc.save(pdf,garbage=4,deflate=True)
(ART/'paragraph-decision-ledger-v3.json').write_text(json.dumps({'schema':'v3.12-paragraph-decision-ledger','count':len(ledger),'blocks':ledger},ensure_ascii=False,indent=2),encoding='utf8')
rd=fitz.open(pdf); rd[0].get_pixmap(matrix=fitz.Matrix(2,2),alpha=False).save(ART/'candidate-v3-page-0001.png')
print(pdf); print('negative_fit',sum(1 for x in ledger if x['fit_result']<0),[x['block_id'] for x in ledger if x['fit_result']<0])
