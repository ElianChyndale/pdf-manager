# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
import argparse,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE));import run_verified_samples as run
R=run.SAMPLE_ROOT;run.ARTIFACT_ROOT=R/"agent-artifacts/v3.11-cost-balanced-final-3";run.CANDIDATE_ROOT=R/"translated/v3.11-cost-balanced-final-3-candidates";run.RELEASE_ROOT=R/"translated/v3.11-cost-balanced-final-3";run.RECORDS_PATH=run.ARTIFACT_ROOT/"sample-records.json";run.SELECTED=(("1","1"),("2","2"),("3","3"))
if __name__=="__main__":p=argparse.ArgumentParser();p.add_argument("--phase",choices=("execute","publish"),required=True);a=p.parse_args();print(run.execute() if a.phase=="execute" else run.publish())
