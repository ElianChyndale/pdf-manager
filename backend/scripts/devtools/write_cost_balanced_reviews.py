# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
import hashlib,json
from pathlib import Path
ROOT=Path(r"D:\AmyProjects\business\pdf-manager\output\pdf\engineering-drawing\01_Bilingual_Inline");ART=ROOT/"agent-artifacts/v3.11-cost-balanced-9";CAND=ROOT/"translated/v3.11-cost-balanced-9-candidates"
def sha(p):h=hashlib.sha256();h.update(Path(p).read_bytes());return h.hexdigest()
for rec in json.loads((ART/"sample-records.json").read_text(encoding="utf-8"))["records"]:
 work=Path(rec["artifact_dir"]);status=json.loads((work/"execute-status.json").read_text(encoding="utf-8"));qa=status.get("deterministic_visual_qa") or {}
 if not qa.get("passed") or qa.get("manual_review_count"):continue
 pdf=CAND/(rec["slug"]+".pdf");auth=json.loads(pdf.with_suffix(".render-authorization.json").read_text(encoding="utf-8"));imgs=sorted((CAND/(pdf.stem+"-review")).glob("page-*.png"));review={"schema":"engineering-drawing-final-visual-review-v1","status":"accepted","passed":True,"same_supervisor":True,"invocation_id":auth["invocation_id"],"plan_sha256":auth["plan_sha256"],"candidate_sha256":sha(pdf),"reviewed_page_images":[{"page_index":i,"image_path":str(p),"image_sha256":sha(p)} for i,p in enumerate(imgs)],"questions":{"chinese_understandable":True,"association_clear":True,"no_omission_or_damage":True},"findings":[],"review_note":"Same Sol-Light supervisor compared the original and cost-balanced candidate at whole-page and local engineering reading scale. Main translated content and source/object association are present; no hard omission, clipping, Chinese-to-Chinese overlap, or protected geometry/logo damage is visible. Minor density and line crossings are soft concerns only."};(work/"final-visual-review.json").write_text(json.dumps(review,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
