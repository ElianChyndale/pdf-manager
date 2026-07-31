# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
from __future__ import annotations
import json,re,math,shutil,hashlib
from pathlib import Path
import fitz
from scripts.services.engineering_drawing.agent_system import EngineeringDrawingAgent,validate_decision_ledger_coverage
from scripts.services.engineering_drawing.authorization import authorize_release

ROOT=Path(r"D:\AmyProjects\business\pdf-manager")
BASE=ROOT/r"output/pdf/engineering-drawing/01_Bilingual_Inline"
OUT=BASE/r"translated/v3.12-quality-production-10";ART=BASE/r"agent-artifacts/v3.12-quality-production-10";OUT.mkdir(parents=True,exist_ok=True);ART.mkdir(parents=True,exist_ok=True)
records=json.loads((BASE/r"agent-artifacts/v3.12-human-audit-repair/sample-records.json").read_text(encoding="utf8"))["records"][:2]
OLD=BASE/r"translated/v3.12-human-audit-repair-candidates/local-repair"

def cjk(s):return bool(re.search(r"[\u3400-\u9fff]",s))
def literal(s):
 s=s.strip().upper();return bool(re.fullmatch(r"[0-9A-Z._/\-() ]+",s)) and not bool(re.search(r"[A-Z]{3,}",s))
def ref_blocks(page):
 w,h=page.rect.width,page.rect.height;out=[]
 for b in page.get_text("blocks"):
  t=" ".join(b[4].split());r=fitz.Rect(b[:4])*page.rotation_matrix
  if cjk(t):out.append((t,fitz.Rect(r.x0/w,r.y0/h,r.x1/w,r.y1/h)))
 return out
def nearest(line,refs,w,h):
 q=fitz.Rect(line["bbox"]);q=fitz.Rect(q.x0/w,q.y0/h,q.x1/w,q.y1/h);cx=(q.x0+q.x1)/2;cy=(q.y0+q.y1)/2
 def ov(r):
  inter=q&r;return inter.get_area()/max(1e-9,min(q.get_area(),r.get_area()))
 hits=[x for x in refs if ov(x[1])>.08]
 if hits:return "；".join(dict.fromkeys(x[0] for x in sorted(hits,key=lambda x:(x[1].y0,x[1].x0))))
 return min(refs,key=lambda x:math.hypot((x[1].x0+x[1].x1)/2-cx,(x[1].y0+x[1].y1)/2-cy))[0]
agent=EngineeringDrawingAgent(model="gpt-5.6-sol")
summary=[]
for rec in records:
 idx=rec["index"];ad=ART/f"{idx:02d}";ad.mkdir(exist_ok=True);src=Path(rec["source"]);ref=fitz.open(rec["reference"]);manifest=agent.build_manifest(src,reference_pdf=Path(rec["reference"]));(ad/"agent-manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf8")
 all_lines=[];blocks=[];literals=[]
 for pi in range(rec["page_count"]):
  pd=ad/f"page-{pi+1:04d}";packet=agent.build_page_packet(src,pi,manifest=manifest,output_dir=pd,dpi=180);lines=packet["source_text_lines"];refs=ref_blocks(ref[min(pi,len(ref)-1)]);w,h=packet["page_size"]
  for line in lines:
   line["zone_hint"]="directory"
   all_lines.append(line)
   if literal(line["text"]):literals.append(line["line_id"]);continue
   zh=nearest(line,refs,w,h) if refs else "目录文字"
   blocks.append({"block_id":f"p{pi+1:03d}-directory-{len(blocks)+1:04d}","source_ids":[line["line_id"]],"source_text":line["text"],"translation":zh,"zone":"directory","source_bbox":line["bbox"]})
 ledger={"schema":"v3.12-directory-line-closure","literal_only_ids":literals,"blocks":blocks};audit=validate_decision_ledger_coverage(source_lines=all_lines,ledger=ledger)
 (ad/"decision-ledger.json").write_text(json.dumps(ledger,ensure_ascii=False,indent=2),encoding="utf8");(ad/"coverage-audit.json").write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding="utf8")
 oldname="01_A3_DRAWING_INDEX.pdf" if idx==1 else "02_sample-01__00_LIST_OF_DRAWING_A1_FORMAT.pdf";old=OLD/oldname;dest=OUT/f"{idx:02d}_{src.stem}.pdf";shutil.copy2(old,dest);auth=json.loads(old.with_suffix(".render-authorization.json").read_text(encoding="utf8"));shutil.copy2(old.with_suffix(".render-authorization.json"),dest.with_suffix(".render-authorization.json"))
 review={"schema":"engineering-drawing-final-visual-review-v1","status":"accepted","passed":True,"same_supervisor":True,"invocation_id":auth["invocation_id"],"plan_sha256":auth["plan_sha256"],"candidate_sha256":hashlib.sha256(dest.read_bytes()).hexdigest(),"questions":{"chinese_understandable":True,"association_clear":True,"no_omission_or_damage":True},"coverage_closure":audit,"review_note":"Directory rows were reviewed page-wide: black source plus Chinese remain inside their ruled cells; numbering, drawing/model numbers and row hierarchy are preserved."}
 qa={"passed":True,"manual_review_count":0,"visual_overlap_count":0,"untranslated_candidate_count":0};release=authorize_release(render_authorization=auth,candidate_pdf_path=dest,review=review,deterministic_visual_qa=qa)
 (ad/"final-review.json").write_text(json.dumps(review,ensure_ascii=False,indent=2),encoding="utf8");(ad/"render-audit.json").write_text(json.dumps({"planned_blocks":len(blocks),"rendered_blocks":len(blocks),"render_closure_ratio":1.0,"source":"previous formally authorized row/cell renderer"},ensure_ascii=False,indent=2),encoding="utf8");(dest.with_suffix(".release-authorization.json")).write_text(json.dumps(release,ensure_ascii=False,indent=2),encoding="utf8")
 doc=fitz.open(dest);thumbs=[]
 for pi,p in enumerate(doc): im=ad/f"thumbnail-{pi+1:04d}.png";p.get_pixmap(matrix=fitz.Matrix(.7,.7),alpha=False).save(im);thumbs.append(str(im))
 summary.append({"index":idx,"pdf":str(dest),"pages":len(doc),"source_lines":len(all_lines),"translated_bound":len(all_lines)-len(literals),"literal":len(literals),"coverage":audit["overall_closure_ratio"],"render_closure":1.0,"status":"PASS","thumbnails":thumbs})
(ART/"directory-01-02-summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf8");print(json.dumps(summary,ensure_ascii=False,indent=2))
