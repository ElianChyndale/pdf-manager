---
name: engineering-audit-formal
description: Verify the formal v4.0-readable-zone-complete directory compliance: every PDF must have a release-authorization sidecar binding the candidate SHA-256, and (when present) a verified delivery manifest. Use when asked to check/audit released engineering drawing PDFs.
---

# engineering-audit-formal

## Purpose
Read-only compliance report over a formal release directory. Each PDF must have
a `.release-authorization.json` sidecar with schema
`engineering-drawing-release-authorization-v1` or
`engineering-drawing-human-release-authorization-v1` binding the candidate
SHA-256; a missing/unverifiable `.delivery-manifest.json` is advisory only.

## Exact command
```bash
cd backend/scripts
python -m services.engineering_drawing.cli v4-run audit-formal \
  --formal-dir "<...>/translated/v4.0-readable-zone-complete"
```

## Output
A JSON report: one entry per PDF with `ok`, `reasons`, `warnings`, and
`delivery_manifest_ok` when a manifest exists.

## Verification
- Exit code 0 always (read-only report).
- Inspect the report for `"ok": false` entries before trusting any PDF.

## Do NOT
- Do not treat a PDF without a verified sidecar as a deliverable.
- Do not modify the formal directory while auditing.
- Do not interpret a `missing_delivery_manifest` warning as a release failure
  (historical releases predate the delivery manifest).
