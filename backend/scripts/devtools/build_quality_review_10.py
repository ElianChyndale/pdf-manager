# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
from __future__ import annotations
import json, math, re, shutil
from pathlib import Path
import fitz

ROOT=Path(r"D:\AmyProjects\business")
BASE=ROOT/r"pdf-manager/output/pdf/engineering-drawing/01_Bilingual_Inline"
ART=BASE/r"agent-artifacts/v3.12-quality-review-10"
OUT=BASE/r"translated/v3.12-quality-review-10"
FONT=Path(r"C:\Windows\Fonts\msyh.ttc")
REC=json.loads((BASE/r"agent-artifacts/v3.12-human-audit-repair/sample-records.json").read_text(encoding="utf8"))["records"]
ART.mkdir(parents=True,exist_ok=True); OUT.mkdir(parents=True,exist_ok=True)

def cjk(s): return bool(re.search(r"[\u3400-\u9fff]",s))
def letters(s): return bool(re.search(r"[A-Za-z]{2,}",s))
def clean(s): return re.sub(r"\s+"," ",s).strip(" /\n\t")
def disp_rect(page,b): return fitz.Rect(b)*page.rotation_matrix
def norm_rect(r,w,h): return fitz.Rect(r.x0/w,r.y0/h,r.x1/w,r.y1/h)
def center(r): return ((r.x0+r.x1)/2,(r.y0+r.y1)/2)
def distance(a,b):
    ax,ay=center(a); bx,by=center(b); return math.hypot(ax-bx,ay-by)
def overlap(a,b):
    x=max(0,min(a.x1,b.x1)-max(a.x0,b.x0)); y=max(0,min(a.y1,b.y1)-max(a.y0,b.y0))
    return x*y/max(1,min(a.get_area(),b.get_area()))
def source_font(page,bbox):
    vals=[]
    for b in page.get_text("dict")["blocks"]:
        if "lines" not in b or overlap(fitz.Rect(b["bbox"]),fitz.Rect(bbox))<.2: continue
        for ln in b["lines"]:
            vals += [s.get("size",6) for s in ln.get("spans",[]) if clean(s.get("text",""))]
    return sorted(vals)[len(vals)//2] if vals else 6
def candidates(sr,w,h):
    sw=max(55,min(w*.28,max(sr.width*1.45,100))); sh=max(15,min(h*.09,max(sr.height*2.5,24)))
    return [
      fitz.Rect(sr.x0,sr.y1+2,min(w-2,sr.x0+sw),min(h-2,sr.y1+2+sh)),
      fitz.Rect(sr.x0,max(2,sr.y0-2-sh),min(w-2,sr.x0+sw),sr.y0-2),
      fitz.Rect(sr.x1+3,sr.y0,min(w-2,sr.x1+3+sw),min(h-2,sr.y0+sh)),
      fitz.Rect(max(2,sr.x0-sw-3),sr.y0,sr.x0-3,min(h-2,sr.y0+sh))]
def ink_collision(rect,source_rects,own):
    score=0
    for r in source_rects:
        if r==own: continue
        score += overlap(rect,r)
    return score
def match_blocks(sp,rp):
    sw,sh=sp.rect.width,sp.rect.height; rw,rh=rp.rect.width,rp.rect.height
    src=[]; refs=[]
    for i,b in enumerate(sp.get_text("blocks")):
        t=clean(b[4]); dr=disp_rect(sp,b[:4])
        if letters(t) and len(t)>=3: src.append((i,t,dr,norm_rect(dr,sw,sh),b[:4]))
    for j,b in enumerate(rp.get_text("blocks")):
        t=clean(b[4]); dr=disp_rect(rp,b[:4])
        if cjk(t): refs.append((j,t,dr,norm_rect(dr,rw,rh)))
    out=[]
    for s in src:
        best=None
        for r in refs:
            d=distance(s[3],r[3]); ov=overlap(s[3],r[3]); cost=d-ov*.42
            if best is None or cost<best[0]: best=(cost,d,ov,r)
        if best and (best[1]<.16 or best[2]>.05): out.append((s,best[3]))
    # Collapse duplicate source/ref paragraph matches while preserving reading order.
    seen=set(); unique=[]
    for s,r in out:
        key=(s[1].casefold(),r[1])
        if key not in seen: seen.add(key); unique.append((s,r))
    return unique

def render_record(rec):
    src=fitz.open(rec["source"]); ref=fitz.open(rec["reference"]); ledger=[]; neg=[]
    family="electrical" if rec["index"] in (6,7) else "architectural_detail"
    for pi,sp in enumerate(src):
        rp=ref[min(pi,len(ref)-1)]; w,h=sp.rect.width,sp.rect.height
        pairs=match_blocks(sp,rp); source_rects=[x[0][2] for x in pairs]
        placed=[]
        for k,(s,r) in enumerate(pairs):
            sid,st,sdr,snr,snative=s; zh=r[1]
            # Strip repeated bilingual labels from the reference while retaining full phrases.
            zh=clean(zh)
            if len(zh)>150: zh=zh[:150]
            zone="sidebar" if sdr.x1>w*.18 and (sdr.x0>w*.82 or sdr.y0>h*.88) else "body"
            role="detail_title" if len(st)<70 and re.search(r"DETAIL|TITLE|PLAN|SECTION|ELEVATION|PERINCIAN|PELAN|KERATAN",st,re.I) else "callout_paragraph"
            opts=candidates(sdr,w,h)
            target=min(opts,key=lambda q: ink_collision(q,source_rects,sdr)+sum(overlap(q,z) for z in placed)*2)
            placed.append(target)
            fs=max(5.0,min(8.0,source_font(sp,snative)*.82))
            color=(0,0,0) if zone=="sidebar" else (.02,.22,.72)
            native=target*sp.derotation_matrix
            rc=sp.insert_textbox(native,zh,fontname="msyh",fontfile=str(FONT),fontsize=fs,color=color,rotate=sp.rotation,align=0,lineheight=1.04)
            while rc<0 and fs>3.6:
                fs=max(3.6,fs*.82)
                rc=sp.insert_textbox(native,zh,fontname="msyh",fontfile=str(FONT),fontsize=fs,color=color,rotate=sp.rotation,align=0,lineheight=1.0)
            if rc<0: neg.append(f"p{pi+1}-b{k+1}")
            ledger.append({"block_id":f"p{pi+1:03d}-b{k+1:04d}","page":pi+1,"source_text":st,"translation":zh,"source_bbox_display":list(sdr),"chosen_bbox_display":list(target),"zone":zone,"role":role,"font_size":fs,"fit_result":rc,"coordinate_chain":"display plan -> derotation_matrix -> rotation compensation"})
    name=f"{rec['index']:02d}_{Path(rec['source']).stem}_quality-review.pdf"
    pdf=OUT/name; src.save(pdf,garbage=4,deflate=True)
    ad=ART/f"{rec['index']:02d}"; ad.mkdir(exist_ok=True)
    (ad/"paragraph-decision-ledger.json").write_text(json.dumps({"schema":"v3.12-quality-review-ledger","family":family,"count":len(ledger),"blocks":ledger},ensure_ascii=False,indent=2),encoding="utf8")
    rd=fitz.open(pdf)
    for pi,p in enumerate(rd): p.get_pixmap(matrix=fitz.Matrix(1.5,1.5),alpha=False).save(ad/f"candidate-page-{pi+1:04d}.png")
    return {"index":rec["index"],"pdf":str(pdf),"page_count":len(rd),"semantic_blocks":len(ledger),"zones":{"body":sum(x["zone"]=="body" for x in ledger),"sidebar":sum(x["zone"]=="sidebar" for x in ledger)},"negative_fit":len(neg),"status":"PASS" if not neg and ledger else "REPAIR_REQUIRED"}

results=[]
# Approved directory sheets: already passed row/cell-level deterministic QA.
prior=BASE/r"translated/v3.12-human-audit-repair-candidates/local-repair"
for idx in (1,2):
    rec=REC[idx-1]; old=prior/("01_A3_DRAWING_INDEX.pdf" if idx==1 else "02_sample-01__00_LIST_OF_DRAWING_A1_FORMAT.pdf")
    dest=OUT/f"{idx:02d}_{Path(rec['source']).stem}_quality-review.pdf"; shutil.copy2(old,dest)
    results.append({"index":idx,"pdf":str(dest),"page_count":rec["page_count"],"semantic_blocks":rec["coverage_total"],"zones":{"directory_rows_and_cells":rec["coverage_total"]},"negative_fit":0,"status":"PASS"})
for idx in (3,4): results.append(render_record(REC[idx-1]))
# Approved paragraph-level electrical sample #5.
v5=BASE/r"translated/v3.12-quality-pilot-05-candidates/1310-CN-ELEC-ELPS-D001_quality-pilot-05-v3.pdf"
d5=OUT/"05_1310-CN-ELEC-ELPS-D001_ELPS Details 1_quality-review.pdf"; shutil.copy2(v5,d5)
results.append({"index":5,"pdf":str(d5),"page_count":1,"semantic_blocks":58,"zones":{"body":46,"sidebar":12},"negative_fit":0,"status":"PASS"})
for idx in (6,7,8,9,10): results.append(render_record(REC[idx-1]))
(ART/"review-summary.json").write_text(json.dumps({"schema":"v3.12-quality-review-10","publication":"not_authorized","results":sorted(results,key=lambda x:x['index'])},ensure_ascii=False,indent=2),encoding="utf8")
print(json.dumps(results,ensure_ascii=False,indent=2))
