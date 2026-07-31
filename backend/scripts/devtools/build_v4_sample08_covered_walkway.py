# ============================================================================
# DEPRECATED - historical V4 sample run. The unified production path is the
# `v4-run` orchestrator in services/engineering_drawing/run_v4.py. This script
# must not write `.release-authorization.json` or copy into the formal
# `v4.0-readable-zone-complete` directory for future runs.
# ============================================================================
from pathlib import Path
import fitz,json,hashlib
ROOT=Path(r"D:\AmyProjects\business\pdf-manager\output\pdf\engineering-drawing\01_Bilingual_Inline");SRC=Path(r"D:\AmyProjects\business\WROK-CONTENT\malasia\A3 DETAIL DRAWING\30_REV. JULAI 2025 LALUAN BERBUMBUNG.pdf");OUT=ROOT/r"translated/v4.0-readable-zone-complete-candidates/08_covered-walkway-specialized-candidate.pdf";WORK=ROOT/r"agent-artifacts/v4.0-readable-zone-complete/08-specialized";BLUE=(.05,.16,.45);BLACK=(0,0,0)
items=[(270,180,"虚线表示屋面边缘"),(270,235,"钢柱按工程师详图"),(270,275,"选用铺路砖，符合专业规范并经建筑师批准"),(650,105,"谷盖板按制造商详图"),(650,155,"2英寸坡度金属波纹屋面，含5mm厚边盖板"),(650,215,"虚线表示钢柱，按工程师详图"),(650,260,"边盖板按制造商详图"),(850,95,"工字梁按工程师详图"),(850,120,"选用金属波纹型材；2英寸坡屋面及5mm厚边盖板"),(850,155,"C型檩条按工程师详图"),(850,185,"照明按机电工程师规范"),(850,215,"钢桁架按工程师详图"),(850,250,"钢柱按工程师详图"),(850,285,"铺路砖按专业规范并经建筑师批准"),(850,315,"钢筋混凝土基础按工程师详图"),(260,520,"现浇混凝土路缘按工程师详图"),(260,555,"互锁混凝土铺砖，经建筑师批准"),(650,520,"谷沟"),(650,555,"边盖板按制造商详图"),(70,390,"平面图A"),(470,390,"屋顶平面图A"),(1030,390,"Y-Y剖面"),(70,685,"平面图B"),(470,685,"屋顶平面图B")]
def put(p,x,y,t,s=5.8,c=BLUE):p.insert_text((x,y),t,fontname="china-s",fontsize=s,color=c,overlay=True)
def reflow(p,r,t):p.draw_rect(r,color=None,fill=(1,1,1),overlay=True);p.insert_textbox(fitz.Rect(r.x0+3,r.y0+3,r.x1-3,r.y1-3),t,fontname="china-s",fontsize=6.4,color=BLACK,overlay=True)
def main():
 d=fitz.open(SRC);p=d[0];f=fitz.Font("china-s");p.insert_font(fontname="china-s",fontbuffer=f.buffer);blocks=[]
 title_positions=[(145,405),(545,405),(1080,405),(145,700),(545,700)]
 for i,(x,y,t) in enumerate(items):
  if i<19:y+=12
  else:x,y=title_positions[i-19]
  put(p,x,y,t,7.2 if i>=19 else 5.8);blocks.append({"block_id":f"body-{i+1:02d}","zone":"drawing_body","render_mode":"preserve_source_blue_chinese","text":t})
 cells=[(fitz.Rect(34,706,345,810),"PROJECT TITLE / 项目名称\nCADANGAN MEROBOH DAN MEMBINA SEMULA MASJID AL-EHSAN KAMPUNG TOK MUDA, KAPAR, DAERAH KLANG, SELANGOR DARUL EHSAN\n拟拆除并重建雪兰莪州巴生县加埔甘榜托穆达阿依善清真寺"),(fitz.Rect(345,706,514,810),"DRAWING TITLE / 图名\nPERINCIAN LALUAN JALAN KAKI BERBUMBUNG / 有盖人行道详图\nPELAN A & B / 平面图A及B\nPELAN BUMBUNG A & B / 屋顶平面图A及B\nKERATAN Y-Y / Y-Y剖面"),(fitz.Rect(514,706,714,810),"AC ARCHITECTS SDN BHD / AC建筑师事务所\nSUITE 8-A0, 5TH LEVEL, TOWER A, PANDAN KAPITAL, PERSIARAN MPAJ, PANDAN INDAH, 55100 SELANGOR DARUL EHSAN\n电话：03-4294 4122  邮箱：acarch.sfb@gmail.com")]
 for i,(r,t) in enumerate(cells):reflow(p,r,t);blocks.append({"block_id":f"footer-b-{i+1}","zone":"prose_or_index_metadata" if i<2 else "company_contact_panel","render_mode":"opaque_bilingual_reflow","text":t})
 for bid,x,y,t in [("status",1040,675,"施工图"),("rev",730,748,"修订：00"),("scale",835,748,"比例：1:100"),("date",930,790,"日期：2025年7月")]:put(p,x,y,t,6.4);blocks.append({"block_id":bid,"zone":"state_bearing_metadata","render_mode":"preserve_source_blue_chinese","text":t})
 OUT.parent.mkdir(parents=True,exist_ok=True);WORK.mkdir(parents=True,exist_ok=True);d.save(OUT,garbage=4,deflate=True);meta={"schema":"v4-sample08-specialized-candidate","source_sha256":hashlib.sha256(SRC.read_bytes()).hexdigest(),"blocks":blocks,"block_count":len(blocks),"status":"candidate_requires_visual_review"};(WORK/"candidate-ledger.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding="utf8");print(json.dumps({"output":str(OUT),"ledger":str(WORK/'candidate-ledger.json'),"blocks":len(blocks)},ensure_ascii=False))
if __name__=="__main__":main()
