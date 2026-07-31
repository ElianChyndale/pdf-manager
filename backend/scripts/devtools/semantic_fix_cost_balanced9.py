# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
import json, hashlib, shutil, sys
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(r"D:\AmyProjects\business\pdf-manager"); sys.path.insert(0,str(ROOT/"backend/scripts"))
from services.engineering_drawing.multimodal_plan import validate_multimodal_plan
from services.engineering_drawing.supervisor_contract import validate_real_supervisor_plan
from services.engineering_drawing.supervisor_bundle import create_supervisor_run_bundle
BASE=ROOT/"output/pdf/engineering-drawing/01_Bilingual_Inline/agent-artifacts/v3.11-cost-balanced-9"
ZH={
2:["项目：阿尔-埃赫桑清真寺","建议拆除并重建雪兰莪州巴生县加帕尔Tok Muda村阿尔-埃赫桑清真寺","标准平面图","图纸名称","标准详图1","详图1","修订；绘制","外露高度","日期2025年7月；比例1:5；图号ACASB 2401/MTM/RCP/DT-01；绘制APIZ","地面标高","施工图；日期；更正","埋深按设计要求","锚固件","备注；图纸","修订","标准立面，比例1:5","标准X-X剖面，比例1:5"],
3:["详图B","Ø75毫米不锈钢管","2根不锈钢实心杆；Ø100毫米不锈钢管","Ø100毫米不锈钢管","详图A","按详图焊接至管件","地面标高","碎石垫层；不锈钢盖帽","按坡度铺设；20毫米厚水泥砂浆找平层；75毫米厚混凝土地坪；不锈钢盖帽","详图A，比例1:5；3.2毫米厚不锈钢U形卡","A-A剖面，比例1:50；素混凝土基础按工程师详图","立面及B-B剖面，比例1:50","Ø75毫米不锈钢管；6毫米螺栓；50毫米滑轮按厂家详图并焊至钢管","450×450×900毫米混凝土基础（1:3:6）按工程师详图；20毫米找平层找坡；75毫米混凝土地坪","3.2毫米厚不锈钢U形卡；50毫米滑轮、螺栓、6毫米尼龙绳及垫圈按厂家详图","办公室平面图，比例1:50；阿尔-埃赫桑清真寺拆除重建工程","图纸名称","AC建筑设计私人有限公司，Pandan Kapital A座5层8-AD室","图号","详图B，比例1:5；施工图修订记录","雪兰莪州巴生县加帕尔Tok Muda村","阿尔-埃赫桑清真寺","标准旗杆：A-A、B-B剖面、立面及详图A、B","AC建筑设计私人有限公司；邮箱acarch.sb@gmail.com","Pandan Kapital A座","绘制NAZMI；日期2025年7月；修订00；比例1:50","图号ACASB 2401/MTM/TB/DT-01"],
4:["铜带与钢筋及铜带之间采用放热焊接；25×3、50×6毫米铜带；六路主接地排；屋面暗敷PVC管内，详见A1/A4","接地井内铜包钢接地极3根、接杆2个；铜带与接地极放热焊接；板式测试夹置金属盒内；详见A2/B1","50×6及25×3毫米铜带；六路主接地排；放热焊接；日期、绘制、审核及业主栏","详图6/8：ETX、NER接地及接地网至桩帽联结；铜带、测试夹、接地井和主接地排按A2/A3/B1","详图1防雷接地：25×3毫米铜带穿40毫米uPVC明敷；接头放热焊接；测试夹置金属盒内","详图3：ETX(F)、NER(F)接地；50×6毫米铜带及六路主接地排；参建单位资料","防雷接地详图1：50×6毫米接地网、六路主接地排、300毫米PVC绞合铜缆及接地井","防雷接地详图1a：25×3毫米铜带、接地极、测试夹及接地井；穿PVC管暗敷或明敷","详图2：电表、发电机、275/11kV变压器及电缆夹层功能接地；铜带放热焊接","详图4至6：发电机、132/33kV变压器、ETX及NER中性点接地；300毫米PVC绞合铜缆","详图1a及5：防雷和132/33kV变压器中性点接地；铜带明敷于40毫米uPVC管，接头放热焊接","屋面六路主接地排；主承包商机电顾问资料；Racks Central数据中心项目概况","详图8：50×6毫米接地网与桩帽联结；铜带与钢筋放热焊接","六路主接地排由50×6毫米接地网引入；铜带接头放热焊接，详见A4","详图3/4：发电机接地；50×6毫米铜带及电缆与铜带放热焊接，详见A4","50×6毫米铜带接地网连接六路主接地排","安装详图7：275kV开关设备、11kV GIS、电池及LVAC功能接地；绘制AISYAH，设计BRYAN，2026年6月","用户进线站接地与防雷系统详图；50×6毫米铜带接头放热焊接；项目位于柔佛州Plentong"],
5:["围裙区；1500升渗滤液桶；垃圾房；240升回收桶；回路GH-R2","图例：1×18W LED表面或壁装灯具，含驱动、支架及附件；60英寸吊扇点含挂钩和连接件","施工图；日期；绘制；审核；说明；业主/开发商","垃圾房平面：围裙区、厕所、B型围栏、服务器区、屋面线、1500升渗滤液桶；比例1:50","走道及回收区：16英寸壁扇；13A防水开关插座高1400毫米；3小时LED应急灯；10A单联开关","Racks Central及PSB Associates公司资料","门卫室周边：走道、围裙区、登记区、屋面线、检查区；回路GH-Y4、GH-B3","B型围栏；坡道坡度1:3；垃圾房；2×1芯1.5平方毫米PVC电缆及1.5平方毫米保护导体","顾问资料；地下暗敷PVC/AWA/PVC电缆及2×1芯2.5平方毫米PVC电缆、2.5平方毫米保护导体","门卫室配电范围：GH-Y1/Y3、GH-R3/R4、GH-B1及配电箱DB-GH","配电回路：10kA；1盏应急灯；5或4支1×18W LED灯管；备用；10A及20A单极断路器","车辆道闸控制箱及保护导体；主承包商机电顾问资料；Racks Central数据中心项目概况","门卫室电气系统平面布置图，比例1:50；走道","围裙区；入口；回路GH-Y1","电源由EMSB-A引至门卫室DB-GH配电箱","铜母排；100mA漏电动作；60A微型断路器及漏电断路器","门卫室电气系统：I、II级浪涌保护器；共模/差模25kA；4×1芯16平方毫米PVC电缆；柔佛州Plentong项目","绘制AISYAH；设计BRYAN；审核Y.P TAN；日期2026年6月；比例按图；图号及修订"],
7:["日期、绘制、审核及说明；业主Racks Central私人有限公司资料","建筑师Richard W.Z Lee及柔佛州地址、电话资料","土建顾问及基础机电顾问PSB Associates资料","数据中心机电顾问Perunding TLK资料","Alpha咨询工程师及华石公司资料","华石（马来西亚）及主承包商机电顾问Greatians资料","Racks Central数据中心项目：两层275/11kV用户进线站及水处理厂；顾问联系资料","音频/事件记录器：启用、向下、确认、菜单、下一项","以太网寻呼服务器","施工图","监控工作站及软件设于275kV控制继保室；以太网桌面/紧急寻呼话筒；32U机柜内主设备及信号输入","电源监视盘、功率放大器、备用放大器及1A至2A分区状态","扬声器分区、位置及数量按布置图；2×1.5/2.5平方毫米PVC电缆穿镀锌钢管；含275kV、11kV开关室、电池室、通信室及走道","工作模式：紧急语音/公共广播/背景音乐，或紧急语音/公共广播","火灾报警接口盘、DVD及AM/FM多频道以太网音乐服务器、IP寻呼控制器，采用UTP Cat6电缆","网络自动放大器切换盘；免维护铅酸电池及充电器在断电时为寻呼系统供电2小时；放大器数量容量按各区扬声器设计","Racks Central用户进线站电气系统公共广播原理框图；项目位于柔佛州Plentong；绘制AISYAH，设计BRYAN，2026年6月"]}
def sha(x): return hashlib.sha256((json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode()).hexdigest()
recs=json.loads((BASE/"sample-records.json").read_text(encoding="utf-8"))["records"]
for rec in recs:
    n=rec["sample_index"]
    if n not in ZH and n != 1: continue
    w=Path(rec["artifact_dir"]); p=json.loads((w/"supervisor-plan.json").read_text(encoding="utf-8")); vals=ZH.get(n,[b["translated_text"] for b in p["semantic_blocks"]])
    assert len(vals)==len(p["semantic_blocks"]),(n,len(vals),len(p["semantic_blocks"]))
    for b,z in zip(p["semantic_blocks"],vals): b["translated_text"]=z; b["placement"]["render_text"]=z
    stamp=datetime.now(timezone.utc).isoformat(); inv=f"sol-light-human-semantic-{n:02d}-{int(datetime.now().timestamp())}"
    raw={"schema":"sol-light-human-semantic-correction-v1","sample":n,"geometry_changed":False,"corrected_blocks":len(vals),"reference_usage":"translation_evidence_only"}
    p["supervisor_invocation"].update({"invocation_id":inv,"started_at":stamp,"completed_at":stamp,"response_sha256":sha(raw)})
    p=validate_multimodal_plan(p,source_pdf_path=Path(rec["source_pdf"])); p=validate_real_supervisor_plan(p,source_pdf_path=Path(rec["source_pdf"]),require_final_review=False)
    (w/"supervisor-plan.json").write_text(json.dumps(p,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    shutil.rmtree(w/"supervisor-run",ignore_errors=True); m=json.loads((w/"agent-manifest.json").read_text(encoding="utf-8"))
    create_supervisor_run_bundle(bundle_dir=w/"supervisor-run",source_pdf_path=Path(rec["source_pdf"]),page_images=[Path(x["source_image"]) for x in m["pages"]],request={"task":"human semantic correction at fixed approved geometry","reference_usage":"translation_evidence_only"},raw_response=raw,normalized_plan=p,invocation_id=inv,agent_id="sol_light_supervisor",started_at=stamp,completed_at=stamp)
