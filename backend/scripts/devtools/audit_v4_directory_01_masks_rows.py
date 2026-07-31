# ============================================================================
# DEPRECATED - historical V4 sample run. The unified production path is the
# `v4-run` orchestrator in services/engineering_drawing/run_v4.py. This script
# must not write `.release-authorization.json` or copy into the formal
# `v4.0-readable-zone-complete` directory for future runs.
# ============================================================================
from pathlib import Path
import json,re,fitz,numpy as np
from rapidocr_onnxruntime import RapidOCR
from scripts.services.engineering_drawing.workflow_policy import validate_directory_mask_audit
BASE=Path(r"D:\AmyProjects\business\pdf-manager\output\pdf\engineering-drawing\01_Bilingual_Inline");rec=json.loads((BASE/r"agent-artifacts/v3.12-human-audit-repair/sample-records.json").read_text(encoding="utf8"))["records"][0];source=fitz.open(rec["source"]);rendered=fitz.open(BASE/r"translated/v4.0-readable-zone-complete-candidates/01_00_LIST OF DRAWING_A3 FORMAT.pdf");ocr=RapidOCR();pages=[]
for pi,p in enumerate(source):
 pix=p.get_pixmap(matrix=fitz.Matrix(3,3),alpha=False);img=np.frombuffer(pix.samples,dtype=np.uint8).reshape(pix.height,pix.width,pix.n);items,_=ocr(img)
 for side,(xa,xb) in enumerate(((65,110),(615,665))):
  nums=[]
  for pts,text,conf in items or []:
   cx=sum(q[0] for q in pts)/12;cy=sum(q[1] for q in pts)/12
   if xa<=cx<=xb and cy>210 and re.fullmatch(r"\d+\.?",text.strip()):nums.append(text.strip().rstrip("."))
  op=rendered[pi*2+side];out_nums=[w[4].rstrip(".") for w in op.get_text("words",clip=fitz.Rect(40,105,90,1660)) if re.fullmatch(r"\d+\.?",w[4])]
  pages.append({"source_page":pi+1,"source_column":side+1,"output_page":pi*2+side+1,"source_row_numbers":nums,"rendered_row_numbers":out_nums,"all_source_numbers_visible":set(nums).issubset(set(out_nums))})
print(json.dumps([x for x in pages if not x["all_source_numbers_visible"]],ensure_ascii=False,indent=2))
result=validate_directory_mask_audit({"masks":[],"protected_rects":[[40,105,90,1660],[760,105,1080,1660],[1080,105,1150,1660]],"table_rule_rects":[],"minimum_clearance_pt":1.5,"pagewise_row_numbers_match_source":all(x["all_source_numbers_visible"] for x in pages)})
report={"schema":"v4.0-mask-vs-protected-columns-audit","mask_count":0,"protected_columns":["row_number","drawing_number","size"],"rebuild_mode":"no source mask or redaction is used; source inventory is reconstructed into a new protected grid",**result,"pages":pages}
work=BASE/r"agent-artifacts/v4.0-readable-zone-complete/01";(work/r"mask-vs-protected-columns.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf8");print(json.dumps(report,ensure_ascii=False,indent=2))
