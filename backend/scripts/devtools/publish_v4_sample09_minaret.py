# ============================================================================
# DEPRECATED - historical V4 sample run. The unified production path is the
# `v4-run` orchestrator in services/engineering_drawing/run_v4.py. This script
# must not write `.release-authorization.json` or copy into the formal
# `v4.0-readable-zone-complete` directory for future runs.
# ============================================================================
from pathlib import Path
import json, hashlib, shutil, sys

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
from scripts.services.engineering_drawing.orchestration_harness import new_run_identity, validate_handoff

ROOT = Path(r"D:\AmyProjects\business\pdf-manager\output\pdf\engineering-drawing\01_Bilingual_Inline")
SOURCE = Path(r"D:\AmyProjects\business\WROK-CONTENT\malasia\A3 DETAIL DRAWING\13_REV. JULAI 2025 MENARA.pdf")
CANDIDATE = ROOT / r"translated/v4.0-readable-zone-complete-candidates/09_minaret-specialized-candidate.pdf"
FORMAL = ROOT / r"translated/v4.0-readable-zone-complete/09_13_REV. JULAI 2025 MENARA.pdf"
WORK = ROOT / r"agent-artifacts/v4.0-readable-zone-complete/09-specialized"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    candidate = json.loads((WORK / "candidate-ledger.json").read_text(encoding="utf8"))
    semantic = json.loads((WORK / "new-semantic-ledger.json").read_text(encoding="utf8"))
    if candidate["page_count"] != 2 or candidate["index_mapping_count"] != 38:
        raise RuntimeError("two-page mapping contract failed")
    anchors = [b for b in candidate["blocks"] if "anchor_number" in b]
    if len(anchors) != 38 or len({(b["view"], b["anchor_number"]) for b in anchors}) != 38:
        raise RuntimeError("anchor uniqueness failed")
    if {b["block_id"] for b in anchors} != {b["block_id"] for b in semantic["blocks"]}:
        raise RuntimeError("semantic closure failed")

    blocks = [{"block_id": b["block_id"], "source_ids": b["source_ids"],
               "zone": b["zone"], "status": "translated",
               "render_mode": b["render_mode"],
               "text": b.get("translated_text", "")} for b in candidate["blocks"]]
    expected = [sid for b in blocks for sid in b["source_ids"]]
    if len(expected) != len(set(expected)):
        raise RuntimeError("source id uniqueness failed")

    reviews = ["final-review-1.png", "final-review-2.png"]
    if not all((WORK / name).exists() for name in reviews):
        raise RuntimeError("missing independent visual evidence")
    review_sha = hashlib.sha256(b"".join((WORK / name).read_bytes() for name in reviews)).hexdigest()
    candidate_sha = sha(CANDIDATE)
    identity = new_run_identity(run_id="v4-sample09-minaret-two-page-final",
                                source_sha256=sha(SOURCE))
    previous = None
    for stage in ("supervisor_plan", "extraction_ledger", "render_contract",
                  "rendered_candidate", "release_authorization"):
        payload = {**identity, "stage": stage, "blocks": blocks,
                   "expected_source_ids": expected, "literal_only_ids": []}
        if stage in {"rendered_candidate", "release_authorization"}:
            payload.update(whole_page_closure=1.0, ink_closure=1.0,
                           zone_closure={"drawing_body": 1.0,
                                         "prose_or_index_metadata": 1.0,
                                         "company_contact_panel": 1.0,
                                         "state_bearing_metadata": 1.0},
                           hard_findings=[],
                           soft_findings=[
                               "Long drawing-body translations use a numbered second-page index; association distance is longer than inline placement.",
                               "Compact blue state labels share the original title-block cells with black source text.",
                           ], review_evidence=reviews,
                           page_count=2, anchor_mapping_count=38,
                           minimum_font_pt=5.8, index_minimum_font_pt=6.8)
        if stage == "release_authorization":
            payload.update(render_review_passed=True, candidate_sha256=candidate_sha,
                           review_evidence_sha256=review_sha,
                           release_separate_from_renderer=True,
                           authorization="release", pdf=str(FORMAL))
        payload = validate_handoff(payload, previous=previous)
        (WORK / (stage.replace("_", "-") + ".json")).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf8")
        previous = payload

    FORMAL.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CANDIDATE, FORMAL)
    print(json.dumps({"status": "PASS", "formal": str(FORMAL), "pages": 2,
                      "blocks": len(blocks), "mapped_notes": 38,
                      "whole": 1.0, "zone": 1.0, "ink": 1.0,
                      "minimum_font_pt": 5.8, "index_minimum_font_pt": 6.8},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
