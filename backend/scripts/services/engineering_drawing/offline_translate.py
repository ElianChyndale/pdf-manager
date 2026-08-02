"""Offline rule+glossary translator for engineering-drawing natural language.

Covers the bulk of short engineering labels, company/address blocks, and
headings with ZERO API cost.  Only genuinely ambiguous prose falls through to
DeepSeek flash.  Terms are organised by domain; this module is safe to extend
with more terms without touching the translation engine.
"""

from __future__ import annotations

import re

_TERM = {
    # ---- High-frequency engineering labels (repeat across drawings) ----
    "battery": "蓄电池", "trenches": "电缆沟", "trench": "电缆沟",
    "depth": "深度", "future": "预留（未来）", "date": "日期",
    "fall": "排水坡向", "fall 1°": "坡向 1°", "pitch": "坡度", "roof": "屋面",
    "void": "挑空", "(void)": "（挑空）", "scale": "比例",
    "revision": "修订", "correction": "更正", "remarks": "备注",
    "clamp core": "铁芯夹件", "clamp": "夹件", "core": "铁芯",
    "hv-side": "高压侧", "lv-side": "低压侧", "hv side": "高压侧", "lv side": "低压侧",
    "bank 1": "第 1 组", "bank 2": "第 2 组", "bank 3": "第 3 组",
    "ner": "中性点接地电阻", "dga": "油中溶解气体分析", "etx": "端箱", "ptx": "互感器",
    "d00+": "D00+", "depth : 1800mm": "深度：1800mm", "depth: 1800mm": "深度：1800mm",
    "future extension": "预留扩建", "future work": "预留工程",
    "earthing system": "接地系统", "earth": "接地", "earthing": "接地",
    "earth switch": "接地开关", "fast acting earth switch": "快速接地开关",
    "voltage transformer": "电压互感器", "current transformer": "电流互感器",
    "switchgear": "开关柜", "switchgear-a3": "开关柜 A3", "to 1kv switchgear": "接至 1kV 开关柜",
    "transformer": "变压器", "power transformer": "电力变压器",
    "cable": "电缆", "cables": "电缆", "cable trench": "电缆沟",
    "cable tray": "电缆桥架", "cable laid in trench": "电缆敷设于电缆沟内",
    "pump": "水泵", "pumps": "水泵", "pump room": "泵房",
    "light": "照明", "lights": "照明", "lighting": "照明",
    "socket": "插座", "socket outlet": "插座", "switch socket": "开关插座",
    "fan": "风机", "fan coil unit": "风机盘管机组", "fcu": "风机盘管机组",
    "air conditioning": "空调", "aircon": "空调", "air conditioner": "空调",
    "refrigerant pipe": "冷媒管", "refrigerant piping": "冷媒管道",
    "pipe": "管道", "pipes": "管道", "pipe diameter": "管径",
    "tank": "水箱", "water tank": "水箱", "sprinkler tank": "喷淋水箱",
    "water": "水", "water supply": "供水", "water pump": "水泵",
    "fire": "消防", "fire alarm": "火灾报警", "fire hose": "消防水带", "fire extinguisher": "灭火器",
    "alarm": "报警", "alarm system": "报警系统",
    "floor": "楼层", "ground floor": "首层", "first floor": "一层", "second floor": "二层",
    "upper roof floor": "上层屋面", "finish floor level": "完成面标高",
    "room": "房间", "equipment room": "设备间", "plant room": "机房",
    "door": "门", "doors": "门", "window": "窗", "windows": "窗",
    "equipment": "设备", "equipment layout": "设备布置图",
    "layout": "布置图", "plan view": "平面图", "section": "剖面", "elevation": "立面图",
    "detail": "详图", "details": "详图", "detail 1": "详图 1", "detail 2": "详图 2", "detail 6": "详图 6",
    "concrete": "混凝土", "reinforced concrete": "钢筋混凝土", "r.c": "钢筋混凝土",
    "steel": "钢材", "mild steel": "低碳钢", "stainless steel": "不锈钢",
    "galvanised steel": "镀锌钢", "steel column": "钢柱", "steel pipe": "钢管",
    "claybrick": "黏土砖", "cement": "水泥", "brick wall": "砖墙",
    "koridor": "走廊", "lanskap": "景观", "landscape": "景观",
    "revision no": "修订号", "julai": "七月", "2025": "2025",
    "cadangan meroboh dan membina semula masjid al-ehsan": "拆除并重建 Al-Ehsan 清真寺方案",
    "kampung tok muda, kapar, daerah klang, selangor darul ehsan": "雪兰莪州巴生县卡帕 Tok Muda 村",
    "johor darul ta'zim": "柔佛州（Johor Darul Ta'zim）",
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
