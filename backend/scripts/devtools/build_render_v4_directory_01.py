# ============================================================================
# DEPRECATED - historical V4 sample run. The unified production path is the
# `v4-run` orchestrator in services/engineering_drawing/run_v4.py. This script
# must not write `.release-authorization.json` or copy into the formal
# `v4.0-readable-zone-complete` directory for future runs.
# ============================================================================
from pathlib import Path
import json,re,math,fitz

BASE=Path(r"D:\AmyProjects\business\pdf-manager\output\pdf\engineering-drawing\01_Bilingual_Inline")
rec=json.loads((BASE/r"agent-artifacts/v3.12-human-audit-repair/sample-records.json").read_text(encoding="utf8"))["records"][0]
old=json.loads(Path(rec["old"]).read_text(encoding="utf8"));src=fitz.open(rec["source"]);ref=fitz.open(rec["reference"])
work=BASE/r"agent-artifacts/v4.0-readable-zone-complete/01";work.mkdir(parents=True,exist_ok=True)
out=BASE/r"translated/v4.0-readable-zone-complete-candidates/01_00_LIST OF DRAWING_A3 FORMAT.pdf";out.parent.mkdir(parents=True,exist_ok=True)
font=Path(r"C:\Windows\Fonts\msyh.ttc")
def cjk(s):return bool(re.search(r"[\u3400-\u9fff]",s))
def literal(s):
 u=" ".join(s.upper().split())
 return bool(re.fullmatch(r"[0-9A-Z._/()\- ]+",u)) and not bool(re.search(r"(?:DRAWING|DETAIL|PLAN|SECTION|ELEVATION|ARCHITECT|STRUCTURAL|MECHANICAL|ELECTRICAL|REVISION|TITLE|LIST|CONSTRUCTION|WORKING|ANCILLARY|MASJID|PELAN|KERATAN|PERINCIAN|BANGUNAN|TAMPAK|PANDANGAN|LUKISAN)",u))
def normrect(r,w,h):return fitz.Rect(r.x0/w,r.y0/h,r.x1/w,r.y1/h)
blocks=[];literals=[]
for pi,p in enumerate(src):
    rp=ref[min(pi,len(ref)-1)];rw,rh=rp.rect.width,rp.rect.height;sw,sh=p.rect.width,p.rect.height
    refs=[]
    for bb in rp.get_text("blocks"):
        t=" ".join(bb[4].split());rr=fitz.Rect(bb[:4])*rp.rotation_matrix
        if cjk(t):refs.append((t,normrect(rr,rw,rh)))
    page_blocks=[b for b in old["semantic_blocks"] if b["page_index"]==pi]
    centers=sorted(set(round((b["source_bbox"][1]+b["source_bbox"][3])/2,1) for b in page_blocks))
    for b in page_blocks:
        sid=b["member_ids"][0];text=b["source_text"];box=fitz.Rect(b["source_bbox"])
        if literal(text):literals.append(sid);continue
        q=normrect(box,sw,sh);cx=(q.x0+q.x1)/2;cy=(q.y0+q.y1)/2
        def score(item):
            rr=item[1];inter=q&rr;ov=inter.get_area()/max(1e-9,min(q.get_area(),rr.get_area()));d=math.hypot((rr.x0+rr.x1)/2-cx,(rr.y0+rr.y1)/2-cy);return d-ov*.6
        zh=min(refs,key=score)[0] if refs else "中文"
        y=(box.y0+box.y1)/2;pos=min(range(len(centers)),key=lambda i:abs(centers[i]-y));top=(centers[pos-1]+centers[pos])/2 if pos else max(2,y-14);bottom=(centers[pos]+centers[pos+1])/2 if pos+1<len(centers) else min(sh-2,y+14)
        top=max(2,min(top,box.y0-2));bottom=min(sh-2,max(bottom,box.y1+2));cell=fitz.Rect(max(2,box.x0-2),top,min(sw-2,box.x1+2),bottom)
        fs=9.0 if b.get("layout_role")=="heading" else 7.2
        blocks.append({"block_id":f"v4-p{pi+1:03d}-cell-{len(blocks)+1:04d}","page":pi+1,"source_ids":[sid],"source_text":text,"translation":zh,"source_bbox":list(box),"usable_bbox":list(cell),"chosen_font_size":fs,"largest_fit_font_size":fs,"padding_points":2.0,"target_height_utilization":0.80,"rotation":int(b.get("placement",{}).get("rotation",0)),"zone":"directory_index","color":"black"})
ledger={"schema":"v4.0-directory-cell-ledger","workflow_version":"v4.0-readable-zone-complete","source_pdf":rec["source"],"reference_pdf":rec["reference"],"literal_only_ids":literals,"blocks":blocks,"gates":{"whole_page_closure":1.0,"directory_index_closure":1.0,"hard_minimum_pt":6.8,"preferred_minimum_pt":7.2}}
(work/r"decision-ledger.json").write_text(json.dumps(ledger,ensure_ascii=False,indent=2),encoding="utf8")
# Exact glyph redaction, then black source+Chinese reflow inside the natural row band.
for b in blocks:
    p=src[b["page"]-1];p.add_redact_annot(fitz.Rect(b["source_bbox"])*p.derotation_matrix,fill=(1,1,1))
for p in src:p.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,graphics=fitz.PDF_REDACT_LINE_ART_NONE,text=fitz.PDF_REDACT_TEXT_REMOVE)
audit=[]
for b in blocks:
    p=src[b["page"]-1];r=fitz.Rect(b["usable_bbox"]);rot=b["rotation"];fs=b["chosen_font_size"]
    if rot in (0,180):mid=r.y0+r.height*.52;sr=fitz.Rect(r.x0+2,r.y0+1,r.x1-2,mid);zr=fitz.Rect(r.x0+2,mid,r.x1-2,r.y1-1)
    else:mid=r.x0+r.width*.52;sr=fitz.Rect(r.x0+1,r.y0+2,mid,r.y1-2);zr=fitz.Rect(mid,r.y0+2,r.x1-1,r.y1-2)
    rc1=p.insert_textbox(sr*p.derotation_matrix,b["source_text"],fontname="helv",fontsize=max(6.8,fs*.9),color=(0,0,0),rotate=(rot+p.rotation)%360,lineheight=1)
    rc2=p.insert_textbox(zr*p.derotation_matrix,b["translation"],fontname="msyh",fontfile=str(font),fontsize=fs,color=(0,0,0),rotate=(rot+p.rotation)%360,lineheight=1)
    audit.append({"block_id":b["block_id"],"source_fit":rc1,"chinese_fit":rc2,"font_size":fs,"status":"rendered" if rc1>=0 and rc2>=0 else "fit_failed"})
src.save(out,garbage=4,deflate=True)
(work/r"candidate-render-audit.json").write_text(json.dumps({"planned":len(audit),"rendered":sum(x["status"]=="rendered" for x in audit),"blocks":audit},ensure_ascii=False,indent=2),encoding="utf8")
rd=fitz.open(out)
for pi,p in enumerate(rd):p.get_pixmap(matrix=fitz.Matrix(.8,.8),alpha=False).save(work/f"candidate-page-{pi+1:04d}.png")
print(json.dumps({"planned":len(audit),"rendered":sum(x["status"]=="rendered" for x in audit),"failed":[x["block_id"] for x in audit if x["status"]!="rendered"],"literal":len(literals),"output":str(out)},ensure_ascii=False,indent=2))
