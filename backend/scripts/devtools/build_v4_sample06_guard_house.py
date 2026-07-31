# ============================================================================
# DEPRECATED - historical V4 sample run. The unified production path is the
# `v4-run` orchestrator in services/engineering_drawing/run_v4.py. This script
# must not write `.release-authorization.json` or copy into the formal
# `v4.0-readable-zone-complete` directory for future runs.
# ============================================================================
from pathlib import Path
import fitz, json, hashlib, sys
sys.path[:0]=[str(Path(__file__).resolve().parents[2]),str(Path(__file__).resolve().parents[1])]
from scripts.services.engineering_drawing.orchestration_harness import new_run_identity, validate_handoff

ROOT=Path(r"D:\AmyProjects\business\pdf-manager\output\pdf\engineering-drawing\01_Bilingual_Inline")
SRC=Path(r"D:\AmyProjects\business\WROK-CONTENT\malasia\报审图纸\275kV MEP Construction Drawing_260610\Construction Drawing\RCJM2 CN ELEC 20260610\Constrcution Drawing PDF\1310-CN-ELEC-LTG-B003_Guard House.pdf")
OUT=ROOT/r"translated/v4.0-readable-zone-complete-candidates/06_guard-house-specialized-first-candidate.pdf"
WORK=ROOT/r"agent-artifacts/v4.0-readable-zone-complete/06-specialized"
BLUE=(.05,.16,.45); BLACK=(0,0,0)

legend=[
"18W表面装LED灯（含驱动、支架及全部附件）",
"18W墙装LED灯（含驱动、支架及全部附件）",
"60英寸吊扇点位（含认可挂钩及连接件）","16英寸壁扇（含支架）",
"超亮LED应急灯（3小时镍镉电池及充电器）","单联10A SPN暗装绝缘开关",
"双联10A SPN暗装绝缘开关","三联10A SPN暗装绝缘开关",
"13A开关插座，安装高度距完成地面1400mm。","13A防水开关插座，安装高度距完成地面1400mm。"]
db=[
"2×1C/1.5mm² PVC电缆，穿暗敷PVC管埋地敷设","5路1×18W LED灯管","6路1×18W LED灯管及吊扇/壁扇",
"1路应急灯","4路1×18W LED灯管","备用","备用","2路13A开关插座","2路13A开关插座",
"2路13A开关插座","2路13A开关插座","2路13A开关插座","备用","备用","备用","其他回路",
"车辆道闸控制箱","2×1C/2.5mm² PVC电缆，穿暗敷PVC管埋地敷设","2×1C/4mm² PVC电缆，穿暗敷PVC管敷设",
"60A镀锡硬拉铜母排","60A四极RCCB（100mA）","60A四极RCCB（30mA）","1、2型浪涌保护器，共模及差模（25kA）",
"4×1C 16mm² PVC电缆","60A三极带中性线MCB","进线电源来自EMSB-A","DB-GH，位于门卫室","接地电阻小于1Ω"]
panels=[
(255,371,"LANDOWNER / DEVELOPER\n业主／开发商\nRACKS CENTRAL SDN. BHD.\n公司编号：202401039267 (1585114-W)\n地址：Wisma SP Setia, Unit 05-22 Indah Walk 3, Jalan Indah 15, Taman Bukit Indah, 81200 Johor Bahru, Johor Darul Ta'zim\n电话：07-230 5995  传真：07-230 5959"),
(371,456,"ARCHITECT\n建筑师\nRICHARD W.Z LEE ARCHITECT\n地址：11-01, Medan Aliff Harmoni 1/2, Taman Damansara Aliff, 81200 Johor Bahru, Johor Darul Takzim\n电话：+603-4161 5698"),
(456,561,"BASE BUILD MEP CONSULTANT\n主体建筑机电顾问\nPSB ASSOCIATES SDN. BHD.\n地址：88-01, Jalan Setia Tropika 1/7, Setia Tropika, 81200 Johor Bahru, Johor Darul Ta'zim\n电话：(+607)230 9889  传真：(+607)232 8799"),
(561,660,"C&S CONSULTANT\n土木与结构顾问\nPERUNDING TLK SDN. BHD. (606257-W)\n地址：34-01, Jalan Ros Merah 2/7, Taman Johor Jaya, 81100 Johor Bahru, Johor Darul Ta'zim\n电话：(+607)355 7675  传真：(+607)361 0076"),
(660,760,"DATA CENTRE MEP CONSULTANT\n数据中心机电顾问\nAlpha Consulting Engineers Pte Ltd\n地址：2, BUKIT MERAH CENTRAL #16-01, SINGAPORE 159835\n电话：(65)6276 2228  邮箱：ace@alpha.com.sg\n网站：www.alpha.com.sg"),
(760,850,"MAIN CONTRACTOR\n总承包商\n华西（马来西亚）有限公司 / HUASHI (MALAYSIA) SDN.BHD.\n地址：Wisma Zelan, Level 21, Jalan Tasik Permaisuri 2, Bandar Tun Razak, 56000 Kuala Lumpur, Malaysia\n电话：+603-9174 5568"),
(850,959,"MAIN CONTRACTOR'S MEP CONSULTANT\n总承包商机电顾问\nGREATIANS CONSULTING SDN. BHD. (1043345-H)\n咨询工程师\n地址：A-03A-5, Block A Setiawalk, Persiaran Wawasan, 47160 Pusat Bandar Puchong, Selangor\n电话：+603-5879 3257 / +607-562 0395\n网站：www.greatian.com  邮箱：gc@greatian.com")]

def urect(p,r): return fitz.Rect(r)*p.derotation_matrix
def put(p,x,y,text,size=6.4,color=BLUE):
 q=fitz.Point(x,y)*p.derotation_matrix; p.insert_text(q,text,fontname="china-s",fontsize=size,color=color,rotate=270,overlay=True)
def putv(p,x,y,text,size=5.8,color=BLUE):
 q=fitz.Point(x,y)*p.derotation_matrix; p.insert_text(q,text,fontname="china-s",fontsize=size,color=color,rotate=0,overlay=True)

def main():
 d=fitz.open(SRC); p=d[0]; f=fitz.Font("china-s"); p.insert_font(fontname="china-s",fontbuffer=f.buffer)
 blocks=[]
 for i,t in enumerate(legend):
  x,y=1075,207+i*31; put(p,x,y,t,5.8); blocks.append({"block_id":f"legend-{i+1:02d}","zone":"drawing_body","render_mode":"preserve_source_blue_chinese","text":t})
 for i,t in enumerate(db):
  if i < 19:
   x,y=846+i*37,675; putv(p,x,y,t,5.8)
  else:
   j=i-19; anchors=[(1010,1065),(1130,1065),(1320,1155),(1260,1185),(1180,1210),(1100,1240),(900,1235),(1510,1210),(1570,1240)]; put(p,*anchors[j],f"[{j+1}]",5.8)
   x=830 if j<5 else 1260; y=1350+(j if j<5 else j-5)*24; put(p,x,y,f"[{j+1}] {t}",5.8)
  blocks.append({"block_id":f"db-{i+1:02d}","zone":"drawing_body","render_mode":"preserve_source_blue_chinese","text":t})
 corrected_bounds=[(250,470),(470,570),(570,705),(705,835),(835,975),(975,1085),(1085,1210)]
 for (y0,y1),(_,_,t) in zip(corrected_bounds,panels):
  r=fitz.Rect(2077,y0+2,2375,y1-2); p.draw_rect(urect(p,r),color=None,fill=(1,1,1),overlay=True)
  # B-mode first candidate: the mask is confined to the cell interior; later audit
  # expands this into the recorded per-glyph union.
  q=urect(p,fitz.Rect(2081,y0+5,2371,y1-5)); p.insert_textbox(q,t,fontname="china-s",fontsize=6.4,color=BLACK,rotate=270,overlay=True)
  blocks.append({"block_id":f"company-{y0}","zone":"company_contact_panel","render_mode":"opaque_bilingual_reflow","text":t})
 titles=[("title-bin","垃圾中心—平面电气系统布置图"),("title-guard","门卫室—平面电气系统布置图"),("title-service","电气系统"),("title-sheet","门卫室：平面布置图")]
 put(p,285,468,titles[0][1],7.2); put(p,285,1290,titles[1][1],7.2); put(p,2185,1425,titles[2][1],6.4); put(p,2185,1470,"门卫室：",6.4); put(p,2185,1495,"平面布置图",6.4)
 for bid,t in titles: blocks.append({"block_id":bid,"zone":"state_bearing_metadata","render_mode":"preserve_source_blue_chinese","text":t})
 OUT.parent.mkdir(parents=True,exist_ok=True); WORK.mkdir(parents=True,exist_ok=True); d.save(OUT,garbage=4,deflate=True)
 meta={"schema":"v4-sample06-specialized-first-candidate","source_sha256":hashlib.sha256(SRC.read_bytes()).hexdigest(),"blocks":blocks,"block_count":len(blocks),"status":"candidate_requires_visual_review"}
 (WORK/"first-candidate-ledger.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding="utf8")
 # Deliberately no release authorization and no copy to the formal directory.
 # Publication is a separate post-review command after every required crop has passed.
 print(json.dumps({"output":str(OUT),"ledger":str(WORK/'first-candidate-ledger.json'),"blocks":len(blocks)},ensure_ascii=False))
if __name__=="__main__": main()
