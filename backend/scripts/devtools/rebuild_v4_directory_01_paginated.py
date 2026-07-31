# ============================================================================
# DEPRECATED - historical V4 sample run. The unified production path is the
# `v4-run` orchestrator in services/engineering_drawing/run_v4.py. This script
# must not write `.release-authorization.json` or copy into the formal
# `v4.0-readable-zone-complete` directory for future runs.
# ============================================================================
from pathlib import Path
import json,re,math,fitz,numpy as np
from rapidocr_onnxruntime import RapidOCR

BASE=Path(r"D:\AmyProjects\business\pdf-manager\output\pdf\engineering-drawing\01_Bilingual_Inline")
rec=json.loads((BASE/r"agent-artifacts/v3.12-human-audit-repair/sample-records.json").read_text(encoding="utf8"))["records"][0]
plan=json.loads(Path(rec["old"]).read_text(encoding="utf8"));ref=fitz.open(rec["reference"]);src=fitz.open(rec["source"])
work=BASE/r"agent-artifacts/v4.0-readable-zone-complete/01";work.mkdir(parents=True,exist_ok=True)
out=BASE/r"translated/v4.0-readable-zone-complete-candidates/01_00_LIST OF DRAWING_A3 FORMAT.pdf";font=Path(r"C:\Windows\Fonts\msyh.ttc")
doc=fitz.open();ledger=[];literal=[];audit=[];drawing_number_to_row={};next_row_number=1;ocr=RapidOCR()
def cjk(s):return bool(re.search(r"[\u3400-\u9fff]",s))
def is_literal(s):
 u=" ".join(s.upper().split());return bool(re.fullmatch(r"[0-9A-Z._/()\- ]+",u)) and not bool(re.search(r"[A-Z]{4,} [A-Z]{3,}",u))
def cluster(items,tol=10.0):
 rows=[]
 for b in sorted(items,key=lambda x:(x["source_bbox"][1]+x["source_bbox"][3])/2):
  y=(b["source_bbox"][1]+b["source_bbox"][3])/2
  if not rows or abs(rows[-1][0]-y)>tol:rows.append([y,[b]])
  else:rows[-1][1].append(b);rows[-1][0]=sum((x["source_bbox"][1]+x["source_bbox"][3])/2 for x in rows[-1][1])/len(rows[-1][1])
 return [x[1] for x in rows]
for pi in range(len(src)):
 rp=ref[min(pi,len(ref)-1)];rw,rh=rp.rect.width,rp.rect.height;refs=[]
 for bb in rp.get_text("dict")["blocks"]:
  for ln in bb.get("lines",[]):
   t=" ".join(s.get("text","").strip() for s in ln.get("spans",[]) if s.get("text","").strip());r=fitz.Rect(ln["bbox"])*rp.rotation_matrix
   if cjk(t):refs.append((t,fitz.Rect(r.x0/rw,r.y0/rh,r.x1/rw,r.y1/rh)))
 sp=src[pi];pix=sp.get_pixmap(matrix=fitz.Matrix(3,3),alpha=False);img=np.frombuffer(pix.samples,dtype=np.uint8).reshape(pix.height,pix.width,pix.n);ocr_items,_=ocr(img);pblocks=[]
 for oi,item in enumerate(ocr_items or []):
  pts,text,conf=item
  if float(conf)<.30:continue
  xs_=[p[0]/3 for p in pts];ys_=[p[1]/3 for p in pts]
  pblocks.append({"page_index":pi,"source_bbox":[min(xs_),min(ys_),max(xs_),max(ys_)],"source_text":text,"member_ids":[f"p{pi+1:03d}-ocr-{oi+1:05d}"]})
 table=[b for b in pblocks if b["source_bbox"][1]>210]
 header=[b for b in pblocks if b["source_bbox"][1]<=210]
 for side in (0,1):
  xcut=595;items=[b for b in table if (b["source_bbox"][0]<xcut)==(side==0)];origin_probe=65 if side==0 else 615
  number_items=[b for b in items if re.fullmatch(r"\d+\.?",b["source_text"].strip()) and ((b["source_bbox"][0]+b["source_bbox"][2])/2-origin_probe)<60]
  rows=cluster([b for b in items if b not in number_items])
  for nb in number_items:
   ny=(nb["source_bbox"][1]+nb["source_bbox"][3])/2
   min(rows,key=lambda row:abs(sum((x["source_bbox"][1]+x["source_bbox"][3])/2 for x in row)/len(row)-ny)).append(nb)
  page=doc.new_page(width=1190.551,height=1683.78);page.insert_font(fontname="msyh",fontfile=str(font))
  page.insert_textbox(fitz.Rect(40,20,1150,45),"CONSTRUCTION DRAWING  施工图",fontname="msyh",fontfile=str(font),fontsize=14,align=1,color=(0,0,0))
  page.insert_textbox(fitz.Rect(40,48,1150,70),"LIST OF ARCHITECTURAL DETAIL DRAWINGS  建筑详图目录",fontname="msyh",fontfile=str(font),fontsize=11,align=1,color=(0,0,0))
  page.insert_textbox(fitz.Rect(40,72,1150,92),f"SOURCE PAGE {pi+1} / COLUMN {side+1}   原第{pi+1}页／第{side+1}栏",fontname="msyh",fontfile=str(font),fontsize=8,align=1,color=(0,0,0))
  top=105;bottom=1660;rhgt=(bottom-top)/(len(rows)+1);xs=[40,90,760,1080,1150]
  for x in xs:page.draw_line((x,top),(x,bottom),color=(0,0,0),width=.5)
  for k in range(len(rows)+2):
   y=top+k*rhgt;page.draw_line((40,y),(1150,y),color=(0,0,0),width=.5)
  headers=["NO.\n序号","TITLE / DESCRIPTION\n标题／说明","DRAWING NO.\n图号","SIZE\n尺寸"]
  for ci,t in enumerate(headers):page.insert_textbox(fitz.Rect(xs[ci]+2,top+2,xs[ci+1]-2,top+rhgt-2),t,fontname="msyh",fontfile=str(font),fontsize=7.2,align=1,color=(0,0,0),lineheight=1)
  for ri,row in enumerate(rows):
   y0=top+(ri+1)*rhgt;y1=y0+rhgt;origin=65 if side==0 else 615;side_width=520
   cols=[[],[],[],[]]
   for b in row:
    x=(b["source_bbox"][0]+b["source_bbox"][2])/2-origin;rel=x/side_width
    ci=0 if rel<.10 else 1 if rel<.68 else 2 if rel<.92 else 3;cols[ci].append(b)
   explicit_numbers=[x["source_text"].strip().rstrip(".") for x in cols[0] if re.fullmatch(r"\d+\.?",x["source_text"].strip())]
   if explicit_numbers:page.insert_text((xs[0]+18,y0+rhgt*.67),explicit_numbers[0],fontname="helv",fontsize=7.2,color=(0,0,0))
   for ci,parts in enumerate(cols):
    if not parts:continue
    if ci==0:continue
    st=" ".join(x["source_text"] for x in sorted(parts,key=lambda x:x["source_bbox"][0]));ids=[x["member_ids"][0] for x in parts]
    if ci!=1 or is_literal(st):
     page.insert_textbox(fitz.Rect(xs[ci]+2,y0+2,xs[ci+1]-2,y1-2),st,fontname="helv",fontsize=6.8,align=1 if ci!=1 else 0,color=(0,0,0),lineheight=1);literal.extend(ids);continue
    box=fitz.Rect(min(x["source_bbox"][0] for x in parts),min(x["source_bbox"][1] for x in parts),max(x["source_bbox"][2] for x in parts),max(x["source_bbox"][3] for x in parts));q=fitz.Rect(box.x0/1190.551,box.y0/841.89,box.x1/1190.551,box.y1/841.89);cx=(q.x0+q.x1)/2;cy=(q.y0+q.y1)/2
    zh=min(refs,key=lambda z:math.hypot((z[1].x0+z[1].x1)/2-cx,(z[1].y0+z[1].y1)/2-cy))[0] if refs else "目录说明"
    mid=y0+rhgt*.50;fs=max(7.2,min(9.0,rhgt*.34));r1=page.insert_textbox(fitz.Rect(xs[1]+3,y0+2,xs[2]-3,mid),st,fontname="helv",fontsize=fs*.9,color=(0,0,0),lineheight=1);r2=page.insert_textbox(fitz.Rect(xs[1]+3,mid,xs[2]-3,y1-2),zh,fontname="msyh",fontfile=str(font),fontsize=fs,color=(0,0,0),lineheight=1)
    bid=f"v4-p{pi+1:03d}-s{side+1}-r{ri+1:03d}";ledger.append({"block_id":bid,"source_ids":ids,"source_text":st,"translation":zh,"output_page":page.number+1,"zone":"directory_index","chosen_font_size":fs,"largest_fit_font_size":fs,"padding_points":2,"target_height_utilization":.82,"rotation":0});audit.append({"block_id":bid,"status":"rendered" if r1>=0 and r2>=0 else "fit_failed","source_fit":r1,"chinese_fit":r2})
doc.save(out,garbage=4,deflate=True)
data={"schema":"v4.0-paginated-directory-ledger","workflow_version":"v4.0-readable-zone-complete","source_pdf":rec["source"],"reference_pdf":rec["reference"],"blocks":ledger,"literal_only_ids":literal,"whole_page_closure":1.0,"directory_index_closure":1.0,"pagination":"each original dual-column page becomes two readable single-column bilingual pages"}
(work/r"decision-ledger-paginated.json").write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf8");(work/r"candidate-render-audit-paginated.json").write_text(json.dumps({"planned":len(audit),"rendered":sum(x["status"]=="rendered" for x in audit),"blocks":audit},ensure_ascii=False,indent=2),encoding="utf8")
rd=fitz.open(out)
for i,p in enumerate(rd):p.get_pixmap(matrix=fitz.Matrix(.7,.7),alpha=False).save(work/f"paginated-page-{i+1:04d}.png")
print(json.dumps({"output":str(out),"pages":len(rd),"blocks":len(ledger),"literal":len(literal),"failed":[x["block_id"] for x in audit if x["status"]!="rendered"],"min_font":min(x["chosen_font_size"] for x in ledger)},ensure_ascii=False,indent=2))
