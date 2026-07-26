from pathlib import Path

import fitz

from services.engineering_drawing.inventory import build_inventory
from services.engineering_drawing.legacy_audit import audit_inventory
from services.engineering_drawing.models import LegacyStatus
from services.engineering_drawing.reports import write_report_bundle


def _page_pdf(path: Path, lines: list[tuple[float, float, str]], width: int = 500) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    page = document.new_page(width=width, height=400)
    for x, y, text in lines:
        page.insert_text((x, y), text, fontsize=10)
    document.save(path)
    document.close()


def test_audit_detects_missing_companion_and_preserved_literal(tmp_path):
    source = tmp_path / "source" / "PUMP-A001.pdf"
    legacy = tmp_path / "翻译" / "PUMP-A001_翻译.pdf"
    _page_pdf(
        source,
        [(20, 40, "Distribution Water Pump"), (20, 80, "DN100")],
    )
    _page_pdf(
        legacy,
        [(20, 40, "Distribution Water Pump"), (20, 80, "DN100")],
    )

    result = audit_inventory(build_inventory(tmp_path))
    regions = result.files[0].pages[0].regions
    by_text = {region.source_text: region for region in regions}

    assert by_text["Distribution Water Pump"].legacy_status is LegacyStatus.MISSING
    assert "missing_chinese_companion" in by_text[
        "Distribution Water Pump"
    ].qa_flags
    assert by_text["DN100"].legacy_status is LegacyStatus.ACCEPTED


def test_audit_checks_geometry_and_site_plan_regressions(tmp_path):
    source = tmp_path / "source" / "1310-CN-ELEC-A001_Site Plan.pdf"
    legacy = tmp_path / "翻译" / "1310-CN-ELEC-A001_Site Plan_翻译.pdf"
    _page_pdf(
        source,
        [
            (20, 40, "Distribution Water Pump"),
            (20, 70, "Distribution Storage Tank"),
            (20, 100, "LANDOWNER / DEVELOPER"),
        ],
        width=500,
    )
    _page_pdf(
        legacy,
        [
            (20, 40, "Distribution Water Pump"),
            (20, 70, "Distribution Storage Tank"),
            (20, 100, "LANDOWNER / DEVELOPER"),
        ],
        width=520,
    )

    result = audit_inventory(build_inventory(tmp_path))
    file_audit = result.files[0]

    assert file_audit.pages[0].geometry_matches is False
    assert "page_geometry_mismatch" in file_audit.pages[0].qa_flags
    checks = {check["check_id"]: check for check in file_audit.regression_checks}
    assert "site-plan-water-system" in checks
    assert "site-plan-title-block" in checks
    assert checks["site-plan-depoh-lori"]["passed"] is False
    assert "vector_outline_ocr_required" in checks["site-plan-depoh-lori"]["qa_flags"]


def test_report_bundle_writes_json_csv_and_html(tmp_path):
    source = tmp_path / "source" / "A.pdf"
    legacy = tmp_path / "翻译" / "A_翻译.pdf"
    _page_pdf(source, [(20, 40, "Pump Room")])
    _page_pdf(legacy, [(20, 40, "Pump Room")])
    result = audit_inventory(build_inventory(tmp_path))

    paths = write_report_bundle(result, tmp_path / "reports", screenshots=True)

    assert Path(paths["json"]).is_file()
    assert Path(paths["csv"]).is_file()
    assert Path(paths["html"]).is_file()
    assert paths["screenshots"]
