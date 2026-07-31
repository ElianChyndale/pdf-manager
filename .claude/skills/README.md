# Project skills — engineering drawing V4

These skills let an agent drive the engineering-drawing bilingual workflow as
invokable units. Each is a thin wrapper over
`python -m services.engineering_drawing.cli <subcommand>` with clear
preconditions and "do not" guards.

| Skill | Purpose | Primary command |
|-------|---------|-----------------|
| `engineering-v4-run` | Run one source PDF through the 5-stage V4 flow and publish via authorization. | `v4-run` |
| `engineering-audit-formal` | Verify formal-dir release evidence (sidecars + delivery manifests). | `v4-run audit-formal` |
| `engineering-review-queue` | Risk-ranked HTML review sheet with crops. | `v4-run review-queue` |
| `engineering-benchmark-eval` | Held-out-aware benchmark evaluation. | `benchmark-split` / `benchmark-evaluate` |
| `engineering-batch-bootstrap` | Create supervisor page packets for a batch. | `agent-bootstrap` |

Full operating manual: `backend/scripts/services/engineering_drawing/AGENTS.md`.
Normative spec: `backend/scripts/services/engineering_drawing/WORKFLOW_SPEC_V4.md`.
