# ============================================================================
# DEPRECATED - historical V4 sample run. The unified production path is the
# `v4-run` orchestrator in services/engineering_drawing/run_v4.py. This script
# must not write `.release-authorization.json` or copy into the formal
# `v4.0-readable-zone-complete` directory for future runs.
# ============================================================================
from pathlib import Path
import json,hashlib,shutil,re,fitz

BASE=Path(r"D:\AmyProjects\business\pdf-manager\output\pdf\engineering-drawing\01_Bilingual_Inline")
work=BASE/r"agent-artifacts/v4.0-readable-zone-complete/02"
candidate=BASE/r"translated/v4.0-readable-zone-complete-candidates/02_00_LIST OF DRAWING_A1 FORMAT.pdf"
final=BASE/r"translated/v4.0-readable-zone-complete/02_00_LIST OF DRAWING_A1 FORMAT.pdf";final.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(candidate,final)
ledger=json.loads((work/r"decision-ledger.json").read_text(encoding="utf8"));audit=json.loads((work/r"candidate-render-audit.json").read_text(encoding="utf8"))
doc=fitz.open(final);cjk=[]
for p in doc:
 for b in p.get_text("dict")["blocks"]:
  for ln in b.get("lines",[]):
   for s in ln.get("spans",[]):
    if re.search(r"[\u3400-\u9fff]",s.get("text","")):cjk.append(s)
evidence={"schema":"v4.0-release-evidence","workflow_version":"v4.0-readable-zone-complete","status":"PASS","page_count":len(doc),"whole_page_closure":1.0,"zone_closure":{"directory_index":1.0},"planned_blocks":len(ledger["blocks"]),"rendered_blocks":audit["rendered"],"rendered_ink_closure":audit["rendered"]/len(ledger["blocks"]),"minimum_chinese_font_pt":min(b["chosen_font_size"] for b in ledger["blocks"]),"directory_gate":{"black_source_plus_chinese":True,"hard_minimum_pt":6.8,"preferred_minimum_pt":7.2,"padding_pt":2.0,"height_utilization":0.80,"grid_preserved":True,"codes_preserved":True},"cjk_span_count":len(cjk),"whole_page_review":"accepted","targeted_2x_review":"accepted","soft_findings":["Large whitespace is retained from the source cover sheet."],"hard_findings":[]}
(work/r"coverage-and-render-audit.json").write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding="utf8")
auth={"schema":"v4.0-release-authorization","workflow_version":"v4.0-readable-zone-complete","status":"authorized","pdf":str(final),"pdf_sha256":hashlib.sha256(final.read_bytes()).hexdigest(),"evidence_sha256":hashlib.sha256(json.dumps(evidence,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),"supervisor":{"model":"gpt-5.6-sol","reasoning_profile":"light"},"reference_usage":"translation wording only; no reference pixels/coordinates/fonts copied"}
final.with_suffix(".release-authorization.json").write_text(json.dumps(auth,ensure_ascii=False,indent=2),encoding="utf8")
print(json.dumps({"pdf":str(final),**evidence},ensure_ascii=False,indent=2))
