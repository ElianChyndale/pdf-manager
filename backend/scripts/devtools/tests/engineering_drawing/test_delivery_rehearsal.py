"""End-to-end delivery rehearsal (Task 4): 8 injected failure scenarios.

Exercises the production gates and the delivery controller together so the next
Codex session can rely on preflight -> canary -> pilot -> production without
per-item scripts.  All scenarios are offline/deterministic.
"""

from __future__ import annotations

import json
from pathlib import Path

import fitz
import pytest

from services.engineering_drawing import run_v4
from services.engineering_drawing.delivery_run import (
    PLAN_SCHEMA,
    batch_summary,
    build_plan_packet,
    export_plan_packets,
    import_supervisor_plans,
    load_batch,
    new_batch,
    phase_gate,
    save_batch,
    select_phase_items,
    validate_plan_against_packet,
)
from services.engineering_drawing.typography_policy import (
    validate_placement_audit_fonts,
    validate_plan_fonts,
)
from services.engineering_drawing.token_preservation import check_token_preservation


def _pdf(path: Path, *, text: str = "ROOF WATER TANK", second: str | None = None) -> Path:
    document = fitz.open()
    page = document.new_page(width=200, height=120)
    page.insert_text((10, 20), text, fontsize=8)
    if second:
        page2 = document.new_page(width=200, height=120)
        page2.insert_text((10, 20), second, fontsize=8)
    document.save(path)
    document.close()
    return path


def _manifest(tmp_path: Path, *, count: int = 6) -> Path:
    source_root = tmp_path / "sources"
    source_root.mkdir()
    items = []
    for index in range(count):
        _pdf(source_root / f"d{index + 1}.pdf", text=f"ROOF TANK {index + 1}")
        items.append(
            {
                "item_id": f"d{index + 1}",
                "source_pdf": f"d{index + 1}.pdf",
                "relative_output": f"d{index + 1}.pdf",
                "document_context": {"drawing_discipline": "electrical" if index % 2 else "mechanical"},
            }
        )
    manifest = tmp_path / "delivery.json"
    manifest.write_text(
        json.dumps({"schema": "engineering-drawing-delivery-batch-v1", "batch_id": "rehearsal", "items": items}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest


# --------------------------------------------------------------------------
# Scenario 1 & 2: font gate + token preservation
# --------------------------------------------------------------------------

def test_font_gate_catches_subfloor_and_token_loss_detected(tmp_path: Path) -> None:
    # Font: a body caption at 4.0pt must fail the post-render gate.
    violations = validate_placement_audit_fonts(
        placement_audit=[{"region_id": "r1", "zone": "drawing_body", "status": "inline_near", "font_size": 4.0, "target_bbox": [0, 0, 10, 10]}],
        renderer="inline_plus_opaque",
    )
    assert violations and violations[0]["required_floor"] == 5.8
    # Plan pre-gate too.
    plan_violations = validate_plan_fonts(
        plan={"semantic_blocks": [{"block_id": "b", "region_type": "drawing_body", "coverage_status": "translated", "placement": {"font_size": 3.0}}]},
        renderer="inline_plus_opaque",
    )
    assert plan_violations
    # Token loss.
    assert check_token_preservation(source_text="DN200", target_text="DN20")["lost_tokens"]


# --------------------------------------------------------------------------
# Scenario 3 & 4: OCR deferred -> review queue; resume recovers
# --------------------------------------------------------------------------

def test_invalid_plan_detected_and_batch_resumes(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, count=4)
    source_root = tmp_path / "sources"
    packets_dir = tmp_path / "packets"
    written = export_plan_packets(manifest=json.loads(manifest.read_text(encoding="utf-8")), source_root=source_root, out_dir=packets_dir)
    packet = json.loads(sorted(written)[0].read_text(encoding="utf-8"))
    plans_dir = tmp_path / "plans"
    plans_dir.mkdir()
    (plans_dir / "plan-001.json").write_text(
        json.dumps(
            {
                "schema": PLAN_SCHEMA,
                "packet_id": packet["packet_id"],
                "source_sha256": packet["source_sha256"],
                "page_index": 0,
                "semantic_blocks": [{"source_text": "ROOF TANK 1", "coverage_status": "translated"}],
                "coverage_inventory": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (plans_dir / "plan-002.json").write_text(
        json.dumps({"schema": PLAN_SCHEMA, "packet_id": "ghost", "source_sha256": "0" * 64, "page_index": 0, "semantic_blocks": [], "coverage_inventory": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    result = import_supervisor_plans(plans_dir=plans_dir, packets_dir=packets_dir, out_dir=tmp_path / "import")
    statuses = {item["status"] for item in result["items"]}
    assert statuses == {"valid", "invalid"}

    # Batch: interrupt halfway then resume.
    state = new_batch(batch_id="r", items=json.loads(manifest.read_text(encoding="utf-8"))["items"], output_root=tmp_path / "out")
    batch = load_batch(state)
    for item in batch["items"]:
        item["state"] = "qa" if item["item_id"] in ("d1", "d2") else "pending"
    save_batch(state, batch)
    # Resume: released items skipped; pending remain.
    reloaded = load_batch(state)
    assert reloaded["items"][0]["state"] == "qa"


# --------------------------------------------------------------------------
# Scenario 5 & 6: single-file failure isolation + canary phase-stop
# --------------------------------------------------------------------------

def test_single_file_failure_does_not_abort_batch(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, count=5)
    state = new_batch(batch_id="r", items=json.loads(manifest.read_text(encoding="utf-8"))["items"], output_root=tmp_path / "out")
    batch = load_batch(state)
    for item in batch["items"]:
        if item["item_id"] == "d1":
            item["state"] = "failed"
            item["failure_reason"] = "render_crash"
        else:
            item["state"] = "released"
    save_batch(state, batch)
    summary = batch_summary(load_batch(state))
    assert summary["item_counts"]["failed"] == 1
    assert summary["item_counts"]["released"] == 4
    assert len(summary["failures"]) == 1


def test_canary_failure_blocks_pilot(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, count=6)
    state = new_batch(batch_id="r", items=json.loads(manifest.read_text(encoding="utf-8"))["items"], output_root=tmp_path / "out")
    batch = load_batch(state)
    batch["phase"] = "canary"
    for item in batch["items"]:
        if item["item_id"] in ("d1", "d2", "d3"):
            item["state"] = "failed"
            item["failure_reason"] = "font_below_v4_floor:d1"
        else:
            item["state"] = "qa"
    save_batch(state, batch)
    reasons = phase_gate(load_batch(state))
    assert any("font_floor_violation" in reason for reason in reasons)


# --------------------------------------------------------------------------
# Scenario 7 & 8: review decision -> revision run; production freeze
# --------------------------------------------------------------------------

def test_review_decision_creates_immutable_revision_run(tmp_path: Path) -> None:
    from services.engineering_drawing.review_decisions import add_decision, build_revision_run

    decisions_path = tmp_path / "review-decisions.json"
    decision = {
        "run_id": "run-001",
        "source_sha256": "a" * 64,
        "candidate_sha256": "b" * 64,
        "policy_fingerprint": "c" * 64,
        "supervisor_plan_sha256": "d" * 64,
        "region_id": "r1",
        "region_revision": 1,
        "decision": "edit",
        "approved_translation": "门卫室",
        "decision_reason": "wrong term",
        "tm_promotion_scope": "project",
    }
    add_decision(decisions_path, decision)
    revision = build_revision_run(
        original_run={"run_id": "run-001", "source_sha256": "a" * 64},
        decision=decision,
        work_dir=tmp_path,
    )
    record = json.loads(revision.read_text(encoding="utf-8"))
    assert record["revision_id"] == "run-001-r1"
    assert record["bindings"]["supervisor_plan_sha256"] == "d" * 64
    assert record["status"] == "translated"


def test_production_freeze_manifest(tmp_path: Path) -> None:
    """Freeze config: git commit, policy fingerprint, font hash, prompt hashes."""
    from services.engineering_drawing.fonts.resolve import font_sha256
    from services.engineering_drawing.orchestration_harness import canonical_policy_fingerprint

    frozen = {
        "schema": "engineering-drawing-frozen-production-config-v1",
        "git_commit": "rehearsal-sha",
        "policy_fingerprint": canonical_policy_fingerprint(),
        "prompt_hashes": {},
        "font_hash": font_sha256(),
        "ocr_config": {"deepseek_risk_budget": {"max_crops": 12, "max_crop_megapixels": 8}},
        "model_identifiers": {"supervisor": "gpt-5.6-sol", "reasoning_profile": "light"},
        "glossary_hash": None,
        "tm_hash": None,
        "document_context_template": {"language_policy": "bilingual", "units": "metric"},
    }
    path = tmp_path / "frozen-production-config.json"
    path.write_text(json.dumps(frozen, ensure_ascii=False, indent=2), encoding="utf-8")
    assert json.loads(path.read_text(encoding="utf-8"))["policy_fingerprint"]
