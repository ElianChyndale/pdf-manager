# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import repair_cost_balanced_v311 as r
r.BASE=Path(r"D:\AmyProjects\business\pdf-manager\output\pdf\engineering-drawing\01_Bilingual_Inline\agent-artifacts\v3.11-cost-balanced-final-3")
r.main()
