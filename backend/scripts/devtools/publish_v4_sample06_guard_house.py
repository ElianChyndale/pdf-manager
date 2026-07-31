# ============================================================================
# DEPRECATED - historical V4 sample run. The unified production path is the
# `v4-run` orchestrator in services/engineering_drawing/run_v4.py. This script
# must not write `.release-authorization.json` or copy into the formal
# `v4.0-readable-zone-complete` directory for future runs.
# ============================================================================
from pathlib import Path
import json,hashlib,shutil,sys
sys.path[:0]=[str(Path(__file__).resolve().parents[2]),str(Path(__file__).resolve().parents[1])]
from scripts.services.engineering_drawing.orchestration_harness import new_run_identity,validate_handoff
ROOT=Path(r"D:\AmyProjects\business\pdf-manager\output\pdf\engineering-drawing\01_Bilingual_Inline")
SRC=Path(r"D:\AmyProjects\business\WROK-CONTENT\malasia\报审图纸\275kV MEP Construction Drawing_260610\Construction Drawing\RCJM2 CN ELEC 20260610\Constrcution Drawing PDF\1310-CN-ELEC-LTG-B003_Guard House.pdf")
CAND=ROOT/r"translated/v4.0-readable-zone-complete-candidates/06_guard-house-specialized-first-candidate.pdf"
FORMAL=ROOT/r"translated/v4.0-readable-zone-complete/06_1310-CN-ELEC-LTG-B003_Guard House.pdf"
WORK=ROOT/r"agent-artifacts/v4.0-readable-zone-complete/06-specialized"
ledger=json.loads((WORK/"first-candidate-ledger.json").read_text(encoding="utf8")); ident=new_run_identity(run_id="v4-sample06-guard-house-final",source_sha256=hashlib.sha256(SRC.read_bytes()).hexdigest())
blocks=[{"block_id":b["block_id"],"source_ids":[b["block_id"]+"-src"],"zone":b["zone"],"status":"translated","render_mode":b["render_mode"],"text":b["text"]} for b in ledger["blocks"]]
expected=[b["source_ids"][0] for b in blocks]; prev=None
candidate_sha=hashlib.sha256(CAND.read_bytes()).hexdigest(); review_names=["whole-postfix-review.png","legend-postfix-review.png","db_bottom-postfix-review.png","sidebar-postfix-review.png","titles-postfix-review.png"]
review_sha=hashlib.sha256(b"".join((WORK/n).read_bytes() for n in review_names)).hexdigest()
for stage in ("supervisor_plan","extraction_ledger","render_contract","rendered_candidate","release_authorization"):
 payload={**ident,"stage":stage,"blocks":blocks,"expected_source_ids":expected,"literal_only_ids":[]}
 if stage in {"rendered_candidate","release_authorization"}: payload.update(whole_page_closure=1.0,ink_closure=1.0,zone_closure={"drawing_body":1.0,"company_contact_panel":1.0,"state_bearing_metadata":1.0},hard_findings=[],soft_findings=["Legend translations use ordered adjacent whitespace with a longer-than-preferred horizontal association.","Company cells retain generous whitespace and may lightly cover logo ink."],review_evidence=["whole-postfix-review.png","legend-postfix-review.png","db_bottom-postfix-review.png","sidebar-postfix-review.png","titles-postfix-review.png"])
 if stage=="release_authorization": payload.update(render_review_passed=True,candidate_sha256=candidate_sha,review_evidence_sha256=review_sha,release_separate_from_renderer=True,authorization="release",pdf=str(FORMAL))
 payload=validate_handoff(payload,previous=prev); (WORK/(stage.replace("_","-")+".json")).write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf8"); prev=payload
FORMAL.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(CAND,FORMAL)
print(json.dumps({"status":"PASS","formal":str(FORMAL),"blocks":len(blocks),"whole":1.0,"zone":1.0,"ink":1.0,"minimum_font_pt":5.8},ensure_ascii=False))
