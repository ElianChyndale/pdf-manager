"""Translation workflow public facade.

Imports are resolved lazily so low-level modules can depend on workflow helpers
without pulling the full runtime pipeline during test/module import.
"""

__all__ = [
    "BookRequest",
    "BookResult",
    "TranslationRequest",
    "TranslationResult",
    "TranslationExecutionRequest",
    "default_page_translation_name",
    "execute_translation_request",
    "run_book",
    "translate_book",
    "translate_items_to_path",
]


def __getattr__(name: str):
    if name in {"BookRequest", "BookResult", "TranslationRequest", "TranslationResult", "run_book", "translate_book"}:
        from services.translation.workflow import book_facade

        return getattr(book_facade, name)
    if name in {"TranslationExecutionRequest", "execute_translation_request"}:
        from services.translation.workflow import execution

        return getattr(execution, name)
    if name in {"default_page_translation_name", "translate_items_to_path"}:
        from services.translation.workflow import translation_workflow

        return getattr(translation_workflow, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
