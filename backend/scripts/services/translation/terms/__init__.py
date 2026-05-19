from .abbreviations import AbbreviationEntry
from .glossary import GlossaryEntry
from .glossary import glossary_hard_entries
from .glossary import normalize_glossary_entries
from .glossary import parse_glossary_json
from .injection import build_terms_guidance
from .preserve import auto_preserve_glossary_entries_from_texts
from .preserve import merge_auto_preserve_glossary_entries
from .usage import summarize_glossary_usage

__all__ = [
    "AbbreviationEntry",
    "GlossaryEntry",
    "auto_preserve_glossary_entries_from_texts",
    "build_terms_guidance",
    "glossary_hard_entries",
    "merge_auto_preserve_glossary_entries",
    "normalize_glossary_entries",
    "parse_glossary_json",
    "summarize_glossary_usage",
]
