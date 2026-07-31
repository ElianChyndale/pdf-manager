# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
import hashlib,json,sys
from pathlib import Path
ROOT=Path(r"D:\AmyProjects\business\pdf-manager");sys.path.insert(0,str(ROOT/"backend/scripts"))
from services.engineering_drawing.agent_system import EngineeringDrawingAgent
from services.engineering_drawing.existing_translation_registry import extract_native_existing_translations
BASE=ROOT/"output/pdf/engineering-drawing/01_Bilingual_Inline/agent-artifacts/v3.11-cost-balanced-final-3";M=ROOT.parent/"WROK-CONTENT/malasia";S=M/"A3 DETAIL DRAWING";R=M/"清真寺施工图纸 11112025 翻译/清真寺施工图纸 11112025 翻译";names=["30_REV. JULAI 2025 LALUAN BERBUMBUNG","13_REV. JULAI 2025 MENARA","28_REV. JULAI 2025 GAZEBO"]
def sha(p):h=hashlib.sha256();h.update(p.read_bytes());return h.hexdigest()
def wr(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
a=EngineeringDrawingAgent();recs=[]
for i,n in enumerate(names,1):
 s=S/(n+".pdf");r=R/(n+"_翻译.pdf");w=BASE/f"sample-{i:02d}__{n.replace(' ','_')}";w.mkdir(parents=True,exist_ok=True);m=a.build_manifest(s,reference_pdf=r);reg=extract_native_existing_translations(r);wr(w/"existing-translation-registry.json",reg);pages=[]
 for p in range(m["source_snapshot"]["page_count"]):
  d=w/f"page-{p+1:04d}";packet=a.build_page_packet(s,p,manifest=m,evidence=[x for x in reg.get("items",[]) if x.get("page_index")==p],output_dir=d,dpi=180);im=d/packet["source_image"];pages.append({"page_index":p,"packet":str((d/"page-packet.json").resolve()),"source_image":str(im.resolve()),"image_sha256":sha(im)})
 m["pages"]=pages;m["existing_translation_registry"]=str((w/"existing-translation-registry.json").resolve());wr(w/"agent-manifest.json",m);tasks=[{"id":"visual-page-0001-full","page_index":0,"full_page":True,"engine":"technical_cad_ocr","rotation":0,"language_scope":["ms","en","technical_codes"],"purpose":"Sol-Light visually confirmed low-density sheet; extract source wording only"}];wr(w/"preplan-ocr-tasks.json",{"supervisor_plan":{"ocr_tasks":tasks}});recs.append({"sample_index":i,"source_pdf":str(s.resolve()),"reference_pdf":str(r.resolve()),"slug":w.name,"artifact_dir":str(w.resolve()),"page_count":1})
wr(BASE/"sample-records.json",{"schema":"cost-balanced-final3-v311","records":recs})
