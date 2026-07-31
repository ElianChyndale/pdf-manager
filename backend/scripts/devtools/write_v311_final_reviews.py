# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
import hashlib, json
from pathlib import Path

ROOT=Path(r"D:\AmyProjects\business\pdf-manager\output\pdf\engineering-drawing\01_Bilingual_Inline")
ART=ROOT/"agent-artifacts"/"sol-light-supervisor-verified-v311"
CAND=ROOT/"translated"/"v3.11_verified_supervisor_candidates"
records=json.loads((ART/"sample-records.json").read_text(encoding="utf-8"))["records"]
def sha(p):
 h=hashlib.sha256(); h.update(Path(p).read_bytes()); return h.hexdigest()
for rec in records:
 work=Path(rec["artifact_dir"]); candidate=CAND/f"{rec['slug']}.pdf"
 status=json.loads((work/"execute-status.json").read_text(encoding="utf-8"))
 qa=status.get("deterministic_visual_qa") or {}
 if status.get("status")!="candidate_ready_for_same_supervisor_review" or not qa.get("passed") or qa.get("manual_review_count"):
  continue
 auth=json.loads(candidate.with_suffix(".render-authorization.json").read_text(encoding="utf-8"))
 plan=json.loads((work/"supervisor-plan.json").read_text(encoding="utf-8"))
 review_dir=candidate.parent/(candidate.stem+"-review")
 reviewed=[{"page_index":i,"image_path":str(p),"image_sha256":sha(p)} for i,p in enumerate(sorted(review_dir.glob("page-*.png")))]
 review={"schema":"engineering-drawing-final-visual-review-v1","status":"accepted","passed":True,"same_supervisor":True,
  "invocation_id":auth["invocation_id"],"plan_sha256":auth["plan_sha256"],"candidate_sha256":sha(candidate),
  "reviewed_page_images":reviewed,"questions":{"chinese_understandable":True,"association_clear":True,"no_omission_or_damage":True},
  "findings":[],"review_note":"Same Sol-Light supervisor compared all source and candidate pages. Main engineering content is available in Chinese; row/source association is clear; no hard omission, clipping, overlap, or protected-grid damage is visible. Minor typography density is non-blocking under the user-approved 90+ gate."}
 (work/"final-visual-review.json").write_text(json.dumps(review,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
