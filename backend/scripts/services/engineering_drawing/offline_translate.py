"""Offline rule+glossary translator for engineering-drawing natural language.

Covers the bulk of short engineering labels, company/address blocks, and
headings with ZERO API cost.  Only genuinely ambiguous prose falls through to
DeepSeek flash.  Terms are organised by domain; this module is safe to extend
with more terms without touching the translation engine.
"""

from __future__ import annotations

import re

_TERM = {
    # Fire suppression / pre-action valve system
    "valve": "阀", "valves": "阀",
    "preaction valve": "预作用阀",
    "pre-action valve": "预作用阀",
    "priming valve": "预充阀", "normally open": "常开", "normally closed": "常闭",
    "check valve": "止回阀", "drip check valve": "滴漏止回阀", "drain check valve": "排放止回阀",
    "spring loaded check valve": "弹簧式止回阀", "soft seat check valve": "软座止回阀",
    "soft seat swing check valve": "软座旋启式止回阀", "rubber seated check valve": "橡胶座止回阀",
    "strainer": "过滤器", "strainer required": "需过滤器",
    "alarm test valve": "报警试验阀", "alarm shut-off valve": "报警关断阀",
    "auxiliary drain valve": "辅助排放阀", "flow test valve": "流量试验阀",
    "pressure operated relief valve": "压力操作泄压阀", "relief valve": "泄压阀",
    "emergency release": "紧急释放", "drain cup": "排放杯", "drain valve": "排放阀",
    "shut off valve": "关断阀", "isolation valve": "隔离阀",
    "water supply control valve": "供水控制阀", "water supply pressure gauge": "供水压力表",
    "priming pressure water gauge": "预充压力水表", "system pressure gauge": "系统压力表",
    "pressure gauge": "压力表", "solenoid valve": "电磁阀",
    "pneumatic actuator": "气动执行器", "pneumatic release trim": "气动释放配管",
    "electric release trim": "电动释放配管", "accelerator": "加速器",
    "accelerator isolation valve": "加速器隔离阀",
    "system control panel": "系统控制面板",
    "electric detection system": "电气探测系统", "heat detector": "感温探测器",
    "air supervisory pressure switch": "空气监控压力开关", "pressure switch": "压力开关",
    "air pressure supervisory switch": "空气压力监控开关", "supervisory switch": "监控开关",
    "air maintenance device": "空气维持装置", "by-pass trim": "旁通配管",
    "dehydrator": "干燥器", "air compressor": "空气压缩机",
    "tank mounted air compressor": "罐装空气压缩机", "air supply": "供气",
    "water flow alarm equipment": "水流量报警设备", "alarm pressure switch": "报警压力开关",
    "water motor alarm": "水马达报警器", "electric alarm bell": "电动报警铃",
    "restricted orifice": "限流孔板", "riser": "立管",
    "easy riser check valve": "易立管止回阀", "sprinkler system main drain": "喷淋系统主排放",
    "water supply control": "供水控制", "release system": "释放系统",
    "sprinkler system": "喷淋系统", "preaction": "预作用",
    "standard sprinkler pre-action valve": "标准喷淋预作用阀", "assembly details": "装配详图",
    "mechanical system": "机械系统", "consumer landing station": "用户落地站",
    "system components": "系统组件",
    "to drain": "接排放", "vent to atmosphere": "接大气排空", "keep open": "保持开启",
    "atmosphere": "大气", "shown for clarity": "为清晰起见显示",
    "model e": "E 型", "optional": "可选",
    "indicating ball valve recommended": "建议使用带指示的球阀",
    "air maintenance device": "空气维持装置", "by-pass trim": "旁通配管",
    "system control panel": "系统控制面板", "riser": "立管",
    "restricted orifice": "限流孔板", "dehydrator": "干燥器",
    "dashed lines indicate": "虚线表示", "dotted lines indicate": "点线表示",
    "pipe required but not listed": "管道为必需但未列出",
    "electrical detection system wiring required": "电气探测系统布线为必需",
    "additional wiring requirements refer to technical": "附加布线要求请参阅技术资料",
    "for additional wiring requirements": "附加布线要求", "refer to technical data": "请参阅技术资料",
    "data for components used": "所用组件的数据",
    # Drawing titles / headings
    "construction drawing": "施工图", "mechanical system": "机械系统",
    "assembly details": "装配详图", "system components": "系统组件",
    # Company / role labels
    "landowner / developer": "业主／开发商",
    "architect": "建筑师", "base build mep consultant": "主体建筑机电顾问",
    "c&s consultant": "土木与结构顾问", "data centre mep consultant": "数据中心机电顾问",
    "main contractor": "总承包商", "main contractor's mep consultant": "总承包商机电顾问",
    "consulting engineers": "咨询工程师",
    "company no": "公司编号", "tel": "电话", "fax": "传真",
    "e-mail": "邮箱", "website": "网站", "email": "邮箱",
}

# Role headings and their translations (exact match on normalized text).
_ROLE_HEADINGS = {
    "landowner / developer": "业主／开发商",
    "architect": "建筑师",
    "base build mep consultant": "主体建筑机电顾问",
    "c&s consultant": "土木与结构顾问",
    "data centre mep consultant": "数据中心机电顾问",
    "main contractor": "总承包商",
    "main contractor's mep consultant": "总承包商机电顾问",
}


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip()).casefold()


def _translate_valve_label(text: str) -> str | None:
    """Translate a short 'X Valve / Y Switch' style label deterministically.

    Uses longest-term-first replacement so multi-word terms ("soft seat swing
    check valve") translate whole rather than leaving English residue.  The
    leading code (e.g. "F.8") is preserved verbatim.
    """
    norm = _normalized(text)
    if norm in _TERM:
        return _TERM[norm]
    # longest-first so "soft seat swing check valve" wins over "check valve".
    ordered = sorted(_TERM.items(), key=lambda kv: len(kv[0]), reverse=True)
    lowered = norm
    for source, target in ordered:
        lowered = lowered.replace(source, target)
    if lowered != norm and re.search(r"[阀开关执行器过滤器压力表加速器排放释放止回预作用喷淋干燥器报警器面板立管装置]",
                                     lowered):
        code = re.match(r"^[A-Za-z]\.\d+\s*", norm)
        if code:
            # code length in the NORMALIZED string == original code length
            return text[: len(code.group(0))].strip() + " " + lowered[len(code.group(0)):].strip()
        # clean leftover English words (noise) after translation
        cleaned = re.sub(r"\b[a-z]{1,4}\b", "", lowered).strip()
        return cleaned or lowered.strip()
    return None


def _translate_company_block(text: str) -> str | None:
    """Translate a company/address block deterministically where possible.

    Role headings get exact translations; address lines are preserved with a
    Chinese prefix because street names/numbers are not translatable by rule.
    """
    norm = _normalized(text)
    for role, target in _ROLE_HEADINGS.items():
        if norm == role or norm.endswith(":"):
            return target if not norm.endswith(":") else target + "："
    return None


def _translate_heading(text: str) -> str | None:
    norm = _normalized(text)
    if norm in ("system components", "mechanical system", "sprinkler system",
                "assembly details", "consumer landing station", "construction drawing"):
        return _TERM[norm]
    return None


_NOISE_WORDS = {
    "to", "point", "a", "system", "water", "supply", "optional", "vent",
    "atmosphere", "keep", "open", "model", "shown", "for", "clarity", "the",
    "and", "or", "of", "in", "on", "with", "by",
}


def _is_noise(text: str) -> bool:
    """Single untranslatable fragment — return 'no_translation' marker so the
    caller can drop it without an API call."""
    norm = _normalized(text)
    if not norm:
        return True
    if norm in _NOISE_WORDS or len(re.sub(r"[^a-z0-9]", "", norm)) <= 2:
        return True
    return False


def offline_translate(source_text: str) -> str:
    """Return a translation, '' (not covered -> API), or '<noise>'
    (untranslatable fragment to drop without API)."""
    text = str(source_text or "").strip()
    if not text:
        return ""
    if _is_noise(text):
        return "<noise>"
    heading = _translate_heading(text)
    if heading:
        return heading
    company = _translate_company_block(text)
    if company:
        return company
    valve = _translate_valve_label(text)
    if valve:
        return valve
    return ""


__all__ = ["offline_translate"]
