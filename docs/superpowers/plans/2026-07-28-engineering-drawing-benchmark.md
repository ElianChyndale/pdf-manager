# Engineering Drawing Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reproducible 12-page engineering-drawing translation benchmark with Codex pre-annotation, user adjudication, locked gold records, hard-gate scoring, visual diffs, and version-promotion decisions.

**Architecture:** Add an isolated `services.engineering_drawing.benchmark` package. A versioned repository manifest identifies immutable source pages; generated PDFs, PNGs, annotations, audit events, model outputs, and reports live under a caller-supplied benchmark workspace and never enter the production `translated` directory. Deterministic validators and scorers consume the locked gold records, existing coverage/placement artifacts, and rendered PDFs; the multimodal model only proposes annotations and subjective visual findings, which remain auditable and user-adjudicated.

**Tech Stack:** Python 3.11, PyMuPDF 1.26.5, Pillow 10.4.0, existing translation-provider runtime, pytest 9.0.3, JSON/HTML artifacts.

## Global Constraints

- Do not invoke `batch-translate` or write PDFs into `output/pdf/engineering-drawing/01_Bilingual_Inline/translated`.
- Keep source English/Malay/Arabic/Jawi text visible; the benchmark evaluates added Chinese companions.
- Preserve exact numbers, units, models, equipment IDs, drawing numbers, and source rotation.
- Prefer safe whitespace plus a dark-blue 0.32 pt orthogonal leader without arrows; if blocked, shrink only to the configured minimum, then preserve the legacy placement and require manual review.
- Treat long notes and specifications as semantic blocks; keep distinct equipment IDs, table cells, legend entries, and title-block rows separate.
- Core-set inputs are page 1 of the 12 PDFs approved in `docs/superpowers/specs/2026-07-28-engineering-drawing-benchmark-design.md`.
- Generated benchmark assets default to `output/pdf/engineering-drawing/benchmark`; production delivery assets remain separate.
- Every gold-record mutation appends an audit event and increments `gold_version`; never overwrite adjudication history.

---

## File Structure

Create:

- `backend/scripts/services/engineering_drawing/benchmark/__init__.py` — public benchmark interfaces.
- `backend/scripts/services/engineering_drawing/benchmark/schema.py` — typed records and strict JSON validation.
- `backend/scripts/services/engineering_drawing/benchmark/core-set.v1.json` — approved 12-page manifest.
- `backend/scripts/services/engineering_drawing/benchmark/challenge-set.v1.json` — versioned, initially empty challenge-bank manifest.
- `backend/scripts/services/engineering_drawing/benchmark/workspace.py` — source freezing, hashes, page extraction, and stable workspace layout.
- `backend/scripts/services/engineering_drawing/benchmark/prelabel.py` — multimodal prelabel request/response contract and uncertainty selection.
- `backend/scripts/services/engineering_drawing/benchmark/adjudication.py` — append-only user decisions and gold locking.
- `backend/scripts/services/engineering_drawing/benchmark/scoring.py` — seven hard gates, five weighted scores, and promotion rule.
- `backend/scripts/services/engineering_drawing/benchmark/report.py` — side-by-side/diff PNGs and HTML/JSON reports.
- `backend/scripts/services/engineering_drawing/benchmark/runner.py` — seed, prelabel, adjudicate, evaluate orchestration.
- `backend/scripts/devtools/tests/engineering_drawing/test_benchmark_schema.py`
- `backend/scripts/devtools/tests/engineering_drawing/test_benchmark_workspace.py`
- `backend/scripts/devtools/tests/engineering_drawing/test_benchmark_prelabel.py`
- `backend/scripts/devtools/tests/engineering_drawing/test_benchmark_adjudication.py`
- `backend/scripts/devtools/tests/engineering_drawing/test_benchmark_scoring.py`
- `backend/scripts/devtools/tests/engineering_drawing/test_benchmark_report.py`
- `backend/scripts/devtools/tests/engineering_drawing/test_benchmark_runner.py`

Modify:

- `backend/scripts/services/engineering_drawing/cli.py:29-90,93-220` — add benchmark commands without changing `batch-translate`.
- `backend/scripts/services/engineering_drawing/README.md` — document benchmark commands, directories, and the no-batch safety boundary.

## Task 1: Versioned Core Manifest and Annotation Schema

**Files:**

- Create: `backend/scripts/services/engineering_drawing/benchmark/__init__.py`
- Create: `backend/scripts/services/engineering_drawing/benchmark/schema.py`
- Create: `backend/scripts/services/engineering_drawing/benchmark/core-set.v1.json`
- Create: `backend/scripts/devtools/tests/engineering_drawing/test_benchmark_schema.py`

**Interfaces:**

- Produces: `load_core_manifest(path: Path) -> CoreManifest`
- Produces: `load_challenge_manifest(path: Path) -> CoreManifest`
- Produces: `GoldSample.from_dict(value: dict) -> GoldSample`
- Produces: `GoldSample.to_dict() -> dict`
- Produces: `validate_gold_sample(sample: GoldSample) -> None`

- [ ] **Step 1: Write failing schema tests**

```python
from pathlib import Path

import pytest

from services.engineering_drawing.benchmark.schema import (
    GoldSample,
    load_challenge_manifest,
    load_core_manifest,
    validate_gold_sample,
)


def test_core_manifest_has_the_approved_twelve_page_one_samples():
    path = (
        Path(__file__).resolve().parents[3]
        / "services/engineering_drawing/benchmark/core-set.v1.json"
    )
    manifest = load_core_manifest(path)
    assert manifest.schema == "engineering-drawing-core-set-v1"
    assert len(manifest.samples) == 12
    assert [item.sample_id for item in manifest.samples] == [
        f"core-{index:02d}" for index in range(1, 13)
    ]
    assert {item.page_number for item in manifest.samples} == {1}
    assert len({item.relative_pdf.casefold() for item in manifest.samples}) == 12


def test_challenge_manifest_starts_empty_and_versioned():
    path = (
        Path(__file__).resolve().parents[3]
        / "services/engineering_drawing/benchmark/challenge-set.v1.json"
    )
    manifest = load_challenge_manifest(path)
    assert manifest.set_name == "challenge"
    assert manifest.benchmark_version == "challenge-v1"
    assert manifest.samples == ()


def test_gold_sample_rejects_target_inside_forbidden_zone():
    sample = GoldSample.from_dict(
        {
            "schema": "engineering-drawing-gold-v1",
            "sample_id": "core-03",
            "gold_version": 1,
            "status": "locked",
            "page": {"width": 300, "height": 200, "rotation": 0},
            "blocks": [
                {
                    "block_id": "core-03-b001",
                    "source_text": "ROOF SYSTEM",
                    "source_language": "en",
                    "source_bbox": [10, 10, 80, 25],
                    "rotation": 0,
                    "reading_order": 1,
                    "group_member_ids": ["ocr-1"],
                    "merge_decision": "single",
                    "gold_translation": "屋面系统",
                    "literal_tokens": [],
                    "allowed_regions": [[90, 10, 170, 30]],
                    "forbidden_zones": [[90, 10, 170, 30]],
                    "font_size_range": [3.2, 6.5],
                    "leader": {"allowed": True, "required": False},
                    "manual_review_required": False,
                }
            ],
            "audit": [],
        }
    )
    with pytest.raises(ValueError, match="allowed region overlaps forbidden zone"):
        validate_gold_sample(sample)
```

- [ ] **Step 2: Run the schema tests and confirm the missing module failure**

Run:

```powershell
cd backend/scripts
python -m pytest devtools/tests/engineering_drawing/test_benchmark_schema.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'services.engineering_drawing.benchmark'`.

- [ ] **Step 3: Implement strict dataclasses and validation**

Create `schema.py` with these public types and validation rules:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any


Rect = tuple[float, float, float, float]


def _rect(value: object, field_name: str) -> Rect:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError(f"{field_name} must contain four coordinates")
    result = tuple(float(item) for item in value)
    if result[2] <= result[0] or result[3] <= result[1]:
        raise ValueError(f"{field_name} must be non-empty")
    return result


def _intersects(left: Rect, right: Rect) -> bool:
    return min(left[2], right[2]) > max(left[0], right[0]) and min(
        left[3], right[3]
    ) > max(left[1], right[1])


def _inside(page: Rect, rect: Rect) -> bool:
    return (
        page[0] <= rect[0]
        and page[1] <= rect[1]
        and page[2] >= rect[2]
        and page[3] >= rect[3]
    )


@dataclass(frozen=True)
class CoreSample:
    sample_id: str
    category: str
    relative_pdf: str
    page_number: int
    goals: tuple[str, ...]


@dataclass(frozen=True)
class CoreManifest:
    schema: str
    benchmark_version: str
    samples: tuple[CoreSample, ...]
    set_name: str = "core"


@dataclass
class GoldBlock:
    block_id: str
    source_text: str
    source_language: str
    source_bbox: Rect
    rotation: int
    reading_order: int
    group_member_ids: list[str]
    merge_decision: str
    gold_translation: str
    literal_tokens: list[str]
    allowed_regions: list[Rect]
    forbidden_zones: list[Rect]
    font_size_range: tuple[float, float]
    leader: dict[str, bool]
    manual_review_required: bool = False


@dataclass
class GoldSample:
    schema: str
    sample_id: str
    gold_version: int
    status: str
    page: dict[str, float | int]
    blocks: list[GoldBlock]
    audit: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "GoldSample":
        blocks = []
        for raw in value.get("blocks", []):
            item = dict(raw)
            item["source_bbox"] = _rect(item["source_bbox"], "source_bbox")
            item["allowed_regions"] = [
                _rect(rect, "allowed_regions") for rect in item["allowed_regions"]
            ]
            item["forbidden_zones"] = [
                _rect(rect, "forbidden_zones") for rect in item["forbidden_zones"]
            ]
            item["font_size_range"] = tuple(
                float(number) for number in item["font_size_range"]
            )
            blocks.append(GoldBlock(**item))
        return cls(
            schema=str(value["schema"]),
            sample_id=str(value["sample_id"]),
            gold_version=int(value["gold_version"]),
            status=str(value["status"]),
            page=dict(value["page"]),
            blocks=blocks,
            audit=list(value.get("audit", [])),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_core_manifest(path: Path) -> CoreManifest:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    samples = tuple(
        CoreSample(
            sample_id=str(item["sample_id"]),
            category=str(item["category"]),
            relative_pdf=str(item["relative_pdf"]),
            page_number=int(item["page_number"]),
            goals=tuple(str(goal) for goal in item["goals"]),
        )
        for item in payload["samples"]
    )
    manifest = CoreManifest(
        schema=str(payload["schema"]),
        benchmark_version=str(payload["benchmark_version"]),
        samples=samples,
        set_name="core",
    )
    if manifest.schema != "engineering-drawing-core-set-v1":
        raise ValueError("unsupported core manifest schema")
    if len(samples) != 12 or len({item.sample_id for item in samples}) != 12:
        raise ValueError("core manifest must contain 12 unique samples")
    if any(item.page_number != 1 for item in samples):
        raise ValueError("approved core samples must use page 1")
    return manifest


def load_challenge_manifest(path: Path) -> CoreManifest:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema") != "engineering-drawing-challenge-set-v1":
        raise ValueError("unsupported challenge manifest schema")
    samples = tuple(
        CoreSample(
            sample_id=str(item["sample_id"]),
            category=str(item["category"]),
            relative_pdf=str(item["relative_pdf"]),
            page_number=int(item["page_number"]),
            goals=tuple(str(goal) for goal in item["goals"]),
        )
        for item in payload.get("samples", [])
    )
    if len({item.sample_id for item in samples}) != len(samples):
        raise ValueError("challenge sample IDs must be unique")
    return CoreManifest(
        schema=str(payload["schema"]),
        benchmark_version=str(payload["benchmark_version"]),
        samples=samples,
        set_name="challenge",
    )


def validate_gold_sample(sample: GoldSample) -> None:
    if sample.schema != "engineering-drawing-gold-v1":
        raise ValueError("unsupported gold schema")
    if sample.status not in {"candidate", "prelabeled", "adjudicated", "locked"}:
        raise ValueError("invalid gold status")
    if sample.gold_version < 1:
        raise ValueError("gold_version must be positive")
    block_ids = [block.block_id for block in sample.blocks]
    if len(block_ids) != len(set(block_ids)):
        raise ValueError("block_id values must be unique")
    page_rect = (
        0.0,
        0.0,
        float(sample.page["width"]),
        float(sample.page["height"]),
    )
    for block in sample.blocks:
        if block.rotation not in {0, 90, 180, 270}:
            raise ValueError("rotation must be orthogonal")
        if not block.source_text or not block.gold_translation:
            raise ValueError("source and gold translation are required")
        if block.font_size_range[0] < 3.2:
            raise ValueError("font size is below the workflow minimum")
        if not _inside(page_rect, block.source_bbox) or any(
            not _inside(page_rect, rect)
            for rect in [*block.allowed_regions, *block.forbidden_zones]
        ):
            raise ValueError("block geometry is outside the source page")
        if any(
            _intersects(allowed, forbidden)
            for allowed in block.allowed_regions
            for forbidden in block.forbidden_zones
        ):
            raise ValueError("allowed region overlaps forbidden zone")
```

Create `__init__.py` that exports `CoreManifest`, `GoldSample`, `load_core_manifest`, `load_challenge_manifest`, and `validate_gold_sample`.

- [ ] **Step 4: Add the complete approved manifest**

Create `core-set.v1.json` with `schema`, `benchmark_version`, and these 12 records. Each record uses `"page_number": 1` and the listed goal strings:

```json
{
  "schema": "engineering-drawing-core-set-v1",
  "benchmark_version": "core-v1",
  "samples": [
    {"sample_id":"core-01","category":"site_overview","relative_pdf":"报审图纸/275kV MEP Construction Drawing_260610/Construction Drawing/RCJM2 CN ELEC 20260610/Constrcution Drawing PDF/1310-CN-ELEC-A001_Site Plan.pdf","page_number":1,"goals":["map","rotated_text","company_information","whitespace_layout"]},
    {"sample_id":"core-02","category":"mosque_site","relative_pdf":"03_CONSTRUCTION DWG_MASJID_11 NOV 2025/A1 WORKING DRAWING/00_Site Masjid Tok Muda_CONSTRUCTION.pdf","page_number":1,"goals":["malay","legend","title_block","multi_region"]},
    {"sample_id":"core-03","category":"roof_detail","relative_pdf":"A3 DETAIL DRAWING/10_REV. JULAI 2025 ROOF DETAIL.pdf","page_number":1,"goals":["semantic_block","materials","numbers","units"]},
    {"sample_id":"core-04","category":"corner_bead_detail","relative_pdf":"A3 DETAIL DRAWING/17-CORNER BEAD DETAIL.pdf","page_number":1,"goals":["detail","product_note","image_text_mix","title_block"]},
    {"sample_id":"core-05","category":"tower_detail","relative_pdf":"A3 DETAIL DRAWING/13_REV. JULAI 2025 MENARA.pdf","page_number":1,"goals":["dense_vertical_labels","leaders","elevations","malay"]},
    {"sample_id":"core-06","category":"drawing_list","relative_pdf":"A3 DETAIL DRAWING/00_LIST OF DRAWING_A3 FORMAT.pdf","page_number":1,"goals":["table_rows","cell_wrap","repeated_terms","border_protection"]},
    {"sample_id":"core-07","category":"door_window_schedule","relative_pdf":"A3 DETAIL DRAWING/02_REV. JULAI 2025 JADUAL PINTU & TINGKAP.pdf","page_number":1,"goals":["table","dimensions","identifiers","graphics_text_mix"]},
    {"sample_id":"core-08","category":"single_line_diagram","relative_pdf":"报审图纸/275kV MEP Construction Drawing_260610/Construction Drawing/RCJM2 CN ELEC 20260610/Constrcution Drawing PDF/1310-CN-ELEC-SCH-C001_275kV SLD.pdf","page_number":1,"goals":["system_relationships","equipment_ids","voltage","title_block"]},
    {"sample_id":"core-09","category":"pa_schematic","relative_pdf":"报审图纸/275kV MEP Construction Drawing_260610/Construction Drawing/RCJM2 CN ELEC 20260610/Constrcution Drawing PDF/1310-CN-ELEC-PA-C001_PA Schematic.pdf","page_number":1,"goals":["network_lines","equipment_terms","table","association"]},
    {"sample_id":"core-10","category":"dense_mechanical","relative_pdf":"报审图纸/275kV MEP Construction Drawing_260610/Construction Drawing/RCJM2 CN MECH 20260610/PDF/1312-CN-MECH-ACMV-B002.pdf","page_number":1,"goals":["repeated_equipment","dense_labels","leader_avoidance","tiny_text"]},
    {"sample_id":"core-11","category":"company_project","relative_pdf":"报审图纸/RCJM2 CN R1 20260624/RCJM2 CN R1 20260624/PDF/1312-CN-MECH-PSI-A001-R1.pdf","page_number":1,"goals":["company","address","project_description","long_notes"]},
    {"sample_id":"core-12","category":"elevation","relative_pdf":"报审图纸/275kV MEP Construction Drawing_260610/Construction Drawing/RCJM2 CN ELEC 20260610/Constrcution Drawing PDF/1310-CN-ELEC-A002_Elevation.pdf","page_number":1,"goals":["elevation_labels","vertical_boundaries","whitespace","right_information_column"]}
  ]
}
```

Create `challenge-set.v1.json` as the valid empty starting bank:

```json
{
  "schema": "engineering-drawing-challenge-set-v1",
  "benchmark_version": "challenge-v1",
  "samples": []
}
```

- [ ] **Step 5: Run tests and commit**

Run:

```powershell
cd backend/scripts
python -m pytest devtools/tests/engineering_drawing/test_benchmark_schema.py -q
```

Expected: `3 passed`.

Commit:

```powershell
git add backend/scripts/services/engineering_drawing/benchmark backend/scripts/devtools/tests/engineering_drawing/test_benchmark_schema.py
git commit -m "feat: define engineering drawing benchmark schema"
```

## Task 2: Freeze Source Pages into an Isolated Workspace

**Files:**

- Create: `backend/scripts/services/engineering_drawing/benchmark/workspace.py`
- Create: `backend/scripts/devtools/tests/engineering_drawing/test_benchmark_workspace.py`

**Interfaces:**

- Consumes: `CoreManifest`, `CoreSample`
- Produces: `seed_workspace(source_root: Path, workspace: Path, manifest: CoreManifest, dpi: int = 144, challenge_manifest: CoreManifest | None = None) -> dict`
- Produces workspace files: `manifest.lock.json`, `samples/<id>/source.pdf`, `samples/<id>/source.png`, `samples/<id>/sample.json`

- [ ] **Step 1: Write the failing freeze test**

```python
from hashlib import sha256
from pathlib import Path

import fitz

from services.engineering_drawing.benchmark.schema import CoreManifest, CoreSample
from services.engineering_drawing.benchmark.workspace import seed_workspace


def test_seed_workspace_extracts_page_and_writes_stable_hashes(tmp_path: Path):
    source_root = tmp_path / "source"
    source_root.mkdir()
    pdf = source_root / "one.pdf"
    document = fitz.open()
    document.new_page(width=300, height=200).insert_text((20, 30), "ROOF SYSTEM")
    document.save(pdf)
    document.close()
    manifest = CoreManifest(
        schema="engineering-drawing-core-set-v1",
        benchmark_version="test-v1",
        samples=(
            CoreSample("core-03", "roof_detail", "one.pdf", 1, ("semantic_block",)),
        ),
    )

    result = seed_workspace(source_root, tmp_path / "benchmark", manifest, dpi=96)

    sample_dir = tmp_path / "benchmark/samples/core-03"
    frozen = sample_dir / "source.pdf"
    assert frozen.exists()
    assert (sample_dir / "source.png").exists()
    assert result["sample_count"] == 1
    assert result["samples"][0]["source_sha256"] == sha256(frozen.read_bytes()).hexdigest()
    assert result["production_output_touched"] is False
```

- [ ] **Step 2: Run the test and verify failure**

Run:

```powershell
cd backend/scripts
python -m pytest devtools/tests/engineering_drawing/test_benchmark_workspace.py -q
```

Expected: import fails because `benchmark.workspace` does not exist.

- [ ] **Step 3: Implement deterministic extraction and locking**

```python
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import fitz

from .schema import CoreManifest


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def seed_workspace(
    source_root: Path,
    workspace: Path,
    manifest: CoreManifest,
    dpi: int = 144,
    challenge_manifest: CoreManifest | None = None,
) -> dict:
    source_root = Path(source_root).resolve()
    workspace = Path(workspace).resolve()
    records = []
    manifest_sets = [(manifest.set_name, manifest)]
    if challenge_manifest is not None:
        manifest_sets.append((challenge_manifest.set_name, challenge_manifest))
    for set_name, selected_manifest in manifest_sets:
        for spec in selected_manifest.samples:
            source = (source_root / spec.relative_pdf).resolve()
            if source_root not in source.parents or not source.is_file():
                raise FileNotFoundError(f"core source is missing or outside root: {source}")
            sample_dir = workspace / "samples" / spec.sample_id
            sample_dir.mkdir(parents=True, exist_ok=True)
            frozen_pdf = sample_dir / "source.pdf"
            with fitz.open(source) as document:
                if spec.page_number > document.page_count:
                    raise ValueError(f"{spec.sample_id} page is outside source PDF")
                frozen_document = fitz.open()
                frozen_document.insert_pdf(
                    document,
                    from_page=spec.page_number - 1,
                    to_page=spec.page_number - 1,
                )
                frozen_document.save(
                    frozen_pdf,
                    garbage=4,
                    deflate=True,
                    no_new_id=True,
                )
                frozen_document.close()
            with fitz.open(frozen_pdf) as frozen_document:
                page = frozen_document[0]
                pixmap = page.get_pixmap(dpi=dpi, alpha=False)
                pixmap.save(sample_dir / "source.png")
                page_size = [page.rect.width, page.rect.height]
                page_rotation = page.rotation
            record = {
                "sample_id": spec.sample_id,
                "set_name": set_name,
                "category": spec.category,
                "relative_pdf": spec.relative_pdf,
                "page_number": spec.page_number,
                "source_file_sha256": _hash(source),
                "source_sha256": _hash(frozen_pdf),
                "preview_sha256": _hash(sample_dir / "source.png"),
                "page_size": page_size,
                "page_rotation": page_rotation,
                "dpi": dpi,
                "goals": list(spec.goals),
                "status": "candidate",
            }
            _write_json(sample_dir / "sample.json", record)
            records.append(record)
    lock = {
        "schema": "engineering-drawing-benchmark-lock-v1",
        "benchmark_version": manifest.benchmark_version,
        "sample_count": len(records),
        "core_sample_count": sum(item["set_name"] == "core" for item in records),
        "challenge_sample_count": sum(item["set_name"] == "challenge" for item in records),
        "production_output_touched": False,
        "samples": records,
    }
    _write_json(workspace / "manifest.lock.json", lock)
    return lock
```

- [ ] **Step 4: Run tests and commit**

Run:

```powershell
cd backend/scripts
python -m pytest devtools/tests/engineering_drawing/test_benchmark_workspace.py -q
```

Expected: `1 passed`.

Commit:

```powershell
git add backend/scripts/services/engineering_drawing/benchmark/workspace.py backend/scripts/devtools/tests/engineering_drawing/test_benchmark_workspace.py
git commit -m "feat: freeze engineering benchmark pages"
```

## Task 3: Codex Prelabels and Uncertainty Queue

**Files:**

- Create: `backend/scripts/services/engineering_drawing/benchmark/prelabel.py`
- Create: `backend/scripts/devtools/tests/engineering_drawing/test_benchmark_prelabel.py`

**Interfaces:**

- Consumes: source PNG, OCR/vector region dictionaries, `request_chat_content`
- Produces: `build_prelabel_request(*, sample_id: str, image_data_url: str, regions: list[dict]) -> list[dict]`
- Produces: `parse_prelabel_response(content: str, sample_id: str) -> dict`
- Produces: `select_adjudication_queue(prelabel: dict) -> list[dict]`
- Produces: `parse_visual_review_response(content: str, sample_id: str, model: str) -> dict`
- Produces: `request_visual_review(...) -> dict`

- [ ] **Step 1: Write failing tests for block grouping and queue selection**

```python
import json

from services.engineering_drawing.benchmark.prelabel import (
    parse_prelabel_response,
    parse_visual_review_response,
    select_adjudication_queue,
)


def test_prelabel_keeps_paragraph_together_and_ids_separate():
    content = json.dumps(
        {
            "blocks": [
                {
                    "block_id": "core-03-b001",
                    "member_ids": ["ocr-1", "ocr-2", "ocr-3"],
                    "source_text": "ROOF SYSTEM - CUT TO LENGTH KLIPLOK OPTIMA",
                    "source_language": "en",
                    "source_bbox": [10, 10, 250, 60],
                    "rotation": 0,
                    "reading_order": 1,
                    "merge_decision": "merge_paragraph",
                    "gold_translation": "屋面系统——按长度定制 KLIPLOK OPTIMA",
                    "literal_tokens": ["KLIPLOK OPTIMA"],
                    "allowed_regions": [[10, 70, 250, 105]],
                    "forbidden_zones": [[10, 10, 250, 60]],
                    "font_size_range": [3.2, 6.5],
                    "leader": {"allowed": False, "required": False},
                    "confidence": 0.92,
                    "risk_flags": [],
                },
                {
                    "block_id": "core-03-b002",
                    "member_ids": ["ocr-4"],
                    "source_text": "KL98",
                    "source_language": "en",
                    "source_bbox": [260, 10, 290, 25],
                    "rotation": 0,
                    "reading_order": 2,
                    "merge_decision": "separate_identifier",
                    "gold_translation": "KL98 型号",
                    "literal_tokens": ["KL98"],
                    "allowed_regions": [[260, 30, 295, 45]],
                    "forbidden_zones": [[260, 10, 290, 25]],
                    "font_size_range": [3.2, 5.8],
                    "leader": {"allowed": True, "required": False},
                    "confidence": 0.72,
                    "risk_flags": ["identifier_boundary"],
                },
            ]
        }
    )
    prelabel = parse_prelabel_response(content, "core-03")
    queue = select_adjudication_queue(prelabel)
    assert len(prelabel["blocks"][0]["member_ids"]) == 3
    assert [item["block_id"] for item in queue] == ["core-03-b002"]


def test_prelabel_rejects_missing_source_literal():
    content = json.dumps(
        {
            "blocks": [
                {
                    "block_id": "core-03-b001",
                    "member_ids": ["ocr-1"],
                    "source_text": "0.48MM BMT",
                    "source_language": "en",
                    "source_bbox": [1, 1, 30, 10],
                    "rotation": 0,
                    "reading_order": 1,
                    "merge_decision": "single",
                    "gold_translation": "基板厚度",
                    "literal_tokens": ["0.48MM BMT"],
                    "allowed_regions": [[35, 1, 80, 15]],
                    "forbidden_zones": [[1, 1, 30, 10]],
                    "font_size_range": [3.2, 5.8],
                    "leader": {"allowed": True, "required": False},
                    "confidence": 0.9,
                    "risk_flags": [],
                }
            ]
        }
    )
    try:
        parse_prelabel_response(content, "core-03")
    except ValueError as exc:
        assert "literal token" in str(exc)
    else:
        raise AssertionError("missing literal token must be rejected")


def test_visual_review_has_bounded_scores_and_auditable_findings():
    result = parse_visual_review_response(
        json.dumps(
            {
                "layout_association": 17,
                "page_readability": 12,
                "findings": [
                    {
                        "code": "leader_route",
                        "region_id": "core-03-b002",
                        "reason": "引线绕开原文且关联明确",
                    }
                ],
            }
        ),
        sample_id="core-03",
        model="gpt-5.6-sol",
    )
    assert result["layout_association"] == 17
    assert result["page_readability"] == 12
    assert result["findings"][0]["reason"]
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
cd backend/scripts
python -m pytest devtools/tests/engineering_drawing/test_benchmark_prelabel.py -q
```

Expected: import fails because `benchmark.prelabel` does not exist.

- [ ] **Step 3: Implement the strict prelabel response contract**

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from services.translation.llm.shared.response_parsing import extract_json_text


PRELABEL_SCHEMA = "engineering-drawing-prelabel-v1"
PRELABEL_PROMPT_VERSION = "2026-07-benchmark-block-v1"


def build_prelabel_request(
    *,
    sample_id: str,
    image_data_url: str,
    regions: list[dict],
) -> list[dict]:
    rules = (
        "Group complete notes and specifications by meaning, not individual words. "
        "Keep equipment IDs, table cells, legend entries, dimensions, and title rows separate. "
        "Preserve all numbers, units, models, IDs, and source rotation. "
        "Propose allowed whitespace regions and forbidden source/dimension/line zones. "
        "Prefer right, then below, then above; use an orthogonal leader only for dense CAD labels."
    )
    return [
        {"role": "system", "content": rules},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": json.dumps({"sample_id": sample_id, "regions": regions}, ensure_ascii=False)},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ],
        },
    ]


def parse_prelabel_response(content: str, sample_id: str) -> dict:
    payload = json.loads(extract_json_text(content))
    blocks = []
    seen = set()
    for raw in payload.get("blocks", []):
        item = dict(raw)
        block_id = str(item.get("block_id") or "")
        if not block_id.startswith(f"{sample_id}-b") or block_id in seen:
            raise ValueError("block_id must be stable and unique")
        seen.add(block_id)
        target = str(item.get("gold_translation") or "")
        for token in item.get("literal_tokens", []):
            if str(token).replace(" ", "") not in target.replace(" ", ""):
                raise ValueError(f"literal token missing from translation: {token}")
        confidence = float(item.get("confidence", 0))
        if not 0 <= confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        blocks.append(item)
    return {
        "schema": PRELABEL_SCHEMA,
        "prompt_version": PRELABEL_PROMPT_VERSION,
        "sample_id": sample_id,
        "status": "prelabeled",
        "blocks": blocks,
    }


def select_adjudication_queue(prelabel: dict) -> list[dict]:
    high_value_flags = {
        "identifier_boundary",
        "number_or_unit",
        "unreadable",
        "layout_collision",
        "leader_route",
        "table_boundary",
    }
    return [
        block
        for block in prelabel.get("blocks", [])
        if float(block.get("confidence", 0)) < 0.8
        or bool(high_value_flags.intersection(block.get("risk_flags", [])))
    ]


def request_prelabels(
    *,
    sample_id: str,
    image_data_url: str,
    regions: list[dict],
    page: dict[str, float | int],
    api_key: str,
    model: str,
    base_url: str,
    request_fn: Callable[..., str],
) -> dict:
    content = request_fn(
        api_key=api_key,
        model=model,
        base_url=base_url,
        messages=build_prelabel_request(
            sample_id=sample_id,
            image_data_url=image_data_url,
            regions=regions,
        ),
        request_label="engineering-benchmark-prelabel",
    )
    result = parse_prelabel_response(content, sample_id)
    result["page"] = dict(page)
    return result


def parse_visual_review_response(content: str, sample_id: str, model: str) -> dict:
    payload = json.loads(extract_json_text(content))
    layout = float(payload.get("layout_association", -1))
    readability = float(payload.get("page_readability", -1))
    if not 0 <= layout <= 20 or not 0 <= readability <= 15:
        raise ValueError("visual review scores are outside their allowed ranges")
    findings = []
    for raw in payload.get("findings", []):
        item = dict(raw)
        if not str(item.get("code") or "") or not str(item.get("reason") or ""):
            raise ValueError("every visual finding requires code and reason")
        findings.append(item)
    return {
        "schema": "engineering-drawing-visual-review-v1",
        "prompt_version": "2026-07-benchmark-visual-v1",
        "sample_id": sample_id,
        "model": model,
        "layout_association": layout,
        "page_readability": readability,
        "findings": findings,
    }


def request_visual_review(
    *,
    sample_id: str,
    source_image_data_url: str,
    candidate_image_data_url: str,
    api_key: str,
    model: str,
    base_url: str,
    request_fn: Callable[..., str],
) -> dict:
    messages = [
        {
            "role": "system",
            "content": (
                "Compare the source and bilingual candidate as an engineering drawing. "
                "Score layout association from 0 to 20 and whole-page readability from 0 to 15. "
                "Check missing translations, semantic fragmentation, source overlap, unsafe font size, "
                "unclear source-target association, and leader obstruction. Return JSON only."
            ),
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": json.dumps({"sample_id": sample_id})},
                {"type": "image_url", "image_url": {"url": source_image_data_url}},
                {"type": "image_url", "image_url": {"url": candidate_image_data_url}},
            ],
        },
    ]
    content = request_fn(
        api_key=api_key,
        model=model,
        base_url=base_url,
        messages=messages,
        request_label="engineering-benchmark-visual-review",
    )
    return parse_visual_review_response(content, sample_id, model)
```

- [ ] **Step 4: Run tests and commit**

Run:

```powershell
cd backend/scripts
python -m pytest devtools/tests/engineering_drawing/test_benchmark_prelabel.py -q
```

Expected: `3 passed`.

Commit:

```powershell
git add backend/scripts/services/engineering_drawing/benchmark/prelabel.py backend/scripts/devtools/tests/engineering_drawing/test_benchmark_prelabel.py
git commit -m "feat: add engineering benchmark prelabels"
```

## Task 4: Append-Only Adjudication and Gold Locking

**Files:**

- Create: `backend/scripts/services/engineering_drawing/benchmark/adjudication.py`
- Create: `backend/scripts/devtools/tests/engineering_drawing/test_benchmark_adjudication.py`

**Interfaces:**

- Consumes: prelabel JSON and a user decision JSON
- Produces: `apply_adjudication(prelabel: dict, decisions: list[dict], actor: str, decided_at: str) -> GoldSample`
- Produces: `lock_gold(sample: GoldSample, actor: str, decided_at: str) -> GoldSample`

- [ ] **Step 1: Write failing audit/version tests**

```python
from services.engineering_drawing.benchmark.adjudication import (
    apply_adjudication,
    lock_gold,
)


def _prelabel():
    return {
        "schema": "engineering-drawing-prelabel-v1",
        "sample_id": "core-03",
        "status": "prelabeled",
        "page": {"width": 300, "height": 200, "rotation": 0},
        "blocks": [
            {
                "block_id": "core-03-b001",
                "member_ids": ["ocr-1", "ocr-2"],
                "source_text": "ROOF SYSTEM 0.48MM BMT",
                "source_language": "en",
                "source_bbox": [10, 10, 150, 30],
                "rotation": sample_record["page_rotation"],
                "reading_order": 1,
                "merge_decision": "merge_paragraph",
                "gold_translation": "屋面系统，0.48MM BMT",
                "literal_tokens": ["0.48MM BMT"],
                "allowed_regions": [[10, 40, 170, 65]],
                "forbidden_zones": [[10, 10, 150, 30]],
                "font_size_range": [3.2, 6.5],
                "leader": {"allowed": False, "required": False},
                "confidence": 0.7,
                "risk_flags": ["layout_collision"],
            }
        ],
    }


def test_adjudication_changes_value_and_appends_audit():
    sample = apply_adjudication(
        _prelabel(),
        [
            {
                "block_id": "core-03-b001",
                "field": "gold_translation",
                "value": "屋面系统：基板厚度 0.48MM BMT",
                "reason": "按完整技术说明翻译",
            }
        ],
        actor="user",
        decided_at="2026-07-28T10:00:00+08:00",
    )
    assert sample.gold_version == 1
    assert sample.blocks[0].gold_translation == "屋面系统：基板厚度 0.48MM BMT"
    assert sample.audit[0]["old_value"] == "屋面系统，0.48MM BMT"
    assert sample.audit[0]["new_value"] == "屋面系统：基板厚度 0.48MM BMT"
    locked = lock_gold(sample, actor="user", decided_at="2026-07-28T10:05:00+08:00")
    assert locked.status == "locked"
    assert locked.gold_version == 2
    assert locked.audit[-1]["action"] == "lock"
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
cd backend/scripts
python -m pytest devtools/tests/engineering_drawing/test_benchmark_adjudication.py -q
```

Expected: import fails because `benchmark.adjudication` does not exist.

- [ ] **Step 3: Implement field-limited decisions and immutable history**

```python
from __future__ import annotations

from copy import deepcopy

from .schema import GoldSample, validate_gold_sample


EDITABLE_FIELDS = {
    "gold_translation",
    "merge_decision",
    "allowed_regions",
    "forbidden_zones",
    "font_size_range",
    "leader",
    "manual_review_required",
}


def _gold_payload(prelabel: dict) -> dict:
    blocks = []
    for raw in prelabel["blocks"]:
        blocks.append(
            {
                "block_id": raw["block_id"],
                "source_text": raw["source_text"],
                "source_language": raw["source_language"],
                "source_bbox": raw["source_bbox"],
                "rotation": raw["rotation"],
                "reading_order": raw["reading_order"],
                "group_member_ids": list(raw["member_ids"]),
                "merge_decision": raw["merge_decision"],
                "gold_translation": raw["gold_translation"],
                "literal_tokens": list(raw["literal_tokens"]),
                "allowed_regions": list(raw["allowed_regions"]),
                "forbidden_zones": list(raw["forbidden_zones"]),
                "font_size_range": list(raw["font_size_range"]),
                "leader": dict(raw["leader"]),
                "manual_review_required": False,
            }
        )
    return {
        "schema": "engineering-drawing-gold-v1",
        "sample_id": prelabel["sample_id"],
        "gold_version": 1,
        "status": "adjudicated",
        "page": dict(prelabel.get("page") or {"width": 1, "height": 1, "rotation": 0}),
        "blocks": blocks,
        "audit": [],
    }


def apply_adjudication(
    prelabel: dict,
    decisions: list[dict],
    actor: str,
    decided_at: str,
) -> GoldSample:
    payload = _gold_payload(deepcopy(prelabel))
    by_id = {block["block_id"]: block for block in payload["blocks"]}
    for decision in decisions:
        block_id = str(decision["block_id"])
        field = str(decision["field"])
        if block_id not in by_id or field not in EDITABLE_FIELDS:
            raise ValueError("decision targets an unknown block or field")
        reason = str(decision.get("reason") or "").strip()
        if not reason:
            raise ValueError("every adjudication requires a reason")
        old_value = deepcopy(by_id[block_id][field])
        new_value = deepcopy(decision["value"])
        by_id[block_id][field] = new_value
        payload["audit"].append(
            {
                "action": "adjudicate",
                "block_id": block_id,
                "field": field,
                "old_value": old_value,
                "new_value": new_value,
                "reason": reason,
                "actor": actor,
                "decided_at": decided_at,
            }
        )
    sample = GoldSample.from_dict(payload)
    validate_gold_sample(sample)
    return sample


def lock_gold(sample: GoldSample, actor: str, decided_at: str) -> GoldSample:
    payload = sample.to_dict()
    payload["gold_version"] = sample.gold_version + 1
    payload["status"] = "locked"
    payload["audit"].append(
        {
            "action": "lock",
            "actor": actor,
            "decided_at": decided_at,
            "from_version": sample.gold_version,
            "to_version": sample.gold_version + 1,
        }
    )
    locked = GoldSample.from_dict(payload)
    validate_gold_sample(locked)
    return locked
```

- [ ] **Step 4: Run tests and commit**

Run:

```powershell
cd backend/scripts
python -m pytest devtools/tests/engineering_drawing/test_benchmark_adjudication.py -q
```

Expected: `1 passed`.

Commit:

```powershell
git add backend/scripts/services/engineering_drawing/benchmark/adjudication.py backend/scripts/devtools/tests/engineering_drawing/test_benchmark_adjudication.py
git commit -m "feat: add benchmark gold adjudication"
```

## Task 5: Hard Gates, Weighted Scoring, and Promotion Rules

**Files:**

- Create: `backend/scripts/services/engineering_drawing/benchmark/scoring.py`
- Create: `backend/scripts/devtools/tests/engineering_drawing/test_benchmark_scoring.py`

**Interfaces:**

- Consumes: locked `GoldSample`, candidate blocks, placement audit, existing `analyze_visual_qa` result, PDF text diagnostics
- Produces: `score_sample(*, gold_blocks: list[dict], candidate_blocks: list[dict], visual_qa: dict, pdf_diagnostics: dict, subjective: dict) -> dict`
- Produces: `promotion_decision(current: dict, candidate: dict) -> dict`

- [ ] **Step 1: Write failing hard-gate and promotion tests**

```python
from services.engineering_drawing.benchmark.scoring import (
    promotion_decision,
    score_sample,
)


def test_missing_block_is_a_hard_failure_despite_other_scores():
    result = score_sample(
        gold_blocks=[
            {
                "block_id": "b1",
                "gold_translation": "屋面系统",
                "literal_tokens": [],
                "merge_decision": "single",
                "rotation": 0,
                "manual_review_required": False,
            }
        ],
        candidate_blocks=[],
        visual_qa={
            "visual_overlap_count": 0,
            "leader_collision_count": 0,
            "untranslated_candidate_count": 0,
        },
        pdf_diagnostics={
            "replacement_characters": 0,
            "private_use_characters": 0,
            "clipped_or_outside_count": 0,
        },
        subjective={"page_readability": 15, "layout_association": 20},
    )
    assert result["passed"] is False
    assert result["hard_failures"][0]["code"] == "missing_translation"


def test_promotion_requires_gain_or_equal_score_with_less_manual_review():
    current = {
        "core_score": 86.0,
        "hard_failure_count": 0,
        "manual_review_rate": 0.12,
        "category_scores": {"table": 85.0, "detail": 87.0},
        "challenge_pass_rate": 0.8,
    }
    candidate = {
        "core_score": 86.0,
        "hard_failure_count": 0,
        "manual_review_rate": 0.08,
        "category_scores": {"table": 84.0, "detail": 88.0},
        "challenge_pass_rate": 0.81,
    }
    assert promotion_decision(current, candidate)["promote"] is True
    candidate["category_scores"]["table"] = 81.9
    assert promotion_decision(current, candidate)["promote"] is False
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
cd backend/scripts
python -m pytest devtools/tests/engineering_drawing/test_benchmark_scoring.py -q
```

Expected: import fails because `benchmark.scoring` does not exist.

- [ ] **Step 3: Implement deterministic gates and score composition**

```python
from __future__ import annotations

import re
from typing import Any


_CJK = re.compile(r"[\u3400-\u9fff]")


def _fold(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()


def _rect(value: object) -> tuple[float, float, float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    result = tuple(float(item) for item in value)
    return result if result[2] > result[0] and result[3] > result[1] else None


def _contains(outer: tuple[float, ...], inner: tuple[float, ...]) -> bool:
    return (
        outer[0] <= inner[0]
        and outer[1] <= inner[1]
        and outer[2] >= inner[2]
        and outer[3] >= inner[3]
    )


def _intersects(left: tuple[float, ...], right: tuple[float, ...]) -> bool:
    return min(left[2], right[2]) > max(left[0], right[0]) and min(
        left[3], right[3]
    ) > max(left[1], right[1])


def score_sample(
    *,
    gold_blocks: list[dict],
    candidate_blocks: list[dict],
    visual_qa: dict,
    pdf_diagnostics: dict,
    subjective: dict,
) -> dict:
    candidate_by_id = {
        str(item.get("block_id") or item.get("region_id")): item
        for item in candidate_blocks
    }
    hard_failures: list[dict[str, Any]] = []
    semantic_points = coverage_points = grouping_points = 0.0
    for gold in gold_blocks:
        block_id = str(gold["block_id"])
        candidate = candidate_by_id.get(block_id)
        if candidate is None or not str(candidate.get("translated_text") or "").strip():
            if not gold.get("manual_review_required"):
                hard_failures.append({"code": "missing_translation", "block_id": block_id})
            continue
        target = str(candidate["translated_text"])
        if not _CJK.search(target):
            hard_failures.append({"code": "missing_chinese", "block_id": block_id})
        missing_literals = [
            token for token in gold.get("literal_tokens", []) if _fold(token) not in _fold(target)
        ]
        if missing_literals:
            hard_failures.append(
                {"code": "literal_changed", "block_id": block_id, "tokens": missing_literals}
            )
        semantic_points += 30 / max(1, len(gold_blocks)) if _fold(gold["gold_translation"]) == _fold(target) else 15 / max(1, len(gold_blocks))
        coverage_points += 20 / max(1, len(gold_blocks))
        if str(candidate.get("merge_decision")) == str(gold.get("merge_decision")):
            grouping_points += 15 / max(1, len(gold_blocks))
        else:
            hard_failures.append({"code": "wrong_grouping", "block_id": block_id})
        if int(candidate.get("rotation", 0)) != int(gold.get("rotation", 0)):
            hard_failures.append({"code": "wrong_rotation", "block_id": block_id})
        target_bbox = _rect(candidate.get("target_bbox"))
        allowed = [
            rect for value in gold.get("allowed_regions", []) if (rect := _rect(value))
        ]
        forbidden = [
            rect for value in gold.get("forbidden_zones", []) if (rect := _rect(value))
        ]
        if target_bbox is None:
            hard_failures.append({"code": "missing_target_bbox", "block_id": block_id})
        elif allowed and not any(_contains(rect, target_bbox) for rect in allowed):
            hard_failures.append({"code": "outside_allowed_region", "block_id": block_id})
        elif any(_intersects(rect, target_bbox) for rect in forbidden):
            hard_failures.append({"code": "forbidden_zone_overlap", "block_id": block_id})
        font_range = [float(value) for value in gold.get("font_size_range", [3.2, 18])]
        font_size = float(candidate.get("font_size", 0))
        if not font_range[0] <= font_size <= font_range[1]:
            hard_failures.append({"code": "unsafe_font_size", "block_id": block_id})
        leader_rule = dict(gold.get("leader") or {})
        leader = dict(candidate.get("leader") or {})
        leader_drawn = leader.get("status") == "drawn"
        if leader_rule.get("required") and not leader_drawn:
            hard_failures.append({"code": "required_leader_missing", "block_id": block_id})
        if leader_drawn and not leader_rule.get("allowed", False):
            hard_failures.append({"code": "leader_forbidden", "block_id": block_id})
        if leader_drawn and (
            leader.get("color") != "dark_blue"
            or abs(float(leader.get("width_points", 0)) - 0.32) > 0.001
            or bool(leader.get("arrow"))
            or leader.get("route") != "orthogonal"
        ):
            hard_failures.append({"code": "leader_style", "block_id": block_id})
    duplicate_ids = [
        block_id
        for block_id in candidate_by_id
        if sum(
            1
            for item in candidate_blocks
            if str(item.get("block_id") or item.get("region_id")) == block_id
        )
        > 1
    ]
    if duplicate_ids:
        hard_failures.append({"code": "duplicate_translation", "block_ids": duplicate_ids})
    if pdf_diagnostics.get("replacement_characters") or pdf_diagnostics.get("private_use_characters"):
        hard_failures.append({"code": "garbled_text"})
    if pdf_diagnostics.get("clipped_or_outside_count"):
        hard_failures.append({"code": "clipped_or_outside"})
    if visual_qa.get("visual_overlap_count"):
        hard_failures.append({"code": "source_or_translation_overlap"})
    if visual_qa.get("leader_collision_count"):
        hard_failures.append({"code": "leader_collision"})
    if visual_qa.get("untranslated_candidate_count"):
        hard_failures.append({"code": "untranslated_candidate"})
    layout_points = max(0.0, min(20.0, float(subjective.get("layout_association", 0))))
    readability_points = max(0.0, min(15.0, float(subjective.get("page_readability", 0))))
    dimensions = {
        "semantic_terminology": round(semantic_points, 3),
        "coverage_deduplication": round(coverage_points, 3),
        "semantic_grouping": round(grouping_points, 3),
        "layout_association": layout_points,
        "page_readability": readability_points,
    }
    return {
        "schema": "engineering-drawing-score-v1",
        "hard_failures": hard_failures,
        "hard_failure_count": len(hard_failures),
        "dimensions": dimensions,
        "score": round(sum(dimensions.values()), 3),
        "passed": not hard_failures,
    }


def promotion_decision(current: dict, candidate: dict) -> dict:
    reasons = []
    if int(candidate["hard_failure_count"]) > int(current["hard_failure_count"]):
        reasons.append("new_hard_failures")
    score_gain = float(candidate["core_score"]) - float(current["core_score"])
    if score_gain < 1 and not (
        score_gain >= 0
        and float(candidate["manual_review_rate"]) < float(current["manual_review_rate"])
    ):
        reasons.append("insufficient_core_gain")
    for category, old_score in current["category_scores"].items():
        if float(candidate["category_scores"].get(category, 0)) < float(old_score) - 3:
            reasons.append(f"category_regression:{category}")
    if float(candidate["challenge_pass_rate"]) < float(current["challenge_pass_rate"]):
        reasons.append("challenge_regression")
    return {"promote": not reasons, "reasons": reasons, "core_score_gain": score_gain}
```

- [ ] **Step 4: Add one test for every remaining hard gate**

Add parameterized cases for:

```python
import pytest


@pytest.mark.parametrize(
    ("visual", "diagnostics", "expected"),
    [
        ({"visual_overlap_count": 1, "leader_collision_count": 0, "untranslated_candidate_count": 0}, {}, "source_or_translation_overlap"),
        ({"visual_overlap_count": 0, "leader_collision_count": 1, "untranslated_candidate_count": 0}, {}, "leader_collision"),
        ({"visual_overlap_count": 0, "leader_collision_count": 0, "untranslated_candidate_count": 1}, {}, "untranslated_candidate"),
        ({"visual_overlap_count": 0, "leader_collision_count": 0, "untranslated_candidate_count": 0}, {"replacement_characters": 1}, "garbled_text"),
        ({"visual_overlap_count": 0, "leader_collision_count": 0, "untranslated_candidate_count": 0}, {"clipped_or_outside_count": 1}, "clipped_or_outside"),
    ],
)
def test_visual_and_pdf_hard_gates(visual, diagnostics, expected):
    result = score_sample(
        gold_blocks=[],
        candidate_blocks=[],
        visual_qa=visual,
        pdf_diagnostics=diagnostics,
        subjective={"page_readability": 15, "layout_association": 20},
    )
    assert expected in {item["code"] for item in result["hard_failures"]}


def test_layout_constraints_reject_forbidden_zone_and_wrong_leader_style():
    result = score_sample(
        gold_blocks=[
            {
                "block_id": "b1",
                "gold_translation": "屋面系统",
                "literal_tokens": [],
                "merge_decision": "single",
                "rotation": 0,
                "allowed_regions": [[80, 10, 180, 40]],
                "forbidden_zones": [[100, 10, 120, 40]],
                "font_size_range": [3.2, 6.5],
                "leader": {"allowed": True, "required": True},
            }
        ],
        candidate_blocks=[
            {
                "block_id": "b1",
                "translated_text": "屋面系统",
                "merge_decision": "single",
                "rotation": 0,
                "target_bbox": [100, 12, 118, 30],
                "font_size": 5,
                "leader": {
                    "status": "drawn",
                    "color": "blue",
                    "width_points": 0.5,
                    "arrow": True,
                    "route": "diagonal",
                },
            }
        ],
        visual_qa={
            "visual_overlap_count": 0,
            "leader_collision_count": 0,
            "untranslated_candidate_count": 0,
        },
        pdf_diagnostics={},
        subjective={"page_readability": 15, "layout_association": 20},
    )
    codes = {item["code"] for item in result["hard_failures"]}
    assert {"forbidden_zone_overlap", "leader_style"}.issubset(codes)
```

- [ ] **Step 5: Run tests and commit**

Run:

```powershell
cd backend/scripts
python -m pytest devtools/tests/engineering_drawing/test_benchmark_scoring.py -q
```

Expected: all scoring tests pass.

Commit:

```powershell
git add backend/scripts/services/engineering_drawing/benchmark/scoring.py backend/scripts/devtools/tests/engineering_drawing/test_benchmark_scoring.py
git commit -m "feat: score engineering drawing benchmark"
```

## Task 6: Visual Diff and Reader-Facing Benchmark Report

**Files:**

- Create: `backend/scripts/services/engineering_drawing/benchmark/report.py`
- Create: `backend/scripts/devtools/tests/engineering_drawing/test_benchmark_report.py`

**Interfaces:**

- Produces: `render_comparison(source_pdf: Path, candidate_pdf: Path, output_png: Path, markers: list[dict], dpi: int = 120) -> Path`
- Produces: `write_benchmark_report(summary: dict, workspace: Path) -> tuple[Path, Path]`

- [ ] **Step 1: Write failing report test**

```python
from pathlib import Path

import fitz
from PIL import Image

from services.engineering_drawing.benchmark.report import (
    render_comparison,
    write_benchmark_report,
)


def _pdf(path: Path, text: str):
    document = fitz.open()
    page = document.new_page(width=200, height=120)
    page.insert_text((10, 20), text)
    document.save(path)
    document.close()


def test_report_writes_side_by_side_png_json_and_html(tmp_path: Path):
    source = tmp_path / "source.pdf"
    candidate = tmp_path / "candidate.pdf"
    _pdf(source, "ROOF SYSTEM")
    _pdf(candidate, "ROOF SYSTEM")
    image = render_comparison(
        source,
        candidate,
        tmp_path / "comparison.png",
        [{"side": "candidate", "bbox": [10, 10, 80, 30], "code": "missing_translation"}],
        dpi=72,
    )
    with Image.open(image) as opened:
        assert opened.width == 400
    json_path, html_path = write_benchmark_report(
        {"schema": "engineering-drawing-benchmark-report-v1", "samples": [], "core_score": 0},
        tmp_path,
    )
    assert json_path.exists()
    assert "Engineering Drawing Benchmark" in html_path.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
cd backend/scripts
python -m pytest devtools/tests/engineering_drawing/test_benchmark_report.py -q
```

Expected: import fails because `benchmark.report` does not exist.

- [ ] **Step 3: Implement comparison rendering and escaped HTML**

```python
from __future__ import annotations

import html
import json
from pathlib import Path

import fitz
from PIL import Image, ImageDraw


def _page_image(path: Path, dpi: int) -> Image.Image:
    with fitz.open(path) as document:
        pixmap = document[0].get_pixmap(dpi=dpi, alpha=False)
        return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)


def render_comparison(
    source_pdf: Path,
    candidate_pdf: Path,
    output_png: Path,
    markers: list[dict],
    dpi: int = 120,
) -> Path:
    source = _page_image(source_pdf, dpi)
    candidate = _page_image(candidate_pdf, dpi)
    scale = dpi / 72
    draw = ImageDraw.Draw(candidate)
    for marker in markers:
        if marker.get("side", "candidate") != "candidate":
            continue
        x0, y0, x1, y1 = (float(value) * scale for value in marker["bbox"])
        draw.rectangle((x0, y0, x1, y1), outline=(220, 30, 30), width=max(2, round(scale)))
        draw.text((x0, max(0, y0 - 12)), str(marker["code"]), fill=(220, 30, 30))
    canvas = Image.new(
        "RGB",
        (source.width + candidate.width, max(source.height, candidate.height)),
        "white",
    )
    canvas.paste(source, (0, 0))
    canvas.paste(candidate, (source.width, 0))
    output_png = Path(output_png)
    output_png.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_png, optimize=True)
    return output_png


def write_benchmark_report(summary: dict, workspace: Path) -> tuple[Path, Path]:
    workspace = Path(workspace)
    reports = workspace / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    json_path = reports / "benchmark-report.json"
    html_path = reports / "benchmark-report.html"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(item.get('sample_id', '')))}</td>"
        f"<td>{html.escape(str(item.get('category', '')))}</td>"
        f"<td>{float(item.get('score', 0)):.1f}</td>"
        f"<td>{int(item.get('hard_failure_count', 0))}</td>"
        f"<td><a href='../{html.escape(str(item.get('comparison_png', '')))}'>查看</a></td>"
        "</tr>"
        for item in summary.get("samples", [])
    )
    html_path.write_text(
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
        "<title>Engineering Drawing Benchmark</title>"
        "<style>body{font-family:Arial,\"Microsoft YaHei\",sans-serif;margin:24px}"
        "table{border-collapse:collapse;width:100%}th,td{border:1px solid #ccc;padding:6px}</style>"
        "</head><body><h1>Engineering Drawing Benchmark</h1>"
        f"<p>Core score: {float(summary.get('core_score', 0)):.1f}</p>"
        "<table><thead><tr><th>样本</th><th>类别</th><th>得分</th><th>硬失败</th><th>对比</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></body></html>",
        encoding="utf-8",
    )
    return json_path, html_path
```

- [ ] **Step 4: Run tests and commit**

Run:

```powershell
cd backend/scripts
python -m pytest devtools/tests/engineering_drawing/test_benchmark_report.py -q
```

Expected: `1 passed`.

Commit:

```powershell
git add backend/scripts/services/engineering_drawing/benchmark/report.py backend/scripts/devtools/tests/engineering_drawing/test_benchmark_report.py
git commit -m "feat: render engineering benchmark reports"
```

## Task 7: Benchmark Runner, CLI, and Single-Sample End-to-End Exercise

**Files:**

- Create: `backend/scripts/services/engineering_drawing/benchmark/runner.py`
- Create: `backend/scripts/devtools/tests/engineering_drawing/test_benchmark_runner.py`
- Modify: `backend/scripts/services/engineering_drawing/cli.py:29-90,93-220`
- Modify: `backend/scripts/services/engineering_drawing/README.md`

**Interfaces:**

- Produces CLI commands: `benchmark-seed`, `benchmark-prelabel`, `benchmark-adjudicate`, `benchmark-visual-review`, `benchmark-evaluate`
- Produces: `evaluate_workspace(workspace: Path, candidate_root: Path, baseline_report: Path | None = None) -> dict`
- The end-to-end exercise targets only `core-03`; it does not call `run_batch`.

- [ ] **Step 1: Write failing CLI safety and end-to-end tests**

```python
import json
from pathlib import Path

import fitz

import services.engineering_drawing.cli as engineering_cli
from services.engineering_drawing.benchmark.schema import CoreManifest, CoreSample
from services.engineering_drawing.benchmark.runner import evaluate_workspace
from services.engineering_drawing.cli import main


def _one_page(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    document.new_page(width=300, height=200).insert_text((20, 30), text)
    document.save(path)
    document.close()


def test_benchmark_seed_never_creates_production_translated_pdf(tmp_path: Path, monkeypatch):
    source = tmp_path / "malasia/A3 DETAIL DRAWING/10_REV. JULAI 2025 ROOF DETAIL.pdf"
    _one_page(source, "ROOF SYSTEM")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "engineering-drawing-core-set-v1",
                "benchmark_version": "test-v1",
                "samples": [
                    {
                        "sample_id": "core-03",
                        "category": "roof_detail",
                        "relative_pdf": "A3 DETAIL DRAWING/10_REV. JULAI 2025 ROOF DETAIL.pdf",
                        "page_number": 1,
                        "goals": ["semantic_block"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    workspace = tmp_path / "output/pdf/engineering-drawing/benchmark"
    monkeypatch.setattr(
        engineering_cli,
        "load_core_manifest",
        lambda _path: CoreManifest(
            schema="engineering-drawing-core-set-v1",
            benchmark_version="test-v1",
            samples=(
                CoreSample(
                    "core-03",
                    "roof_detail",
                    "A3 DETAIL DRAWING/10_REV. JULAI 2025 ROOF DETAIL.pdf",
                    1,
                    ("semantic_block",),
                ),
            ),
        ),
    )
    monkeypatch.setattr(
        engineering_cli,
        "load_challenge_manifest",
        lambda _path: CoreManifest(
            schema="engineering-drawing-challenge-set-v1",
            benchmark_version="challenge-test-v1",
            samples=(),
            set_name="challenge",
        ),
    )
    assert main(
        [
            "benchmark-seed",
            "--source-root",
            str(tmp_path / "malasia"),
            "--workspace",
            str(workspace),
            "--manifest",
            str(manifest),
        ]
    ) == 0
    assert (workspace / "samples/core-03/source.pdf").exists()
    assert not list((tmp_path / "output").rglob("translated/*.pdf"))


def test_single_sample_locked_gold_to_report_flow(tmp_path: Path):
    workspace = tmp_path / "benchmark"
    sample_dir = workspace / "samples/core-03"
    candidate_root = tmp_path / "candidate"
    sample_dir.mkdir(parents=True)
    candidate_root.mkdir()
    _one_page(sample_dir / "source.pdf", "ROOF SYSTEM")
    _one_page(candidate_root / "core-03.pdf", "ROOF SYSTEM")
    (workspace / "manifest.lock.json").write_text(
        json.dumps(
            {
                "samples": [
                    {
                        "sample_id": "core-03",
                        "set_name": "core",
                        "category": "roof_detail",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (sample_dir / "gold.locked.json").write_text(
        json.dumps(
            {
                "blocks": [
                    {
                        "block_id": "core-03-b001",
                        "source_bbox": [20, 18, 100, 35],
                        "gold_translation": "屋面系统",
                        "literal_tokens": [],
                        "merge_decision": "single",
                        "rotation": 0,
                        "allowed_regions": [[120, 10, 220, 45]],
                        "forbidden_zones": [[20, 18, 100, 35]],
                        "font_size_range": [3.2, 6.5],
                        "leader": {"allowed": False, "required": False},
                        "manual_review_required": False,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (candidate_root / "core-03.regions.json").write_text(
        json.dumps(
            {
                "regions": [
                    {
                        "block_id": "core-03-b001",
                        "translated_text": "屋面系统",
                        "merge_decision": "single",
                        "rotation": 0,
                        "target_bbox": [120, 10, 180, 30],
                        "font_size": 5,
                        "leader": {"status": "not_needed"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (candidate_root / "core-03.inline-placement.json").write_text(
        json.dumps(
            {
                "placements": [
                    {
                        "region_id": "core-03-b001",
                        "page_index": 0,
                        "source_bbox": [20, 18, 100, 35],
                        "target_bbox": [120, 10, 180, 30],
                        "translated_text": "屋面系统",
                        "status": "inline_near",
                        "coverage_status": "translated",
                        "leader": {"status": "not_needed", "path": []},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (candidate_root / "core-03.subjective.json").write_text(
        json.dumps(
            {
                "schema": "engineering-drawing-visual-review-v1",
                "layout_association": 20,
                "page_readability": 15,
                "findings": [],
            }
        ),
        encoding="utf-8",
    )

    result = evaluate_workspace(workspace, candidate_root)

    assert result["hard_failure_count"] == 0
    assert result["core_score"] == 100
    assert (workspace / "reports/benchmark-report.html").exists()
```

- [ ] **Step 2: Run test and verify parser failure**

Run:

```powershell
cd backend/scripts
python -m pytest devtools/tests/engineering_drawing/test_benchmark_runner.py -q
```

Expected: argparse exits because `benchmark-seed` is not a registered command.

- [ ] **Step 3: Implement runner orchestration**

```python
from __future__ import annotations

import json
from pathlib import Path

from .report import render_comparison, write_benchmark_report
from .scoring import promotion_decision, score_sample
from services.engineering_drawing.visual_qa import analyze_visual_qa


def _read(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def evaluate_workspace(
    workspace: Path,
    candidate_root: Path,
    baseline_report: Path | None = None,
) -> dict:
    workspace = Path(workspace)
    candidate_root = Path(candidate_root)
    lock = _read(workspace / "manifest.lock.json")
    samples = []
    for record in lock["samples"]:
        sample_id = record["sample_id"]
        sample_dir = workspace / "samples" / sample_id
        gold = _read(sample_dir / "gold.locked.json")
        candidate_pdf = candidate_root / f"{sample_id}.pdf"
        candidate_regions = _read(candidate_root / f"{sample_id}.regions.json")["regions"]
        placement_path = candidate_root / f"{sample_id}.inline-placement.json"
        visual = analyze_visual_qa(
            output_pdf_path=candidate_pdf,
            placement_audit_path=placement_path,
        )
        with __import__("fitz").open(candidate_pdf) as document, __import__("fitz").open(
            sample_dir / "source.pdf"
        ) as source_document:
            text = "\n".join(page.get_text() for page in document)
            geometry_equal = (
                document.page_count == source_document.page_count
                and all(
                    abs(document[index].rect.width - source_document[index].rect.width) <= 0.5
                    and abs(document[index].rect.height - source_document[index].rect.height) <= 0.5
                    for index in range(source_document.page_count)
                )
            )
        diagnostics = {
            "replacement_characters": text.count("\ufffd"),
            "private_use_characters": sum("\ue000" <= char <= "\uf8ff" for char in text),
            "clipped_or_outside_count": (0 if geometry_equal else 1) + sum(
                str(item.get("status", "")).startswith("rejected")
                for item in _read(placement_path).get("placements", [])
            ),
        }
        subjective_path = candidate_root / f"{sample_id}.subjective.json"
        if not subjective_path.exists():
            raise FileNotFoundError(
                f"multimodal visual review is missing for {sample_id}: {subjective_path}"
            )
        subjective = _read(subjective_path)
        scored = score_sample(
            gold_blocks=gold["blocks"],
            candidate_blocks=candidate_regions,
            visual_qa=visual,
            pdf_diagnostics=diagnostics,
            subjective=subjective,
        )
        comparison = render_comparison(
            sample_dir / "source.pdf",
            candidate_pdf,
            workspace / "comparisons" / f"{sample_id}.png",
            [
                {
                    "side": "candidate",
                    "bbox": next(
                        (
                            block["source_bbox"]
                            for block in gold["blocks"]
                            if block["block_id"] == failure.get("block_id")
                        ),
                        [0, 0, 1, 1],
                    ),
                    "code": failure["code"],
                }
                for failure in scored["hard_failures"]
            ],
        )
        samples.append(
            {
                "sample_id": sample_id,
                "set_name": record["set_name"],
                "category": record["category"],
                "comparison_png": str(comparison.relative_to(workspace)).replace("\\", "/"),
                **scored,
            }
        )
    core_items = [item for item in samples if item["set_name"] == "core"]
    challenge_items = [item for item in samples if item["set_name"] == "challenge"]
    all_gold_blocks = [
        block
        for record in lock["samples"]
        for block in _read(
            workspace / "samples" / record["sample_id"] / "gold.locked.json"
        )["blocks"]
    ]
    summary = {
        "schema": "engineering-drawing-benchmark-report-v1",
        "samples": samples,
        "core_score": sum(item["score"] for item in core_items) / max(1, len(core_items)),
        "hard_failure_count": sum(item["hard_failure_count"] for item in samples),
        "manual_review_rate": sum(
            bool(block.get("manual_review_required")) for block in all_gold_blocks
        ) / max(1, len(all_gold_blocks)),
        "automation_rate": sum(
            not bool(block.get("manual_review_required")) for block in all_gold_blocks
        ) / max(1, len(all_gold_blocks)),
        "category_scores": {
            category: sum(item["score"] for item in core_items if item["category"] == category)
            / sum(1 for item in core_items if item["category"] == category)
            for category in {item["category"] for item in core_items}
        },
        "challenge_pass_rate": (
            sum(bool(item["passed"]) for item in challenge_items) / len(challenge_items)
            if challenge_items
            else 1.0
        ),
        "challenge_sample_count": len(challenge_items),
    }
    if baseline_report is not None:
        summary["promotion"] = promotion_decision(_read(baseline_report), summary)
    write_benchmark_report(summary, workspace)
    return summary
```

- [ ] **Step 4: Add the four CLI parsers and dispatch branches**

Add imports in `cli.py`:

```python
from .benchmark.adjudication import apply_adjudication, lock_gold
from .benchmark.prelabel import (
    request_prelabels,
    request_visual_review,
    select_adjudication_queue,
)
from .benchmark.runner import evaluate_workspace
from .benchmark.schema import load_challenge_manifest, load_core_manifest
from .benchmark.workspace import seed_workspace
from services.translation.llm.shared.provider_runtime import get_api_key
from services.translation.llm.shared.provider_runtime import request_chat_content
```

Add parsers in `_parser()`:

```python
    benchmark_seed = subparsers.add_parser("benchmark-seed")
    benchmark_seed.add_argument("--source-root", required=True, type=Path)
    benchmark_seed.add_argument("--workspace", required=True, type=Path)
    benchmark_seed.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).with_name("benchmark") / "core-set.v1.json",
    )
    benchmark_seed.add_argument(
        "--challenge-manifest",
        type=Path,
        default=Path(__file__).with_name("benchmark") / "challenge-set.v1.json",
    )
    benchmark_seed.add_argument("--dpi", type=int, default=144)

    benchmark_prelabel = subparsers.add_parser("benchmark-prelabel")
    benchmark_prelabel.add_argument("--workspace", required=True, type=Path)
    benchmark_prelabel.add_argument("--sample-id", required=True)
    benchmark_prelabel.add_argument("--regions-json", required=True, type=Path)
    benchmark_prelabel.add_argument("--model", default="gpt-5.6-sol")
    benchmark_prelabel.add_argument("--base-url", default=DEFAULT_BASE_URL)

    benchmark_adjudicate = subparsers.add_parser("benchmark-adjudicate")
    benchmark_adjudicate.add_argument("--workspace", required=True, type=Path)
    benchmark_adjudicate.add_argument("--sample-id", required=True)
    benchmark_adjudicate.add_argument("--decisions", required=True, type=Path)
    benchmark_adjudicate.add_argument("--actor", default="user")
    benchmark_adjudicate.add_argument("--decided-at", required=True)
    benchmark_adjudicate.add_argument("--lock", action="store_true")

    benchmark_visual = subparsers.add_parser("benchmark-visual-review")
    benchmark_visual.add_argument("--workspace", required=True, type=Path)
    benchmark_visual.add_argument("--candidate-root", required=True, type=Path)
    benchmark_visual.add_argument("--sample-id", required=True)
    benchmark_visual.add_argument("--model", default="gpt-5.6-sol")
    benchmark_visual.add_argument("--base-url", default=DEFAULT_BASE_URL)

    benchmark_evaluate = subparsers.add_parser("benchmark-evaluate")
    benchmark_evaluate.add_argument("--workspace", required=True, type=Path)
    benchmark_evaluate.add_argument("--candidate-root", required=True, type=Path)
    benchmark_evaluate.add_argument("--baseline-report", type=Path)
```

Add dispatch before the existing `samples` branch:

```python
    if args.command == "benchmark-seed":
        result = seed_workspace(
            args.source_root,
            args.workspace,
            load_core_manifest(args.manifest),
            dpi=args.dpi,
            challenge_manifest=load_challenge_manifest(args.challenge_manifest),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "benchmark-prelabel":
        import base64

        sample_dir = args.workspace / "samples" / args.sample_id
        image_data_url = "data:image/png;base64," + base64.b64encode(
            (sample_dir / "source.png").read_bytes()
        ).decode("ascii")
        regions = json.loads(args.regions_json.read_text(encoding="utf-8"))["regions"]
        sample_record = json.loads(
            (sample_dir / "sample.json").read_text(encoding="utf-8")
        )
        result = request_prelabels(
            sample_id=args.sample_id,
            image_data_url=image_data_url,
            regions=regions,
            page={
                "width": sample_record["page_size"][0],
                "height": sample_record["page_size"][1],
                "rotation": 0,
            },
            api_key=get_api_key(),
            model=args.model,
            base_url=args.base_url,
            request_fn=request_chat_content,
        )
        (sample_dir / "prelabel.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (sample_dir / "adjudication-queue.json").write_text(
            json.dumps(
                {"items": select_adjudication_queue(result)},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return 0
    if args.command == "benchmark-adjudicate":
        sample_dir = args.workspace / "samples" / args.sample_id
        prelabel = json.loads((sample_dir / "prelabel.json").read_text(encoding="utf-8"))
        decisions = json.loads(args.decisions.read_text(encoding="utf-8"))["decisions"]
        gold = apply_adjudication(prelabel, decisions, args.actor, args.decided_at)
        if args.lock:
            gold = lock_gold(gold, args.actor, args.decided_at)
        output_name = "gold.locked.json" if gold.status == "locked" else "gold.adjudicated.json"
        (sample_dir / output_name).write_text(
            json.dumps(gold.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return 0
    if args.command == "benchmark-visual-review":
        import base64
        import fitz

        sample_dir = args.workspace / "samples" / args.sample_id
        source_url = "data:image/png;base64," + base64.b64encode(
            (sample_dir / "source.png").read_bytes()
        ).decode("ascii")
        candidate_pdf = args.candidate_root / f"{args.sample_id}.pdf"
        with fitz.open(candidate_pdf) as document:
            candidate_png = document[0].get_pixmap(dpi=144, alpha=False).tobytes("png")
        candidate_url = "data:image/png;base64," + base64.b64encode(
            candidate_png
        ).decode("ascii")
        result = request_visual_review(
            sample_id=args.sample_id,
            source_image_data_url=source_url,
            candidate_image_data_url=candidate_url,
            api_key=get_api_key(),
            model=args.model,
            base_url=args.base_url,
            request_fn=request_chat_content,
        )
        (args.candidate_root / f"{args.sample_id}.subjective.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return 0
    if args.command == "benchmark-evaluate":
        result = evaluate_workspace(
            args.workspace,
            args.candidate_root,
            args.baseline_report,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["hard_failure_count"] == 0 else 2
```

- [ ] **Step 5: Run the targeted test and the full engineering suite**

Run:

```powershell
cd backend/scripts
python -m pytest devtools/tests/engineering_drawing/test_benchmark_runner.py -q
python -m pytest devtools/tests/engineering_drawing -q
```

Expected: both runner tests pass; all engineering-drawing tests pass with no regression.

- [ ] **Step 6: Exercise only core-03 with real source data**

Run:

```powershell
cd backend/scripts
python -m services.engineering_drawing benchmark-seed `
  --source-root "D:\AmyProjects\business\WROK-CONTENT\malasia" `
  --workspace "D:\AmyProjects\business\pdf-manager\output\pdf\engineering-drawing\benchmark"
```

Expected:

- `output/pdf/engineering-drawing/benchmark/manifest.lock.json` reports 12 samples.
- `output/pdf/engineering-drawing/benchmark/samples/core-03/source.pdf` and `source.png` exist.
- No new PDF exists under `output/pdf/engineering-drawing/01_Bilingual_Inline/translated`.

Then run OCR only for the frozen `core-03` page:

```powershell
python -m services.engineering_drawing ocr `
  --pdf "D:\AmyProjects\business\pdf-manager\output\pdf\engineering-drawing\benchmark\samples\core-03\source.pdf" `
  --output "D:\AmyProjects\business\pdf-manager\output\pdf\engineering-drawing\benchmark\samples\core-03\regions.json" `
  --cache-dir "D:\AmyProjects\business\pdf-manager\output\pdf\engineering-drawing\benchmark\cache\core-03" `
  --start-page 1 `
  --end-page 1
```

Expected: `core-03/regions.json` exists and contains page-1 source regions. Stop before `benchmark-prelabel` if no approved model budget is available; the seed and OCR artifacts remain resumable.

- [ ] **Step 7: Document commands, safety boundary, and artifact lifecycle**

Append to `README.md`:

```markdown
## Benchmark workflow

The benchmark is separate from production translation. Its default workspace is
`output/pdf/engineering-drawing/benchmark`; it never writes delivery PDFs to
`01_Bilingual_Inline/translated`.

Lifecycle:

1. `benchmark-seed` freezes the approved 12 source pages and hashes.
2. `benchmark-prelabel` asks the Sol multimodal model for semantic blocks,
   translations, layout constraints, and uncertainty flags.
3. A reviewer edits only `adjudication-queue.json` disputes and records reasons.
4. `benchmark-adjudicate --lock` creates an audited `gold.locked.json`.
5. `benchmark-visual-review` records the Sol model, prompt version, page-layout
   score, readability score, and auditable findings for each candidate page.
6. `benchmark-evaluate` applies hard gates, weighted scoring, visual comparisons,
   and version-promotion rules.

Never run `batch-translate` as part of benchmark construction or annotation.
```

- [ ] **Step 8: Commit the runner and documentation**

```powershell
git add backend/scripts/services/engineering_drawing/benchmark/runner.py backend/scripts/devtools/tests/engineering_drawing/test_benchmark_runner.py backend/scripts/services/engineering_drawing/cli.py backend/scripts/services/engineering_drawing/README.md
git commit -m "feat: add engineering benchmark workflow"
```

## Task 8: Final Verification and Traceability Check

**Files:**

- Verify: `docs/superpowers/specs/2026-07-28-engineering-drawing-benchmark-design.md`
- Verify: all files created or modified by Tasks 1–7

**Interfaces:**

- Consumes all prior task outputs.
- Produces a clean test result and a traceability checklist; no production PDF mutation.

- [ ] **Step 1: Run formatting and placeholder scans**

Run:

```powershell
rg -n "[T]ODO|[T]BD|[F]IXME|[P]LACEHOLDER|implement[ ]later|fill[ ]in" backend/scripts/services/engineering_drawing/benchmark backend/scripts/devtools/tests/engineering_drawing/test_benchmark_*.py
git diff --check
```

Expected: `rg` returns no matches and `git diff --check` returns no errors.

- [ ] **Step 2: Run the complete targeted suite**

Run:

```powershell
cd backend/scripts
python -m pytest devtools/tests/engineering_drawing -q
```

Expected: every engineering-drawing test passes.

- [ ] **Step 3: Verify core paths and production isolation**

Run:

```powershell
$lock = Get-Content "D:\AmyProjects\business\pdf-manager\output\pdf\engineering-drawing\benchmark\manifest.lock.json" -Raw | ConvertFrom-Json
if ($lock.sample_count -ne 12) { throw "Expected 12 frozen samples" }
$missing = $lock.samples | Where-Object {
  -not (Test-Path -LiteralPath ("D:\AmyProjects\business\pdf-manager\output\pdf\engineering-drawing\benchmark\samples\" + $_.sample_id + "\source.pdf"))
}
if ($missing) { throw "Frozen sample PDFs are missing" }
Write-Output "12 core samples verified; benchmark workspace is separate from production translated directory."
```

Expected: the verification message is printed and no files are copied to the production translated directory.

- [ ] **Step 4: Review implementation against every design requirement**

Record these exact checks in the implementation handoff:

```text
Core set: 12 fixed page-1 samples with source/page/preview hashes.
Gold lifecycle: candidate -> prelabeled -> adjudicated -> locked, with append-only audit.
Semantic grouping: paragraphs merge; equipment IDs, table cells, legends, dimensions, and title rows stay separate.
Layout gold: allowed regions, forbidden zones, font range, rotation, and leader rules.
Hard gates: missing, garbled, overlap, clipping/outside, literal change, wrong grouping, leader collision.
Scores: 30 semantic + 20 coverage + 15 grouping + 20 layout + 15 readability.
Promotion: no new hard failures; +1 core score or equal with lower review rate; category drop <=3; challenge non-decreasing.
Outputs: JSON, HTML, side-by-side PNG, audit history, and manual-review queue.
Safety: no batch translation and no benchmark assets in the production translated directory.
```

- [ ] **Step 5: Commit any verification-only documentation correction**

If Step 4 finds a documentation mismatch, correct only that mismatch, rerun Steps 1–3, then commit the exact documentation file:

```powershell
git add backend/scripts/services/engineering_drawing/README.md
git commit -m "docs: align engineering benchmark workflow"
```

If no mismatch exists, do not create an empty commit.
