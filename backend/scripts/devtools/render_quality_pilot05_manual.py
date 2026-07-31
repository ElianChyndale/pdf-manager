# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
import json,re,fitz
from pathlib import Path
ROOT=Path(r"D:\AmyProjects\business\pdf-manager")
ART=ROOT/"output/pdf/engineering-drawing/01_Bilingual_Inline/agent-artifacts/v3.12-quality-pilot-05";OUT=ROOT/"output/pdf/engineering-drawing/01_Bilingual_Inline/translated/v3.12-quality-pilot-05-candidates";OUT.mkdir(parents=True,exist_ok=True)
SRC=Path(r"D:\AmyProjects\business\WROK-CONTENT\malasia\报审图纸\275kV MEP Construction Drawing_260610\Construction Drawing\RCJM2 CN ELEC 20260610\Constrcution Drawing PDF\1310-CN-ELEC-ELPS-D001_ELPS Details 1.pdf")
FONT=r"C:\Windows\Fonts\msyh.ttc"
M={"DETAIL":"详图","LIGHTNING EARTH":"防雷接地","ROOF":"屋面","PLATE TYPE TEST CLAMP":"板式测试夹","COVERED IN METAL BOX":"置于金属盒内","REFER DETAIL":"详见详图","REFER TO DETAIL":"详见详图","COPPER TAPE c/w 40mm":"铜带，配40毫米","uPVC CONDUIT":"uPVC线管","RUN ON SURFACE":"明敷","RUN IN PVC CONDUIT":"敷设在PVC导管内","CONCEALED IN COLUMN":"暗敷于柱内","COPPER TAPE":"铜带","TAPE TO & FROM NEXT":"连接至前后相邻处","EARTH CHAMBER":"接地井","EXOTHERMIC WELDING":"放热焊接","COPPER TAPE TO ROD JOINT":"铜带与接地极连接","COPPER TAPE TO COPPER TAPE":"铜带与铜带连接","COPPERBOND EARTHROD":"铜包钢接地极","ROD COUPLIGN":"接地极连接器","COPPER TAPE EARTH GRID":"铜带接地网","SIX WAYS":"六路","MAIN GROUND BAR":"主接地排","METER":"电表","GENSET":"发电机组","EARTH":"接地","TX":"变压器","CABLE CELLAR":"电缆夹层","PVC STRANDED":"PVC绞合","COPPER CABLE":"铜缆","CABLE TO COPPER TAPE":"电缆与铜带连接","INTERLINKING EARTH":"互连接地","FROM EARTH GRID TO PILE CAP":"从接地网至桩帽","COPPER TAPE TO REBAR":"铜带与钢筋连接","TAPE FROM EARTH MAT SYSTEM":"来自接地网系统的铜带","BATTERY":"蓄电池"}
MAN={0:"详图1／防雷接地",12:"详图1a／防雷接地",33:"详图2／电表、发电机组、275/11kV变压器及电缆夹层功能接地",43:"详图3／ETX（F）、NER（F）功能接地",46:"详图4／发电机组（N）接地",54:"详图5／132/33kV变压器（N）接地",70:"详图6／ETX（N）、NER（N）功能接地",79:"详图7／11kV GIS、蓄电池、LVAC及275kV开关设备功能接地",84:"详图8／从接地网至桩帽的互连接地"}
SIDES={0:'below',1:'right',2:'right',3:'right',4:'left',5:'right',6:'left',7:'above',8:'left',9:'left',10:'right',11:'left',12:'below',13:'right',14:'right',15:'right',16:'left',17:'right',18:'left',19:'left',20:'right',21:'left',22:'left',23:'left',24:'right',25:'right',26:'below',27:'right',28:'left',29:'right',30:'above',31:'above',32:'above',33:'below',34:'right',35:'below',36:'right',37:'left',38:'right',39:'above',40:'above',41:'above',42:'right',43:'below',44:'right',45:'left',46:'below',47:'right',48:'above',49:'above',50:'right',51:'right',52:'right',53:'left',54:'below',55:'left',56:'above',57:'above',58:'above',59:'above',60:'right',61:'right',62:'left',63:'right',64:'left',65:'right',66:'above',67:'above',68:'above',69:'right',70:'below',71:'right',72:'right',73:'right',74:'above',75:'left',76:'left',77:'right',78:'left',79:'below',80:'right',81:'right',82:'left',83:'left',84:'below',85:'left',86:'above'}
def zh(i,t):
 if i in MAN:return MAN[i]
 s=t.replace('\n','；').replace(' / ','；')
 for a,b in sorted(M.items(),key=lambda x:-len(x[0])):s=re.sub(re.escape(a),b,s,flags=re.I)
 s=s.replace('(F)','（F）').replace('(N)','（N）').replace('(3nos.)','3根').replace('(2nos.)','2个').replace('c/w','配').replace('COUPLIGN','连接器')
 return s.strip(' -；')
def target(r,side,text,rot):
 fs=4.2;w=max(46,min(210,len(text)*fs*.62));h=max(13,min(35,(len(text)*fs*.62/max(w,1)+1)*fs*1.25));x0,y0,x1,y1=r
 if rot==90:w,h=h,w
 if side=='left':q=[x0-w-4,(y0+y1-h)/2,x0-4,(y0+y1+h)/2]
 elif side=='right':q=[x1+4,(y0+y1-h)/2,x1+4+w,(y0+y1+h)/2]
 elif side=='above':q=[(x0+x1-w)/2,y0-h-4,(x0+x1+w)/2,y0-4]
 else:q=[(x0+x1-w)/2,y1+4,(x0+x1+w)/2,y1+4+h]
 return fitz.Rect(max(3,q[0]),max(3,q[1]),min(2065,q[2]),min(1678,q[3]))
doc=fitz.open(SRC);p=doc[0];ledger=[]
def native_rect(display_rect):
 return fitz.Rect(display_rect)*p.derotation_matrix
for i,b in enumerate(p.get_text('blocks')):
 text=b[4].strip()
 if not text or i>86:continue
 r=fitz.Rect(b[:4])*p.rotation_matrix;rot=90 if (r.height>r.width*2 and text.replace('\n','').lower().endswith('mm')) else 0;z=zh(i,text);side=SIDES[i];q=target(r,side,z,rot);p.insert_textbox(native_rect(q),z,fontname='msyh',fontfile=FONT,fontsize=5.2,color=(.04,.18,.62),rotate=(rot+90)%360,align=0);ledger.append({'block_id':f'body-{i:03d}','source_text':text,'source_bbox':list(r),'translation':z,'zone':'drawing_body','rotation':rot,'chosen_bbox':list(q),'side':side,'leader':[],'visual_reason':f'Visually selected {side} within the same detail panel; source and conductive geometry remain visible.'})
# Visually bounded sidebar panels; redact only ordinary text, never logos or borders.
PANELS=[('owner',[2076,326,2345,461],"土地业主／开发商；RACKS CENTRAL私人有限公司；公司与柔佛州地址、电话及传真信息"),('architect',[2076,471,2345,560],"建筑师：RICHARD W.Z LEE建筑师事务所；柔佛州地址及电话"),('base_mep',[2076,580,2345,692],"主体建筑机电顾问：PSB ASSOCIATES私人有限公司；柔佛州地址、电话及传真"),('cs',[2076,711,2345,830],"土建顾问：PERUNDING TLK私人有限公司；柔佛州地址、电话及传真"),('dc_mep',[2076,836,2345,932],"数据中心机电顾问：Alpha咨询工程师私人有限公司；新加坡地址、电话、邮箱及网站"),('contractor',[2076,982,2345,1061],"总承包商：华西（马来西亚）有限公司；吉隆坡地址及电话"),('contractor_mep',[2076,1091,2345,1208],"总承包商机电顾问：GREATIANS CONSULTING私人有限公司；雪兰莪州地址、电话、传真、网站及邮箱")]
for name,box,z in PANELS:
 r=fitz.Rect(box);src=' / '.join(x[4].strip().replace('\n',' / ') for x in p.get_text('blocks') if x[4].strip() and (fitz.Rect(x[:4])*p.rotation_matrix).intersects(r));p.add_redact_annot(native_rect(r),fill=(1,1,1));ledger.append({'block_id':'sidebar-'+name,'source_text':src,'source_bbox':box,'translation':z,'zone':'company_contact_panel','rotation':0,'chosen_bbox':box,'leader':[],'visual_reason':'Separate visually ruled company/contact subpanel; exact panel text is re-typeset bilingually while logo and borders remain outside the mask.'})
p.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,graphics=0)
for name,box,z in PANELS:
 r=fitz.Rect(box);p.insert_textbox(native_rect(r),z+'\n'+next(x['source_text'] for x in ledger if x['block_id']=='sidebar-'+name),fontname='msyh',fontfile=FONT,fontsize=4.4,color=(0,0,0),lineheight=1.05,rotate=90)
# State/prose fields remain source-visible with nearby blue Chinese.
for box,z in [([2100,200,2335,220],'施工图'),([2077,1212,2340,1400],'项目：RACKS CENTRAL数据中心；包括275/11kV用户进线站、水处理厂、警卫室及带回收区垃圾房；位于柔佛州Plentong工业区'),([2077,1418,2340,1445],'服务：接地与防雷系统'),([2077,1462,2340,1522],'图名：用户进线站防雷安装详图'),([2077,1508,2340,1532],'绘制、设计、审核、比例、日期及修订状态见原文'),([2077,1644,2340,1674],'图号1310-CN-ELEC-ELPS-D001；修订00')]:p.insert_textbox(native_rect(fitz.Rect(box)),z,fontname='msyh',fontfile=FONT,fontsize=5.2,color=(.04,.18,.62),rotate=90);ledger.append({'block_id':'metadata-'+str(len(ledger)),'source_text':'state/prose field','source_bbox':box,'translation':z,'zone':'state_bearing_metadata' if box[1]>=1400 else 'prose_or_index_metadata','rotation':0,'chosen_bbox':box,'leader':[],'visual_reason':'Visually separate project/title/state cell; source symbols, borders and status marks remain visible.'})
pdf=OUT/'1310-CN-ELEC-ELPS-D001_quality-pilot-05.pdf';doc.save(pdf,garbage=4,deflate=True);(ART/'decision-ledger.json').write_text(json.dumps({'schema':'v3.12-quality-pilot05-decision-ledger','blocks':ledger},ensure_ascii=False,indent=2),encoding='utf8');print(pdf)
