from .aggregator import TranslationRunDiagnostics
from .aggregator import classify_provider_family
from .aggregator import get_active_translation_run_diagnostics
from .aggregator import infer_stage_from_request_label
from .aggregator import translation_run_diagnostics_scope
from .models import ErrorTaxonomy
from .models import FinalStatus
from .models import TranslationDiagnostic
from .models import TranslationDiagnosticsCollector
from .models import classify_error_taxonomy

__all__ = [
    "aggregate_payload_diagnostics",
    "build_translation_debug_index",
    "classify_error_taxonomy",
    "ErrorTaxonomy",
    "FinalStatus",
    "TranslationDiagnostic",
    "TranslationDiagnosticsCollector",
    "TranslationRunDiagnostics",
    "classify_provider_family",
    "get_active_translation_run_diagnostics",
    "infer_stage_from_request_label",
    "translation_run_diagnostics_scope",
    "write_translation_debug_index",
    "write_translation_diagnostics",
]


def build_translation_debug_index(*args, **kwargs):
    from .debug_index import build_translation_debug_index as _impl

    return _impl(*args, **kwargs)


def write_translation_debug_index(*args, **kwargs):
    from .debug_index import write_translation_debug_index as _impl

    return _impl(*args, **kwargs)


def aggregate_payload_diagnostics(*args, **kwargs):
    from .io import aggregate_payload_diagnostics as _impl

    return _impl(*args, **kwargs)


def write_translation_diagnostics(*args, **kwargs):
    from .io import write_translation_diagnostics as _impl

    return _impl(*args, **kwargs)
