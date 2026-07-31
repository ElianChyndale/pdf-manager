# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
import hashlib,json,sys
from pathlib import Path
ROOT=Path(r"D:\AmyProjects\business\pdf-manager"); sys.path.insert(0,str(ROOT/"backend"/"scripts"))
from services.engineering_drawing.agent_system import EngineeringDrawingAgent
from services.engineering_drawing.existing_translation_registry import extract_native_existing_translations
BASE=ROOT/"output/pdf/engineering-drawing/01_Bilingual_Inline/agent-artifacts/v3.11-cost-balanced-9"
M=ROOT.parent/"WROK-CONTENT/malasia"
items=[
(M/"03_CONSTRUCTION DWG_MASJID_11 NOV 2025/A1 WORKING DRAWING/00_LIST OF DRAWING_A1 FORMAT.pdf",M/"清真寺施工图纸 11112025 翻译/清真寺施工图纸 11112025 翻译/00_LIST OF DRAWING_A1 FORMAT_翻译.pdf"),
(M/"A3 DETAIL DRAWING/23_REV. JULAI 2025 PERINCIAN TIANG R.C.pdf",M/"清真寺施工图纸 11112025 翻译/清真寺施工图纸 11112025 翻译/23_REV. JULAI 2025 PERINCIAN TIANG R.C_翻译.pdf"),
(M/"A3 DETAIL DRAWING/08_REV. JULAI 2025 PERINCIAN TIANG BENDERA.pdf",M/"清真寺施工图纸 11112025 翻译/清真寺施工图纸 11112025 翻译/08_REV. JULAI 2025 PERINCIAN TIANG BENDERA_翻译.pdf"),
]
P=M/"报审图纸/275kV MEP Construction Drawing_260610/Construction Drawing/RCJM2 CN ELEC 20260610/Constrcution Drawing PDF"; T=M/"Translated Drawing 图纸翻译/Translated Drawing 图纸翻译"
for n in ["1310-CN-ELEC-ELPS-D001_ELPS Details 1","1310-CN-ELEC-LTG-B003_Guard House","1310-CN-ELEC-ELPS-D002_ELPS Details 2","1310-CN-ELEC-PA-C001_PA Schematic","1310-CN-ELEC-PA-B002_1st PA Layout","1310-CN-ELEC-ELPS-B005_Roof Earth System"]: items.append((P/(n+".pdf"),T/(n+"_Translated.pdf")))
def sha(p): h=hashlib.sha256();h.update(p.read_bytes());return h.hexdigest()
def write(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
def main():
 a=EngineeringDrawingAgent(); recs=[]; BASE.mkdir(parents=True,exist_ok=True)
 for i,(s,r) in enumerate(items,1):
  work=BASE/f"sample-{i:02d}__{s.stem.replace(' ','_')}"; work.mkdir(parents=True,exist_ok=True); man=a.build_manifest(s,reference_pdf=r); reg=extract_native_existing_translations(r); write(work/"existing-translation-registry.json",reg); pages=[]
  for p in range(man["source_snapshot"]["page_count"]):
   d=work/f"page-{p+1:04d}"; packet=a.build_page_packet(s,p,manifest=man,evidence=[x for x in reg.get("items",[]) if x.get("page_index")==p],output_dir=d,dpi=180); img=d/packet["source_image"];pages.append({"page_index":p,"packet":str((d/"page-packet.json").resolve()),"source_image":str(img.resolve()),"image_sha256":sha(img)})
  man["pages"]=pages;man["existing_translation_registry"]=str((work/"existing-translation-registry.json").resolve());write(work/"agent-manifest.json",man)
  tasks=[{"id":f"visual-page-{p+1:04d}-full","page_index":p,"full_page":True,"engine":"technical_cad_ocr","rotation":0,"language_scope":["ms","en","technical_codes"],"purpose":"Sol-Light visually confirmed page: extract visible source wording only"} for p in range(man["source_snapshot"]["page_count"])]
  write(work/"preplan-ocr-tasks.json",{"supervisor_plan":{"ocr_tasks":tasks}}); recs.append({"sample_index":i,"source_pdf":str(s.resolve()),"reference_pdf":str(r.resolve()),"slug":work.name,"artifact_dir":str(work.resolve()),"page_count":man["source_snapshot"]["page_count"]})
 write(BASE/"sample-records.json",{"schema":"cost-balanced-v311","records":recs})
if __name__=="__main__":main()
