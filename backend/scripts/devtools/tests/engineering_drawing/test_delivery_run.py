"""Delivery batch controller: plan packets, shards, states, resume, gates."""

from __future__ import annotations

import json
from pathlib import Path

import fitz
import pytest

from services.engineering_drawing.delivery_run import (
    PLAN_SCHEMA,
    batch_summary,
    build_plan_packet,
    build_plan_shards,
    export_plan_packets,
    import_supervisor_plans,
    load_batch,
    new_batch,
    phase_gate,
    save_batch,
    select_phase_items,
    validate_plan_against_packet,
)
from services.engineering_drawing.preflight import build_preflight_html, run_preflight


def _source_pdf(path: Path, *, text: str = "ROOF WATER TANK") -> Path:
    document = fitz.open()
    page = document.new_page(width=200, height=120)
    page.insert_text((10, 20), text, fontsize=8)
    document.save(path)
    document.close()
    return path


def _manifest(tmp_path: Path, *, count: int = 3) -> tuple[Path, Path]:
    source_root = tmp_path / "sources"
    source_root.mkdir()
    items = []
    for index in range(count):
        source = _source_pdf(source_root / f"drawing-{index + 1:03d}.pdf")
        items.append(
            {
                "item_id": f"drawing-{index + 1:03d}",
                "source_pdf": source.name,
                "relative_output": f"drawing-{index + 1:03d}.pdf",
                "document_context": {"drawing_discipline": "electrical" if index % 2 else "mechanical"},
            }
        )
    manifest = tmp_path / "delivery-160.json"
    manifest.write_text(json.dumps({"schema": "engineering-drawing-delivery-batch-v1", "batch_id": "delivery-160", "items": items}, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest, source_root


def test_export_plan_packets_writes_one_per_page(tmp_path: Path) -> None:
    manifest, source_root = _manifest(tmp_path, count=2)
    out = tmp_path / "packets"
    written = export_plan_packets(manifest=json.loads(manifest.read_text(encoding="utf-8")), source_root=source_root, out_dir=out)
    assert len(written) == 2  # one page each
    packet = json.loads(written[0].read_text(encoding="utf-8"))
    assert packet["schema"] == "engineering-drawing-plan-packet-v1"
    assert packet["source_sha256"]
    assert packet["page_size"] == [200.0, 120.0]
    assert any("ROOF" in c.get("text", "") for c in packet["native_text_candidates"])


def test_validate_plan_against_packet(tmp_path: Path) -> None:
    source = _source_pdf(tmp_path / "s.pdf")
    image = tmp_path / "p.png"
    with fitz.open(source) as document:
        document[0].get_pixmap(alpha=False).save(image)
    packet = build_plan_packet(
        packet_id="d-p0001",
        source_pdf=source,
        page_index=0,
        page_count=1,
        page_image=image,
        native_text_candidates=[{"text": "ROOF WATER TANK", "bbox": [0, 0, 100, 20], "rotation": 0}],
        ocr_suggested_regions=[],
        document_context=None,
        glossary_tm_refs=None,
    )
    good = {
        "schema": PLAN_SCHEMA,
        "packet_id": "d-p0001",
        "source_sha256": packet["source_sha256"],
        "page_index": 0,
        "semantic_blocks": [{"source_text": "ROOF WATER TANK", "coverage_status": "translated"}],
        "coverage_inventory": [],
    }
    assert validate_plan_against_packet(good, packet) == []
    bad = dict(good)
    bad["source_sha256"] = "0" * 64
    assert validate_plan_against_packet(bad, packet) != []
    incomplete = dict(good)
    incomplete["semantic_blocks"] = [{"source_text": "WATER TANK", "coverage_status": "translated"}]
    assert validate_plan_against_packet(incomplete, packet) != []


def test_import_supervisor_plans_marks_invalid(tmp_path: Path) -> None:
    manifest, source_root = _manifest(tmp_path, count=2)
    packets_dir = tmp_path / "packets"
    export_plan_packets(manifest=json.loads(manifest.read_text(encoding="utf-8")), source_root=source_root, out_dir=packets_dir)
    plans_dir = tmp_path / "plans"
    plans_dir.mkdir()
    # Build a valid plan from the first packet.
    packet = json.loads(sorted(packets_dir.rglob("packet-*.json"))[0].read_text(encoding="utf-8"))
    (plans_dir / "plan-001.json").write_text(
        json.dumps(
            {
                "schema": PLAN_SCHEMA,
                "packet_id": packet["packet_id"],
                "source_sha256": packet["source_sha256"],
                "page_index": 0,
                "semantic_blocks": [{"source_text": "ROOF WATER TANK", "coverage_status": "translated"}],
                "coverage_inventory": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    # An invalid plan with a wrong source hash.
    (plans_dir / "plan-002.json").write_text(
        json.dumps(
            {
                "schema": PLAN_SCHEMA,
                "packet_id": "missing-packet",
                "source_sha256": "0" * 64,
                "page_index": 0,
                "semantic_blocks": [],
                "coverage_inventory": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    result = import_supervisor_plans(plans_dir=plans_dir, packets_dir=packets_dir, out_dir=tmp_path / "import")
    statuses = {item["status"] for item in result["items"]}
    assert statuses == {"valid", "invalid"}


def test_plan_shards_bounded_and_keep_item_together(tmp_path: Path) -> None:
    manifest, source_root = _manifest(tmp_path, count=5)
    packets_dir = tmp_path / "packets"
    written = export_plan_packets(manifest=json.loads(manifest.read_text(encoding="utf-8")), source_root=source_root, out_dir=packets_dir)
    # Force tiny shards: max_pages=2.
    shards = build_plan_shards(packet_paths=written, out_dir=tmp_path / "shards", max_pages=2, max_regions=100)
    assert len(shards) >= 2
    for shard_path in shards:
        shard = json.loads(shard_path.read_text(encoding="utf-8"))
        assert shard["pages"] <= 2
        assert shard["schema"] == "engineering-drawing-delivery-shard-v1"


def test_batch_state_machine_and_resume(tmp_path: Path) -> None:
    manifest, _ = _manifest(tmp_path, count=4)
    state = new_batch(batch_id="b", items=json.loads(manifest.read_text(encoding="utf-8"))["items"], output_root=tmp_path / "out")
    batch = load_batch(state)
    assert batch["schema"] == "engineering-drawing-delivery-batch-v1"
    assert all(item["state"] == "pending" for item in batch["items"])
    # Select canary.
    selected = select_phase_items(batch, phase="canary", canary_size=2)
    assert len(selected) == 2
    for item in batch["items"]:
        if str(item["item_id"]) in selected:
            item["state"] = "preflight"
    # Mark one failed, others progressed; batch continues.
    for item in batch["items"]:
        if item["item_id"] == selected[0]:
            item["state"] = "failed"
            item["failure_reason"] = "severe_page_damage"
        elif item["item_id"] in selected:
            item["state"] = "qa"
    save_batch(state, batch)
    reloaded = load_batch(state)
    assert any(item["state"] == "failed" for item in reloaded["items"])
    summary = batch_summary(reloaded)
    assert summary["item_counts"]["failed"] == 1
    assert summary["item_counts"]["qa"] == 1


def test_phase_gate_blocks_on_canary_failure(tmp_path: Path) -> None:
    manifest, _ = _manifest(tmp_path, count=2)
    state = new_batch(batch_id="b", items=json.loads(manifest.read_text(encoding="utf-8"))["items"], output_root=tmp_path / "out")
    batch = load_batch(state)
    batch["phase"] = "canary"
    for item in batch["items"]:
        item["state"] = "failed"
        item["failure_reason"] = "font_below_v4_floor:drawing-001"
    save_batch(state, batch)
    reasons = phase_gate(load_batch(state))
    assert any("font_floor_violation" in reason for reason in reasons)


def test_select_phase_items_risk_stratified(tmp_path: Path) -> None:
    manifest, _ = _manifest(tmp_path, count=6)
    state = new_batch(batch_id="b", items=json.loads(manifest.read_text(encoding="utf-8"))["items"], output_root=tmp_path / "out")
    batch = load_batch(state)
    profiles = {
        f"drawing-{i:03d}": {"raster": "scanned" if i in (1, 2, 3) else "vector", "page_count": 1}
        for i in range(1, 7)
    }
    selected = select_phase_items(batch, phase="canary", canary_size=4, risk_profiles=profiles)
    assert len(selected) == 4
    # Highest-risk (scanned) items come first.
    assert str(selected[0]) in {f"drawing-{i:03d}" for i in (1, 2, 3)}


def test_preflight_report(tmp_path: Path) -> None:
    manifest, source_root = _manifest(tmp_path, count=3)
    report = run_preflight(manifest=json.loads(manifest.read_text(encoding="utf-8")), source_root=source_root, output_root=tmp_path / "out")
    assert report["schema"] == "engineering-drawing-delivery-preflight-v1"
    assert report["passed"] is True
    assert report["capacity"]["total_pdfs"] == 3
    assert report["codex_operator_supervisor"]["group"] == "manual"
    html_text = build_preflight_html(report)
    assert "<table>" in html_text
    assert "PASS" in html_text


def test_preflight_detects_missing_source(tmp_path: Path) -> None:
    source_root = tmp_path / "sources"
    source_root.mkdir()
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps({"items": [{"item_id": "a", "source_pdf": "missing.pdf"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    report = run_preflight(manifest=json.loads(manifest.read_text(encoding="utf-8")), source_root=source_root, output_root=tmp_path / "out")
    assert report["passed"] is False
    assert "sources_exist" in report["critical_failures"]
