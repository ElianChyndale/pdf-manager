from __future__ import annotations

import re

from services.rendering.layout.model.models import RenderBlock
from services.rendering.output.typst.block_fit import fit_dimensions
from services.rendering.output.typst import block_config as typst_config
from services.rendering.output.typst.block_fields import typst_block_fields
from services.rendering.output.typst.block_fields import typst_rgb
from services.rendering.output.typst.block_markup import typst_markdown_block
from services.rendering.output.typst.block_markup import typst_markdown_fit_call
from services.rendering.output.typst.block_markup import typst_place_context
from services.rendering.output.typst.block_markup import typst_plain_markdown_expr
from services.rendering.output.typst.block_markup import typst_single_line_fit_call
from services.rendering.output.typst.shared import escape_typst_string

PLAIN_LINE_FIT_MAX_CHARS = 40


def sanitize_typst_markdown_for_compile(markdown: str) -> str:
    text = str(markdown or "")
    text = re.sub(r"\$\s*\^\s*\{\s*\\(?:circled|textcircled)\s*R\s*\}\s*\$", "®", text)
    text = re.sub(r"\$\s*\^\s*\{\s*\\(?:circled|textcircled)\s*\{\s*R\s*\}\s*\}\s*\$", "®", text)
    text = re.sub(r"\$\s*\^\s*\{\s*\\(?:textregistered|registered)\s*\}\s*\$", "®", text)
    text = re.sub(r"\$\s*\^\s*\{\s*®\s*\}\s*\$", "®", text)
    text = text.replace("$^®$", "®").replace("$^{®}$", "®")
    text = text.replace(r"$^\circled{R}$", "®").replace(r"$^\textcircled{R}$", "®")
    text = re.sub(r"\\langlen\b", r"\\langle n", text)
    text = text.replace(r"\circled{\times}", r"\otimes")
    text = text.replace(r"\circled{\parallel}", r"\circ")
    text = text.replace(r"\textcircled{\times}", r"\otimes")
    text = text.replace(r"\textcircled{\parallel}", r"\circ")
    return text


def build_typst_block(block_id: str, block: RenderBlock, *, include_fill: bool = False) -> str:
    fields = typst_block_fields(
        block_id,
        block.inner_bbox,
        font_size_pt=block.font_size_pt,
        leading_em=block.leading_em,
        font_weight=block.font_weight,
    )
    text_fill = typst_rgb(block.text_color)
    block_fill = typst_config.cover_fill_arg(
        include_fill=include_fill,
        use_cover_fill=block.use_cover_fill,
        cover_fill=typst_rgb(block.cover_fill),
    )

    if block.render_kind in {"plain", "plain_line"}:
        plain_text = block.plain_text
        if len(plain_text) > PLAIN_LINE_FIT_MAX_CHARS:
            text_name = f"{fields.var_prefix}_txt"
            body_name = f"{fields.var_prefix}_body"
            body_expr = typst_plain_markdown_expr(
                text_name,
                font_size_pt=fields.font_size,
                leading_em=fields.leading,
                font_weight=fields.font_weight,
                text_fill=text_fill,
                first_line_indent_pt=typst_config.first_line_indent_pt(block.first_line_indent_pt),
                justify_text=typst_config.typst_bool(block.justify_text),
            )
            parts = [
                f'#let {text_name} = "{escape_typst_string(plain_text)}"',
                typst_markdown_block(
                    body_name,
                    width_pt=fields.width,
                    height_pt=fields.height,
                    block_fill=block_fill,
                    body_expr=body_expr,
                ),
                typst_place_context(x_pt=fields.x0, y_pt=fields.y0, body_name=body_name),
            ]
            return "\n".join(parts) + "\n"
        text_name = f"{fields.var_prefix}_txt"
        base_name = f"{fields.var_prefix}_base"
        scaled_name = f"{fields.var_prefix}_scaled"
        parts = [
            f'#let {text_name} = "{escape_typst_string(plain_text)}"',
            f'#let {base_name} = box[#{{ set text(size: {fields.font_size}pt, weight: "{fields.font_weight}", fill: {text_fill}); {text_name} }}]',
            "#context {",
            f"  let base-size = measure({base_name})",
            f"  let scaled-font = if base-size.width > {fields.width}pt {{ {fields.font_size}pt * ({fields.width}pt / base-size.width) }} else {{ {fields.font_size}pt }}",
            f'  let {scaled_name} = block(width: {fields.width}pt, height: {fields.height}pt{block_fill})[#{{ set text(size: scaled-font, weight: "{fields.font_weight}", fill: {text_fill}); {text_name} }}]',
            f"  place(top + left, dx: {fields.x0}pt, dy: {fields.y0}pt, {scaled_name})",
            "}",
        ]
        return "\n".join(parts) + "\n"

    markdown_name = f"{fields.var_prefix}_md"
    body_name = f"{fields.var_prefix}_body"
    markdown = sanitize_typst_markdown_for_compile(block.markdown_text)
    first_line_indent = typst_config.first_line_indent_pt(block.first_line_indent_pt)
    justify_text = typst_config.typst_bool(block.justify_text)
    if block.fit_to_box:
        if block.fit_single_line:
            single_line_fit = typst_config.single_line_fit_config(
                width_pt=fields.width,
                height_pt=fields.height,
                font_size_pt=fields.font_size,
                fit_min_font_size_pt=block.fit_min_font_size_pt,
                fit_max_font_size_pt=block.fit_max_font_size_pt,
                fit_max_height_pt=block.fit_max_height_pt,
                fit_target_width_pt=block.fit_target_width_pt,
                fit_target_height_pt=block.fit_target_height_pt,
                fit_shift_up_pt=block.fit_shift_up_pt,
            )
            fit_call = typst_single_line_fit_call(
                markdown_name,
                single_line_fit,
                font_weight=fields.font_weight,
                justify_text=justify_text,
            )
            parts = [
                f'#let {markdown_name} = "{escape_typst_string(markdown)}"',
                typst_markdown_block(
                    body_name,
                    width_pt=single_line_fit.width_pt,
                    height_pt=single_line_fit.height_pt,
                    block_fill=block_fill,
                    body_expr=f"set text(fill: {text_fill}); {fit_call}",
                ),
                typst_place_context(x_pt=fields.x0, y_pt=fields.y0 - single_line_fit.shift_up_pt, body_name=body_name),
            ]
            return "\n".join(parts) + "\n"
        fit = fit_dimensions(
            width=fields.width,
            height=fields.height,
            font_size=fields.font_size,
            leading=fields.leading,
            fit_min_font_size_pt=block.fit_min_font_size_pt,
            fit_min_leading_em=block.fit_min_leading_em,
            fit_max_height_pt=block.fit_max_height_pt,
        )
        fit_call = typst_markdown_fit_call(
            markdown_name,
            max_font_size_pt=fields.font_size,
            min_font_size_pt=fit["fit_min_font"],
            max_leading_em=fields.leading,
            min_leading_em=fit["fit_min_leading"],
            fit_height_pt=fit["fit_target_height"],
            font_weight=fields.font_weight,
            first_line_indent_pt=first_line_indent,
            justify_text=justify_text,
        )
        parts = [
            f'#let {markdown_name} = "{escape_typst_string(markdown)}"',
            typst_markdown_block(
                body_name,
                width_pt=fit["width"],
                height_pt=fit["fit_height"],
                block_fill=block_fill,
                body_expr=f"set text(fill: {text_fill}); {fit_call}",
            ),
            typst_place_context(x_pt=fields.x0, y_pt=fields.y0, body_name=body_name),
        ]
        return "\n".join(parts) + "\n"
    body_expr = typst_plain_markdown_expr(
        markdown_name,
        font_size_pt=fields.font_size,
        leading_em=fields.leading,
        font_weight=fields.font_weight,
        text_fill=text_fill,
        first_line_indent_pt=first_line_indent,
        justify_text=justify_text,
    )
    parts = [
        f'#let {markdown_name} = "{escape_typst_string(markdown)}"',
        typst_markdown_block(
            body_name,
            width_pt=fields.width,
            height_pt=fields.height,
            block_fill=block_fill,
            body_expr=body_expr,
        ),
        typst_place_context(x_pt=fields.x0, y_pt=fields.y0, body_name=body_name),
    ]
    return "\n".join(parts) + "\n"


def build_typst_cover_rect(block_id: str, block: RenderBlock) -> str:
    rect_name = f"{block_id.replace('-', '_')}_cover"
    x0, y0, x1, y1 = block.cover_bbox
    width = max(typst_config.MIN_BLOCK_SIZE_PT, x1 - x0)
    height = max(typst_config.MIN_BLOCK_SIZE_PT, y1 - y0)
    cover_fill = typst_rgb(block.cover_fill)
    parts = [
        f"#let {rect_name} = rect(width: {width}pt, height: {height}pt, fill: {cover_fill})",
        typst_place_context(x_pt=x0, y_pt=y0, body_name=rect_name),
    ]
    return "\n".join(parts) + "\n"
