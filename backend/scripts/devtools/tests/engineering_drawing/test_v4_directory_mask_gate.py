import pytest

from services.engineering_drawing.workflow_policy import validate_directory_mask_audit


def test_directory_mask_audit_accepts_zero_intersection():
    result=validate_directory_mask_audit({"masks":[[20,20,40,30]],"protected_rects":[[0,0,10,100],[80,0,100,100]],"table_rule_rects":[[0,10,100,11]],"minimum_clearance_pt":1.5,"pagewise_row_numbers_match_source":True})
    assert result["passed"] is True
    assert result["intersection_count"] == 0


def test_directory_mask_audit_rejects_number_column_intersection():
    with pytest.raises(ValueError,match="intersect protected"):
        validate_directory_mask_audit({"masks":[[8,20,30,30]],"protected_rects":[[0,0,10,100]],"table_rule_rects":[],"minimum_clearance_pt":1.5,"pagewise_row_numbers_match_source":True})


def test_directory_mask_audit_requires_pagewise_row_number_check():
    with pytest.raises(ValueError,match="row-number comparison"):
        validate_directory_mask_audit({"masks":[],"protected_rects":[],"table_rule_rects":[],"minimum_clearance_pt":1.5,"pagewise_row_numbers_match_source":False})
