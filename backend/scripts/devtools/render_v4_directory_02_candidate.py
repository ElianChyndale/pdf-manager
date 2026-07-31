# ============================================================================
# DEPRECATED - historical V4 sample run. The unified production path is the
# `v4-run` orchestrator in services/engineering_drawing/run_v4.py. This script
# must not write `.release-authorization.json` or copy into the formal
# `v4.0-readable-zone-complete` directory for future runs.
# ============================================================================
from pathlib import Path
import json, fitz

BASE=Path(r"D:\AmyProjects\business\pdf-manager\output\pdf\engineering-drawing\01_Bilingual_Inline")
work=BASE/r"agent-artifacts/v4.0-readable-zone-complete/02"
ledger=json.loads((work/r"decision-ledger.json").read_text(encoding="utf8"))
out=BASE/r"translated/v4.0-readable-zone-complete-candidates/02_00_LIST OF DRAWING_A1 FORMAT.pdf";out.parent.mkdir(parents=True,exist_ok=True)
font=Path(r"C:\Windows\Fonts\msyh.ttc");doc=fitz.open(ledger["source_pdf"]);page=doc[0]
old=json.loads(Path(json.loads((BASE/r"agent-artifacts/v3.12-human-audit-repair/sample-records.json").read_text(encoding="utf8"))["records"][1]["old"]).read_text(encoding="utf8"));old_by={b["member_ids"][0]:b for b in old["semantic_blocks"]}
special={"v4-p001-cell-002":[159,714,1511,786],"v4-p001-cell-003":[400,790,1280,920],"v4-p001-cell-004":[160,925,1510,1012]}
aud=[]
# Clear only verified natural-language glyph envelopes. Grid rules and literal
# columns are outside these masks and remain untouched.
for b in ledger["blocks"]:
    if b["role"]=="column_heading":continue
    for sid in b["source_ids"]:
        if sid not in old_by:continue
        rr=fitz.Rect(old_by[sid]["source_bbox"])*page.derotation_matrix
        page.add_redact_annot(rr,fill=(1,1,1))
for rr in page.search_for("LIST OF ARCHITECTURAL"):
    page.add_redact_annot(rr,fill=(1,1,1))
# Outlined heading glyphs are not searchable native text. This tight visual
# union contains only the two heading lines and no table rule or graphic.
page.add_redact_annot(fitz.Rect(395,785,1285,925)*page.derotation_matrix,fill=(1,1,1))
page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,graphics=fitz.PDF_REDACT_LINE_ART_NONE,text=fitz.PDF_REDACT_TEXT_REMOVE)
for b in ledger["blocks"]:
    r=fitz.Rect(special.get(b["block_id"],b["usable_bbox"]));rot=int(b["rotation"])
    r=fitz.Rect(r.x0+2,r.y0+2,r.x1-2,r.y1-2);fs=float(b["chosen_font_size"])
    if rot==0:
        mid=r.y0+r.height*.52;sr=fitz.Rect(r.x0,r.y0,r.x1,mid);zr=fitz.Rect(r.x0,mid,r.x1,r.y1)
    else:
        mid=r.x0+r.width*.52;sr=fitz.Rect(r.x0,r.y0,mid,r.y1);zr=fitz.Rect(mid,r.y0,r.x1,r.y1)
    align=1 if b["role"] in {"heading","table_heading","project_heading"} else 0
    rc1=0 if b["role"]=="column_heading" else page.insert_textbox(sr*page.derotation_matrix,b["source_text"],fontname="helv",fontsize=max(6.8,fs*.9),color=(0,0,0),rotate=(rot+page.rotation)%360,align=align,lineheight=1.0)
    rc2=page.insert_textbox(zr*page.derotation_matrix,b["translation"],fontname="msyh",fontfile=str(font),fontsize=fs,color=(0,0,0),rotate=(rot+page.rotation)%360,align=align,lineheight=1.0)
    aud.append({"block_id":b["block_id"],"bbox":list(r),"font_size":fs,"source_fit":rc1,"chinese_fit":rc2,"status":"rendered" if rc1>=0 and rc2>=0 else "fit_failed"})
doc.save(out,garbage=4,deflate=True)
(work/r"candidate-render-audit.json").write_text(json.dumps({"planned":len(aud),"rendered":sum(x["status"]=="rendered" for x in aud),"blocks":aud},ensure_ascii=False,indent=2),encoding="utf8")
rd=fitz.open(out);rd[0].get_pixmap(matrix=fitz.Matrix(.7,.7),alpha=False).save(work/r"candidate-page-0001.png")
print(json.dumps({"output":str(out),"rendered":sum(x["status"]=="rendered" for x in aud),"planned":len(aud),"failed":[x["block_id"] for x in aud if x["status"]!="rendered"]},ensure_ascii=False,indent=2))
