# ============================================================================
# DEPRECATED - historical V4 sample run. The unified production path is the
# `v4-run` orchestrator in services/engineering_drawing/run_v4.py. This script
# must not write `.release-authorization.json` or copy into the formal
# `v4.0-readable-zone-complete` directory for future runs.
# ============================================================================
from pathlib import Path
import fitz,json,hashlib
from build_v4_sample06_guard_house import ROOT,BLUE,BLACK,panels
SRC=Path(r"D:\AmyProjects\business\WROK-CONTENT\malasia\报审图纸\275kV MEP Construction Drawing_260610\Construction Drawing\RCJM2 CN ELEC 20260610\Constrcution Drawing PDF\1310-CN-ELEC-PA-C001_PA Schematic.pdf")
OUT=ROOT/r"translated/v4.0-readable-zone-complete-candidates/07_PA_Schematic-specialized-candidate.pdf"; WORK=ROOT/r"agent-artifacts/v4.0-readable-zone-complete/07-specialized"
items=[
(47,410,"主设备安装于32U设备机柜内；位置：275kV控制及继电器室"),(90,535,"以太网桌面寻呼麦克风：可呼叫全部/独立分区或选定分区"),(70,610,"监控工作站及软件设置"),(235,620,"以太网应急寻呼麦克风"),(175,680,"消防报警接口盘；信号来自消防报警系统"),(200,735,"DVD播放器"),(200,775,"数字AM/FM调谐器"),(220,815,"多通道以太网音乐服务器"),(225,850,"IP寻呼控制器"),(230,885,"事件及音频记录器"),(390,700,"24口网络交换机"),(495,700,"以太网网络控制器（BGM/寻呼）"),(625,475,"监视面板"),(620,525,"功率放大器"),(620,565,"功率放大器"),(620,605,"功率放大器"),(620,645,"备用放大器"),(610,715,"网络自动功放切换盘"),(590,790,"免维护密封铅酸蓄电池及充电器；停电时为寻呼系统后备2小时"),(775,570,"6分区解码器"),(820,570,"扬声器线路监控器（6独立分区）"),(950,480,"2×1.5/2.5mm² PVC电缆穿GI管"),(962,515,"分区"),(1035,515,"楼层"),(1110,515,"扬声器类型及数量"),(1235,515,"位置"),(1515,515,"模式"),(1110,615,"数量参见布置图"),(45,1000,"PA系统示意图"),
]
items += [(1030,560,"首层"),(1190,560,"275kV控制及继电器室"),(1030,585,"首层"),(1190,585,"通信室、低压交流室、蓄电池室"),(1030,610,"首层"),(1190,610,"走廊、电缆夹层"),(1030,635,"一层"),(1190,635,"275kV用户开关设备室、11kV开关设备室及蓄电池室"),(1030,660,"一层"),(1190,660,"走廊")]
def urect(p,r): return fitz.Rect(r)*p.derotation_matrix
def put(p,x,y,t,s=6.4,c=BLUE): p.insert_text(fitz.Point(x,y)*p.derotation_matrix,t,fontname="china-s",fontsize=s,color=c,rotate=270,overlay=True)
def main():
 d=fitz.open(SRC);p=d[0];f=fitz.Font("china-s");p.insert_font(fontname="china-s",fontbuffer=f.buffer);blocks=[]
 for i,(x,y,t) in enumerate(items):put(p,x,y,t,5.8 if i not in (0,28) else 7.2);blocks.append({"block_id":f"body-{i+1:02d}","zone":"drawing_body","render_mode":"preserve_source_blue_chinese","text":t})
 bounds=[(250,470),(470,570),(570,705),(705,835),(835,975),(975,1085),(1085,1210)]
 for (y0,y1),(_,_,t) in zip(bounds,panels):
  r=fitz.Rect(2077,y0+2,2375,y1-2);p.draw_rect(urect(p,r),color=None,fill=(1,1,1),overlay=True);p.insert_textbox(urect(p,fitz.Rect(2081,y0+5,2371,y1-5)),t,fontname="china-s",fontsize=6.4,color=BLACK,rotate=270,overlay=True);blocks.append({"block_id":f"company-{y0}","zone":"company_contact_panel","render_mode":"opaque_bilingual_reflow","text":t})
 for bid,x,y,t in [("service",2185,1425,"电气系统"),("title",2185,1470,"用户登陆站：PA系统方框图")]:put(p,x,y,t,6.4);blocks.append({"block_id":bid,"zone":"state_bearing_metadata","render_mode":"preserve_source_blue_chinese","text":t})
 OUT.parent.mkdir(parents=True,exist_ok=True);WORK.mkdir(parents=True,exist_ok=True);d.save(OUT,garbage=4,deflate=True);meta={"schema":"v4-sample07-specialized-candidate","source_sha256":hashlib.sha256(SRC.read_bytes()).hexdigest(),"blocks":blocks,"block_count":len(blocks),"status":"candidate_requires_visual_review"};(WORK/"candidate-ledger.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding="utf8");print(json.dumps({"output":str(OUT),"ledger":str(WORK/'candidate-ledger.json'),"blocks":len(blocks)},ensure_ascii=False))
if __name__=="__main__":main()
