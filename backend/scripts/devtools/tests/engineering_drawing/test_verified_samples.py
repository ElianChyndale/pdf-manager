from __future__ import annotations

from devtools.run_verified_samples import SELECTED


def test_verified_sample_set_covers_ten_distinct_representative_sheet_types() -> None:
    """The approval set must exercise every high-risk regional rendering mode."""
    names = {name for name, _top_level in SELECTED}

    assert len(SELECTED) == 10
    assert {
        "00_LIST OF DRAWING_A3 FORMAT.pdf",
        "02_REV. JULAI 2025 JADUAL PINTU & TINGKAP.pdf",
        "03_REV JULAI 2025 JADUAL PANEL KACA.pdf",
        "05_REV. JULAI 2025 PERINCIAN TANDAS.pdf",
        "10_REV. JULAI 2025 ROOF DETAIL.pdf",
        "1310-CN-ELEC-A001_Site Plan.pdf",
        "1310-CN-ELEC-A002_Elevation.pdf",
        "1310-CN-ELEC-ELPS-B001_Main Earth Grid.pdf",
        "1310-CN-ELEC-SCH-C001_275kV SLD.pdf",
        "1312-CN-MECH-ACMV-A001.pdf",
    }.issubset(names)
