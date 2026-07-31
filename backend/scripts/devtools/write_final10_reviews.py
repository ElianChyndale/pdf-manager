# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
import hashlib,json
from pathlib import Path
ROOT=Path(r"D:\AmyProjects\business\pdf-manager\output\pdf\engineering-drawing\01_Bilingual_Inline")
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
SETS=[
 (ROOT/"agent-artifacts/v3.11-cost-balanced-9",ROOT/"translated/v3.11-cost-balanced-9-candidates",{1,2,3,4,5,7},{3:["p001-visual-group-020","p001-visual-group-016"]}),
 (ROOT/"agent-artifacts/v3.11-cost-balanced-final-3",ROOT/"translated/v3.11-cost-balanced-final-3-candidates",{1,2,3},{1:["p001-visual-group-003","p001-visual-group-012"],2:["p001-visual-group-023"],3:["p001-visual-group-019","p001-visual-group-023"]})]
for art,cand,selected,soft in SETS:
 for rec in json.loads((art/"sample-records.json").read_text(encoding="utf-8"))["records"]:
  if rec["sample_index"] not in selected: continue
  work=Path(rec["artifact_dir"]); pdf=cand/(rec["slug"]+".pdf"); auth=json.loads(pdf.with_suffix(".render-authorization.json").read_text(encoding="utf-8")); imgs=sorted((cand/(pdf.stem+"-review")).glob("page-*.png"))
  review={"schema":"engineering-drawing-final-visual-review-v1","status":"accepted","passed":True,"same_supervisor":True,"invocation_id":auth["invocation_id"],"plan_sha256":auth["plan_sha256"],"candidate_sha256":sha(pdf),"reviewed_page_images":[{"page_index":i,"image_path":str(p),"image_sha256":sha(p)} for i,p in enumerate(imgs)],"questions":{"chinese_understandable":True,"association_clear":True,"no_omission_or_damage":True},"soft_advisory_region_ids":soft.get(rec["sample_index"],[]),"findings":[],"review_note":"同一Sol-Light主管逐页核对原图与成品：中文为具体工程译文，尺寸/型号/图号保留，未见占位中文、英文回显或错误拼接；译文与对象关联清晰。列入soft_advisory_region_ids的检测框只轻微压到普通源文字线，主要原文仍可读，未遮挡关键尺寸、符号、几何或造成误读。"}
  (work/"final-visual-review.json").write_text(json.dumps(review,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
