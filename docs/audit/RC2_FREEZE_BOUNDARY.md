# RC2 Freeze Boundary — delivery-160

> This document explains exactly what `delivery-160-rc2` freezes, which commit
> hashes validate what, and why the rc2 hotfix does not alter translation or
> scoring behavior. It exists so a future operator/agent never mistakes the rc2
> hotfix commit for a change to the frozen translation engine.

## The two relevant commits

| Commit | Full SHA | Role |
|--------|----------|------|
| **Translation engine freeze** | `fde70aa20d26b4a864d81b5012611005a1bb0df8` (`fde70aa2`) | The frozen **translation engine** — the V4 five-stage workflow, `run_v4`, `workflow_policy` (`v4.0-readable-zone-complete`), supervisor `gpt-5.6-sol`/light, translation `deepseek-v4-flash`, OCR `PP-OCRv5_server_det/rec`, closures=1.0, no-renderer-self-authorization, revision-run immutability. This is the code that produces the bilingual PDFs. |
| **Delivery orchestration hotfix** | `bdcb596a04e77fce599a0734ad1a73c33461776e` (`bdcb596a`) | The **delivery orchestration hotfix** on top of rc1 — preflight glossary-dir resolution, `--production-runtime`, `validate-production`, `delivery-report`, `duplicate-map`, `dashboard`, and CLI arg-parsing fixes. These are **tooling around** the delivery pipeline; they do not touch translation/scoring/rendering logic. |

Tags:
- `delivery-160-rc1` peels to `61e48590` (freeze config committed on top of `fde70aa2`).
- `delivery-160-rc2` peels to `bdcb596a` (the hotfix commit).

## Why rc2 does not modify translation/scoring behavior

`bdcb596a` changes only:

1. `backend/scripts/services/engineering_drawing/preflight.py` — glossary-dir
   resolution + `--production-runtime` checks.
2. `backend/scripts/services/engineering_drawing/cli.py` — `delivery-run`
   subcommand arg parsing + new subcommands (`validate-production`,
   `delivery-report`, `duplicate-map`, `dashboard`).
3. `backend/scripts/services/engineering_drawing/delivery_run.py` —
   `build_delivery_report`, `build_duplicate_map` (delivery-clarity, not
   translation).
4. `backend/scripts/services/engineering_drawing/validate_production.py`,
   `delivery_dashboard.py` — new read-only tooling.
5. `backend/scripts/services/engineering_drawing/overlay_pair.py` — 2 lines:
   portable-font completion (`resolve_cjk_font()`), **fixes** the render path on
   Linux/Docker; it does not change translation, scoring, or layout logic.
6. Tests: `test_delivery_preflight_hotfix.py` (6 new).

It does **not** modify: `workflow_policy.py`, `orchestration_harness.py`,
`supervisor_contract.py`, `authorization.py`, scoring mathematics, the V4
five-stage state machine, or `frozen-production-config.json`.

## Which hash validates what

| Artifact | Validating hash | What it proves |
|----------|-----------------|----------------|
| `frozen-production-config.json` | `policy_fingerprint` (`a6a3f107…`), `git_commit` = `fde70aa2`, `verification.full_suite_passed` = 662 | The **translation engine code identity** and its policy/typography/model/glossary/font snapshot. Recomputes against `workflow_policy.canonical_policy_fingerprint()`. |
| `delivery-160.json` (delivery manifest) | `policy_fingerprint` + `document_context_template_hash` (`e151dabf…`) | The delivery input set (anonymous item ids, sources, output naming). Must match the frozen policy fingerprint. |
| `delivery-run validate-production` | recomputes source PDF hashes, glossary/TM hashes vs `glossary-tm-lock.json`, template hash, output-name uniqueness, freeze `policy_fingerprint` match | The dry-run flight checklist — proves the delivery is internally consistent **before** any OCR/LLM/render. |
| `delivery-run preflight --production-runtime` | runtime_* checks (paddleocr, deepseek runner, translation provider, pymupdf, pinned deps, CJK font) | The execution **environment** matches what the frozen dependency set expects. |
| rc2 tag `delivery-160-rc2` | peels to `bdcb596a` | The full production-ready code set = translation engine (`fde70aa2`) + delivery hotfix (`bdcb596a`). |

**Net:** `fde70aa2` is what the translation engine is frozen on; `bdcb596a` adds
delivery tooling only. The 668-test verification (662 at rc1 + 6 hotfix tests)
applies to the rc2 working tree. `frozen-production-config.json` is **not**
regenerated for rc2 because its purpose is to pin the translation-engine code
identity (`fde70aa2`) and policy fingerprint, neither of which the hotfix
changes.

## Rule

> Never treat `bdcb596a` as a translation-engine change. If translation/scoring
> behavior must change, that requires a NEW freeze (`rc3+`) that regenerates
> `frozen-production-config.json`. The rc2 hotfix is delivery-tooling-only and
> must not be merged into a translation-engine release without re-freezing.
