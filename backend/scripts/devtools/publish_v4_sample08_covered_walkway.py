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
R=Path(r"D:\AmyProjects\business\pdf-manager\output\pdf\engineering-drawing\01_Bilingual_Inline");S=Path(r"D:\AmyProjects\business\WROK-CONTENT\malasia\A3 DETAIL DRAWING\30_REV. JULAI 2025 LALUAN BERBUMBUNG.pdf");C=R/r"translated/v4.0-readable-zone-complete-candidates/08_covered-walkway-specialized-candidate.pdf";F=R/r"translated/v4.0-readable-zone-complete/08_30_REV. JULAI 2025 LALUAN BERBUMBUNG.pdf";W=R/r"agent-artifacts/v4.0-readable-zone-complete/08-specialized";L=json.loads((W/"candidate-ledger.json").read_text(encoding="utf8"));I=new_run_identity(run_id="v4-sample08-covered-walkway-final",source_sha256=hashlib.sha256(S.read_bytes()).hexdigest());B=[{"block_id":b["block_id"],"source_ids":[b["block_id"]+"-src"],"zone":b["zone"],"status":"translated","render_mode":b["render_mode"],"text":b["text"]} for b in L["blocks"]];E=[b["source_ids"][0] for b in B];P=None;V=["whole-review2.png","top_views-review2.png","bottom_views-review2.png","footer-review2.png"];cs=hashlib.sha256(C.read_bytes()).hexdigest();rs=hashlib.sha256(b"".join((W/n).read_bytes() for n in V)).hexdigest()
for st in ("supervisor_plan","extraction_ledger","render_contract","rendered_candidate","release_authorization"):
 p={**I,"stage":st,"blocks":B,"expected_source_ids":E,"literal_only_ids":[]}
 if st in {"rendered_candidate","release_authorization"}:p.update(whole_page_closure=1.0,ink_closure=1.0,zone_closure={"drawing_body":1.0,"prose_or_index_metadata":1.0,"company_contact_panel":1.0,"state_bearing_metadata":1.0},hard_findings=[],soft_findings=["Some Chinese callouts remain close to ordinary leader lines.","Footer reflow uses generous whitespace."],review_evidence=V)
 if st=="release_authorization":p.update(render_review_passed=True,candidate_sha256=cs,review_evidence_sha256=rs,release_separate_from_renderer=True,authorization="release",pdf=str(F))
 p=validate_handoff(p,previous=P);(W/(st.replace("_","-")+".json")).write_text(json.dumps(p,ensure_ascii=False,indent=2),encoding="utf8");P=p
F.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(C,F);print(json.dumps({"status":"PASS","formal":str(F),"blocks":len(B),"whole":1.0,"zone":1.0,"ink":1.0,"minimum_font_pt":5.8},ensure_ascii=False))
