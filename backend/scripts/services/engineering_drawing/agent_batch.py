"""Bootstrap and gate the single-supervisor engineering-drawing agent.

This command deliberately stops before rendering when no approved multimodal
page plan exists.  It is the safe production entry point for the full source
inventory; the historical ``batch.py`` path is not allowed to publish on its
own anymore.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from .agent_system import EngineeringDrawingAgent
from .batch import discover_references, discover_sources, match_reference, _safe_slug
from .existing_translation_registry import extract_native_existing_translations


AGENT_BATCH_SCHEMA = "engineering-drawing-agent-batch-v1"


def run_agent_bootstrap(*, root: Path, output_root: Path, dpi: int = 144) -> dict[str, Any]:
    root = Path(root).resolve()
    output_root = Path(output_root).resolve()
    artifact_root = output_root / "agent-artifacts"
    artifact_root.mkdir(parents=True, exist_ok=True)
    agent = EngineeringDrawingAgent()
    sources = discover_sources(root)
    references = discover_references(root)
    records: list[dict[str, Any]] = []
    for index, source in enumerate(sources, start=1):
        slug = _safe_slug(source, root)
        artifact_dir = artifact_root / slug
        artifact_dir.mkdir(parents=True, exist_ok=True)
        reference = match_reference(source, references, root)
        manifest = agent.build_manifest(source, reference_pdf=reference)
        registry = (
            extract_native_existing_translations(reference)
            if reference is not None
            else {"items": [], "required_next_step": "no_reference_visual_ocr_path"}
        )
        registry_path = artifact_dir / "existing-translation-registry.json"
        registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        page_packets: list[dict[str, Any]] = []
        for page_index in range(manifest["source_snapshot"]["page_count"]):
            page_evidence = [item for item in registry.get("items", []) if item.get("page_index") == page_index]
            packet = agent.build_page_packet(
                source,
                page_index,
                manifest=manifest,
                evidence=page_evidence,
                output_dir=artifact_dir / f"page-{page_index + 1:04d}",
                dpi=dpi,
            )
            page_packets.append(
                {
                    "page_index": page_index,
                    "packet": str((artifact_dir / f"page-{page_index + 1:04d}" / "page-packet.json").resolve()),
                    "source_image": str((artifact_dir / f"page-{page_index + 1:04d}" / packet["source_image"]).resolve()),
                    "status": packet["plan_status"],
                    "evidence_items": len(page_evidence),
                }
            )
        manifest["pages"] = page_packets
        manifest["existing_translation_registry"] = str(registry_path.resolve())
        manifest["status"] = "awaiting_multimodal_supervisor_plan"
        manifest_path = artifact_dir / "agent-manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        records.append(
            {
                "source_pdf": str(source),
                "reference_pdf": str(reference) if reference else None,
                "artifact_dir": str(artifact_dir.resolve()),
                "page_count": manifest["source_snapshot"]["page_count"],
                "status": manifest["status"],
            }
        )
        print(f"[{index}/{len(sources)}] packetized {source.name} pages={manifest['source_snapshot']['page_count']}", flush=True)
    summary = {
        "schema": AGENT_BATCH_SCHEMA,
        "agent_name": "engineering-drawing-translator",
        "workflow_version": manifest.get("workflow_version") if records else None,
        "source_root": str(root),
        "artifact_root": str(artifact_root.resolve()),
        "current_release_directory": str(
            (output_root / "translated" / "v4.0-readable-zone-complete").resolve()
        ),
        "source_count": len(sources),
        "page_count": sum(int(item["page_count"]) for item in records),
        "awaiting_supervisor_plan": len(records),
        "published": 0,
        "records": records,
        "release_rule": "no approved multimodal plan, no final PDF publication",
        "historical_output_directories_are_evidence_only": ["01_报审图纸", "02_清真寺施工图纸"],
    }
    (artifact_root / "agent-batch-index.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


__all__ = ["AGENT_BATCH_SCHEMA", "run_agent_bootstrap"]
