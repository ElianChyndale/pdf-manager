"""V4 release-authorization bypass enforcement.

A release sidecar (``*.release-authorization.json``) and any copy into the
formal ``v4.0-readable-zone-complete`` directory must be produced only by the
authorized surface: ``authorization.authorize_release`` /
``authorize_human_release`` and ``run_v4.publish_to_formal``.  A source audit
walks the production and devtools modules with AST so comments cannot
false-positive.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from services.engineering_drawing.run_v4 import audit_formal_dir
from services.engineering_drawing.workflow_policy import WORKFLOW_VERSION

BACKEND = Path(__file__).resolve().parents[4] / "scripts"
SERVICES = BACKEND / "services" / "engineering_drawing"
RENDERING = BACKEND / "services" / "rendering" / "output" / "engineering"
DEVTOOLS = BACKEND / "devtools"

RELEASE_SUFFIX = ".release-authorization.json"
FORMAL_MARKER = "v4.0-readable-zone-complete"


def _py_files(root: Path) -> list[Path]:
    return [
        path
        for path in sorted(root.rglob("*.py"))
        if "tests" not in path.parts and "__pycache__" not in path.parts
    ]


def _writes_release_sidecar(path: Path) -> bool:
    """True when a write/copy call appears near a release-sidecar reference.

    A file that merely hashes the sidecar (e.g. ``delivery_manifest.py`` hashing
    it with ``file_sha256``) is a reader, not a writer.  A writer is a file that
    has a ``write_text`` / ``write_bytes`` / ``copy`` / ``copy2`` call whose line
    is within a few lines of a reference to ``.release-authorization.json`` or
    the formal ``v4.0-readable-zone-complete`` marker.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False

    write_lines: list[int] = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        write_lines = []
    else:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {
                "write_text",
                "write_bytes",
                "copy",
                "copy2",
            }:
                write_lines.append(node.lineno)
    if not write_lines:
        return False
    for match in re.finditer(re.escape(RELEASE_SUFFIX) + r"|\b" + re.escape(FORMAL_MARKER), text):
        line_number = text.count("\n", 0, match.start()) + 1
        if any(abs(line_number - write_line) <= 6 for write_line in write_lines):
            return True
    return False


def _has_deprecated_banner(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return any(line.startswith("# DEPRECATED") for line in text.splitlines()[:6])


def _imports_authorized_release(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return "authorize_release" in text or "authorize_human_release" in text


def test_production_sidecar_writers_are_limited_to_run_v4() -> None:
    production_writers = [
        path.relative_to(BACKEND)
        for root in (SERVICES, RENDERING)
        for path in _py_files(root)
        if _writes_release_sidecar(path)
    ]
    # run_v4.py is the sole production writer of `.release-authorization.json`;
    # delivery_manifest.py only hashes the sidecar (read-only evidence binding).
    assert production_writers == [Path("services/engineering_drawing/run_v4.py")]


def test_every_devtools_sidecar_writer_is_banner_marked_or_authorized() -> None:
    unmarked: list[Path] = []
    for path in _py_files(DEVTOOLS):
        if not _writes_release_sidecar(path):
            continue
        if not (_has_deprecated_banner(path) or _imports_authorized_release(path)):
            unmarked.append(path.relative_to(BACKEND))
    assert not unmarked, f"devtools writers without banner or authorized import: {unmarked}"


def test_audit_formal_dir_flags_hand_rolled_sidecar(tmp_path: Path) -> None:
    formal = tmp_path / "formal"
    formal.mkdir()
    pdf = formal / "01_sample.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    # The exact hand-rolled shape used by the deprecated publish_v4_* scripts.
    hand_rolled = {
        "schema": "v4.0-release-authorization",
        "workflow_version": WORKFLOW_VERSION,
        "status": "authorized",
        "pdf": str(pdf),
        "pdf_sha256": "0" * 64,
        "supervisor": {"model": "gpt-5.6-sol", "reasoning_profile": "light"},
    }
    (formal / "01_sample.release-authorization.json").write_text(
        json.dumps(hand_rolled, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    reports = audit_formal_dir(formal)
    assert len(reports) == 1
    assert reports[0]["ok"] is False
    reasons = " ".join(reports[0]["reasons"])
    assert "unexpected_schema" in reasons
    assert "candidate_sha256_mismatch" in reasons


def test_audit_formal_dir_accepts_compliant_sidecar(tmp_path: Path) -> None:
    from hashlib import sha256

    from services.engineering_drawing.run_v4 import publish_to_formal

    formal = tmp_path / "formal"
    candidate = tmp_path / "candidate.pdf"
    candidate.write_bytes(b"%PDF-1.4 compliant")
    publish_to_formal(
        candidate=candidate,
        formal_dir=formal,
        auth={
            "schema": "engineering-drawing-human-release-authorization-v1",
            "workflow_version": WORKFLOW_VERSION,
            "authorization": "release",
            "authorization_kind": "human",
            "release_separate_from_renderer": True,
            "candidate_sha256": sha256(candidate.read_bytes()).hexdigest(),
        },
    )
    reports = audit_formal_dir(formal)
    assert len(reports) == 1
    assert reports[0]["ok"] is True
