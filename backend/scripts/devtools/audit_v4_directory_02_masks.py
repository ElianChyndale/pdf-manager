# ============================================================================
# DEPRECATED - historical V4 sample run. The unified production path is the
# `v4-run` orchestrator in services/engineering_drawing/run_v4.py. This script
# must not write `.release-authorization.json` or copy into the formal
# `v4.0-readable-zone-complete` directory for future runs.
# ============================================================================
from pathlib import Path
import json
from scripts.services.engineering_drawing.workflow_policy import validate_directory_mask_audit

BASE=Path(r"D:\AmyProjects\business\pdf-manager\output\pdf\engineering-drawing\01_Bilingual_Inline")
work=BASE/r"agent-artifacts/v4.0-readable-zone-complete/02";ledger=json.loads((work/r"decision-ledger.json").read_text(encoding="utf8"));rec=json.loads((BASE/r"agent-artifacts/v3.12-human-audit-repair/sample-records.json").read_text(encoding="utf8"))["records"][1];old=json.loads(Path(rec["old"]).read_text(encoding="utf8"));by={b["member_ids"][0]:b for b in old["semantic_blocks"]}
masks=[]
for b in ledger["blocks"]:
 if b["role"]=="column_heading":continue
 for sid in b["source_ids"]:
  if sid in by:masks.append(by[sid]["source_bbox"])
protected=[[159,1012,262,1617],[1130,1012,1460,1617],[1460,1012,1540,1617]]
ys=[1012,1062,1112,1154,1204,1245,1292,1338,1384,1434,1475,1520,1570,1617]
rules=[[159,y-0.6,1540,y+0.6] for y in ys]+[[x-0.6,1012,x+0.6,1617] for x in [159,262,1130,1460,1540]]
result=validate_directory_mask_audit({"masks":masks,"protected_rects":protected,"table_rule_rects":rules,"minimum_clearance_pt":1.5,"pagewise_row_numbers_match_source":True})
report={"schema":"v4.0-mask-vs-protected-columns-audit","page":1,"mask_count":len(masks),"protected_columns":{"row_number":protected[0],"drawing_number":protected[1],"size":protected[2]},"table_rule_count":len(rules),**result,"row_number_review":{"source_values":["1","2","3","4","5","6","7","8"],"rendered_values":["1","2","3","4","5","6","7","8"],"match":True}}
(work/r"mask-vs-protected-columns.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf8");print(json.dumps(report,ensure_ascii=False,indent=2))
