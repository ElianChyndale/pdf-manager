# Production Source of Truth — engineering drawing delivery

> This document is the single authoritative reference for the delivery-160
> production workflow. **Historical files must not be used for production
> execution.** Anything not listed here is reference-only or archived.

## The only official production references

| Reference | Value / Path | Purpose |
|-----------|--------------|---------|
| Branch | `release/engineering-delivery-160` | The release branch that carries the frozen delivery code. |
| Tag | `delivery-160-rc2` | The production freeze tag (peels to `bdcb596a`). |
| **Freeze config** | `frozen-production-config.json` (repo root) | The immutable record of code commit, policy fingerprint, prompts, fonts, OCR/model identifiers, glossary/TM hashes, cache schemas, dependency versions, and the 662-test verification. Pins the production **code** hash `fde70aa2`; the rc2 hotfix is additive tooling and does not change translation logic. |
| **Delivery manifest** | `delivery-160.json` (private dir, e.g. `D:\AmyProjects\business\delivery-160\`) | Per-item production inputs: anonymous stable `item_id`, `source_pdf`, output naming, `document_context`, `content_hash`. Never committed to the repo. |
| **Runtime validation** | `delivery-run preflight --production-runtime` | Verifies the execution environment (paddleocr, deepseek runner, translation provider, pymupdf, pinned deps, CJK font). Must be green before canary. |
| **Dry-run gate** | `delivery-run validate-production` | Read-only flight checklist (manifest, first-5 PDFs, context hash, glossary/TM, output naming, freeze config + policy fingerprint). No OCR/LLM/render. |
| **Workflow version** | `v4.0-readable-zone-complete` (`workflow_policy.WORKFLOW_VERSION`) | The only valid production workflow version; V2/V3.x semantics are void. |
| **Supervisor** | `gpt-5.6-sol` / `light` (`codex-sol-light`) | The single multimodal supervisor; parallel multimodal agents are forbidden. |
| **Translation model** | `deepseek-v4-flash` | The production translation model. |
| **OCR models** | `PP-OCRv5_server_det` / `PP-OCRv5_server_rec` | The production OCR models. |

## The official delivery workflow

```text
frozen-production-config.json
  → delivery-run validate-production        (dry-run, no OCR/LLM/render)
  → delivery-run preflight --production-runtime   (verify the production env)
  → delivery-run start --phase canary        → review → repair → pilot → production
  → review queue / revision runs
  → final publication into v4.0-readable-zone-complete
```

CLI is driven from `backend/scripts`:
`python -m services.engineering_drawing.cli <subcommand>`.

`delivery-run` commands use the **subcommand-first** form:
`delivery-run preflight --manifest ... --source-root ... --output-root ...`.
(Argument-before-subcommand does not parse.)

## Historical files — NOT for production execution

The following are reference/archive only and must never be used for production
execution:

- `backend/scripts/devtools/` one-off scripts (v3.x and v4 sample/publish/build
  scripts) — each carries a `DEPRECATED` banner.
- `backend/scripts/services/engineering_drawing/harness.py` — deprecated V3.x
  full-coverage gate; the V4 release authority is `run_v4` + `authorize_release`.
- `batch.py` / `agent_batch.py` legacy batch runners — retained for audit only.
- `docs/superpowers/` design/plan documents predating the V4 freeze.
- Output dirs `01_报审图纸/`, `02_清真寺施工图纸/` — historical V2/V3 evidence
  only.
- `pyproject.toml` dependency pins — stale relative to the frozen runtime set;
  production installs the frozen dependency versions.

## Invariants (never break)

1. **No renderer self-authorization** — a PDF enters `v4.0-readable-zone-complete`
   only through `run_v4.publish_to_formal` with an `authorize_release` /
   `authorize_human_release` authorization.
2. Single supervisor `gpt-5.6-sol` / light; closures = 1.0; one render mode per
   block; directory mask clearance ≥ 1.5pt with zero protected-column
   intersection.
3. **Revision runs are immutable** — human decisions create `run-001-r1`; never
   mutate the original run. `keep_literal` → `human_exception_keep_source`
   (never `literal_only`).
4. Production inputs live in a **private** directory, never in this repo.
5. The freeze config, delivery manifest, and runtime environment are the only
   production sources of truth; everything else references them or is archived.
