from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_script(relative_path: str):
    script_path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(script_path.stem, script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pdf_benchmark_generates_page_and_question_scale_outputs(tmp_path):
    module = load_script("scripts/run_pdf_extraction_benchmark.py")

    result = module.run_pdf_extraction_benchmark(output_dir=tmp_path, seed=42)

    assert result["page_count"] >= 20
    assert result["question_count"] >= 30
    assert len(result["extraction_rows"]) == 4
    assert len(result["retrieval_rows"]) == 4
    assert len(result["citation_rows"]) == 4


def test_layout_metadata_method_improves_citation_accuracy(tmp_path):
    module = load_script("scripts/run_pdf_extraction_benchmark.py")

    result = module.run_pdf_extraction_benchmark(output_dir=tmp_path, seed=13)
    citation = {row["method"]: row for row in result["citation_rows"]}

    assert float(citation["layout_aware_metadata"]["citation_accuracy"]) > float(citation["raw_text"]["citation_accuracy"])
    assert all(0.0 <= float(row["retrieval_recall_at_5"]) <= 1.0 for row in result["retrieval_rows"])


def test_failure_taxonomy_contains_expected_failure_types(tmp_path):
    module = load_script("scripts/run_pdf_extraction_benchmark.py")

    result = module.run_pdf_extraction_benchmark(output_dir=tmp_path, seed=21)
    failure_types = {row["failure_type"] for row in result["failure_rows"]}

    assert {"table_boundary_failure", "two_column_reading_order_failure", "ocr_numeric_error", "incorrect_page_citation"}.issubset(failure_types)
