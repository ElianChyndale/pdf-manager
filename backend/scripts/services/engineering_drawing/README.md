# Engineering drawing bilingual production

Active workflow: `v4.0-readable-zone-complete`.

The sole normative specification is
`WORKFLOW_SPEC_V4.md` (formerly `WORKFLOW_SPEC_V2_BLOCK.md`; renamed to match
its actual V4.0 content).
Runtime constants are in `workflow_policy.py`; the supervisor receives
`engineering_drawing_supervisor_v37.txt` and
`rule_profile_engineering_drawing.txt`. These four sources must express the same
V4 semantics. Historical V2/V3 artifacts and output directories are evidence
only and must never be used as active production rules.

## Production contract

All stages use `orchestration_harness.py` as the executable handoff contract;
they do not independently reinterpret prose rules. Every artifact carries the
same source digest, V4 workflow version, policy fingerprint, stable source IDs,
zone assignments and per-block render mode.

The fixed state machine is:

1. `supervisor_plan`: Sol Light partitions the rendered page and chooses one
   immutable A/B render mode per translated block.
2. `extraction_ledger`: OCR/native/reference evidence fills the supervisor's
   stable IDs; it cannot invent zones or silently classify prose as literal.
3. `render_contract`: the executor receives complete blocks, typography and
   mask/placement evidence; it cannot merge, omit or change render mode.
4. `rendered_candidate`: whole-page, per-zone and visible-ink closure must all
   equal 1.0; hard findings block while soft findings remain non-blocking.
5. `release_authorization`: rendered-page review and explicit authorization are
   required. A candidate file alone is never a deliverable.

Each stage behaves like a coordinated skill with one purpose, one validated
input and one validated output. Handoff validation runs before the next stage,
so ambiguity cannot accumulate downstream.

The single multimodal supervisor is Codex `gpt-5.6-sol` with light reasoning.
It inspects the original page, partitions zones, binds every stable source
`line_id`, translates complete semantic blocks, designs readable typography and
positions, and reviews the rendered page. OCR and native PDF text are evidence;
the reference PDF supplies wording only. The original PDF is always the render
base.

Every release requires:

- whole-page and per-zone content closure of 1.0;
- planned-block to visible-CJK-ink closure of 1.0;
- directory rows rendered as readable black source plus Chinese;
- company cells rendered with complete bilingual information in actual non-logo
  whitespace;
- drawing-body source preserved with nearby complete blue Chinese;
- readable type at normal review scale and targeted 2x crops;
- immutable supervisor bundle, render authorization, final visual review and
  release authorization.

## Typography summary

- Directory: batch scale 1.20, preferred 7.2pt, hard minimum 6.8pt, 1.5–3.0pt
  cell padding, largest fitting type close to the corresponding table rules.
- Company cells: batch scale 1.18, preferred 6.8pt, hard minimum 6.4pt, measured
  independently per cell with logos and borders protected.
- Drawing body: preferred 6.4pt, hard minimum 5.8pt, at least 85% of the source
  visual size.

Use semantic wrapping and additional whitespace before reducing type. Missing,
microscopic, clipped, garbled or visibly absent translations block release.

## Main entry points

- `agent_system.py`: page packets, stable IDs and ledger closure.
- `orchestration_harness.py`: immutable stage identity and handoff validation.
- `multimodal_plan.py`: strict plan validation and executor handoff.
- `supervisor_contract.py` / `supervisor_bundle.py`: verified supervisor proof.
- `authorization.py`: non-bypassable render and release authorization.
- `overlay_pair.py` / `panel_reflow.py`: deterministic PDF execution.
- `visual_qa.py`: rendered-page diagnostics.

Dev scripts may create candidates, but no dev script may fabricate a final
review or copy a candidate into the production directory without authorization.
