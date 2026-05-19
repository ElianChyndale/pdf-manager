import sys
import unittest
from pathlib import Path


REPO_SCRIPTS_ROOT = Path("REPO_ROOT_PLACEHOLDER/backend/scripts")
sys.path.insert(0, str(REPO_SCRIPTS_ROOT))

from services.rendering.layout.font_fit import estimate_font_size_pt
from services.rendering.layout.font_fit import estimate_leading_em
from services.rendering.layout.font_fit import is_body_text_candidate
from services.rendering.layout.font_fit import local_font_size_pt
from services.rendering.layout.font_fit import normalize_leading_em_for_font_size
from services.rendering.layout.font_fit import BODY_LEADING_MAX
from services.rendering.layout.font_fit import BODY_LEADING_MIN
from services.rendering.layout.payload.block_seed_body_policy import is_dense_small_box
from services.rendering.layout.payload.block_seed_body_policy import is_heavy_dense_small_box
from services.rendering.layout.payload.blocks import build_render_blocks
from services.rendering.layout.payload.block_seed import _relax_wide_aspect_body_leading
from services.rendering.layout.payload.fit import fit_translated_block_metrics
from services.rendering.layout.typography.measurement import source_visual_line_count
from services.rendering.layout.typography.measurement import visual_line_count


def _sample_item(*, wide_aspect: bool) -> dict:
    return {
        "block_type": "text",
        "source_text": (
            "This document offers initial ideas for an industrial policy agenda to keep people first "
            "during the transition to superintelligence."
        ),
        "bbox": [40, 100, 512, 205],
        "lines": [
            {"bbox": [40, 100, 505, 113], "spans": [{"type": "text", "content": "This document offers initial ideas"}]},
            {"bbox": [40, 115, 503, 128], "spans": [{"type": "text", "content": "for an industrial policy agenda"}]},
            {"bbox": [40, 130, 506, 143], "spans": [{"type": "text", "content": "to keep people first during"}]},
            {"bbox": [40, 145, 504, 158], "spans": [{"type": "text", "content": "the transition to"}]},
            {"bbox": [40, 160, 500, 173], "spans": [{"type": "text", "content": "superintelligence."}]},
        ],
        "_is_body_text_candidate": True,
        "_wide_aspect_body_text": wide_aspect,
    }


class WideAspectBodyFitTests(unittest.TestCase):
    def test_local_font_size_uses_glyph_height_not_loose_line_pitch(self):
        item = {
            "block_type": "text",
            "source_text": "Line one with normal glyphs. Line two has very loose leading.",
            "bbox": [40, 100, 420, 160],
            "lines": [
                {"bbox": [40, 100, 410, 112], "spans": [{"type": "text", "content": "Line one with normal glyphs."}]},
                {"bbox": [40, 140, 410, 152], "spans": [{"type": "text", "content": "Line two has very loose leading."}]},
            ],
        }

        self.assertLess(local_font_size_pt(item), 12.0)

    def test_local_font_size_can_grow_for_large_source_glyphs(self):
        item = {
            "block_type": "text",
            "source_text": "Large source text should not be capped at small body defaults.",
            "bbox": [40, 100, 420, 150],
            "lines": [
                {"bbox": [40, 100, 410, 116], "spans": [{"type": "text", "content": "Large source text should not"}]},
                {"bbox": [40, 124, 410, 140], "spans": [{"type": "text", "content": "be capped at small body defaults."}]},
            ],
        }

        self.assertGreater(local_font_size_pt(item), 12.0)

    def test_wide_aspect_body_keeps_font_closer_to_local_ocr(self):
        base_item = _sample_item(wide_aspect=False)
        wide_item = _sample_item(wide_aspect=True)
        page_font_size = 11.6
        page_line_pitch = 14.0
        page_line_height = 12.6
        density_baseline = 28.0

        base_font = estimate_font_size_pt(base_item, page_font_size, page_line_pitch, page_line_height, density_baseline)
        wide_font = estimate_font_size_pt(wide_item, page_font_size, page_line_pitch, page_line_height, density_baseline)

        self.assertGreater(wide_font, base_font)

    def test_body_font_estimate_does_not_apply_page_factor_twice(self):
        item = _sample_item(wide_aspect=False)
        page_font_size = 11.0
        page_line_pitch = 15.0
        page_line_height = 13.0
        density_baseline = 28.0

        font = estimate_font_size_pt(item, page_font_size, page_line_pitch, page_line_height, density_baseline)

        self.assertGreaterEqual(font, 10.5)

    def test_caption_font_is_visibly_smaller_than_body_font(self):
        body = _sample_item(wide_aspect=False)
        caption = {
            "block_kind": "text",
            "raw_block_type": "figure_title",
            "layout_role": "caption",
            "semantic_role": "metadata",
            "structure_role": "figure_caption",
            "normalized_sub_type": "figure_caption",
            "source_text": "FIG. 1. Cross sections of surfaces of revolution.",
            "bbox": [311.5, 529.5, 562.0, 587.0],
            "lines": [
                {
                    "bbox": [311.5, 529.5, 562.0, 541.5],
                    "spans": [{"type": "text", "content": "FIG. 1. Cross sections of surfaces"}],
                },
                {
                    "bbox": [311.5, 545.5, 562.0, 557.5],
                    "spans": [{"type": "text", "content": "of revolution."}],
                },
            ],
        }
        page_font_size = 10.8
        page_line_pitch = 14.0
        page_line_height = 12.0
        density_baseline = 28.0

        body_font = estimate_font_size_pt(body, page_font_size, page_line_pitch, page_line_height, density_baseline)
        caption_font = estimate_font_size_pt(caption, page_font_size, page_line_pitch, page_line_height, density_baseline)

        self.assertLessEqual(caption_font, 9.8)
        self.assertLess(caption_font, body_font - 0.5)

    def test_vision_footnote_font_is_annotation_sized(self):
        body = _sample_item(wide_aspect=False)
        footnote = {
            "block_type": "text",
            "block_kind": "text",
            "raw_block_type": "vision_footnote",
            "layout_role": "footnote",
            "semantic_role": "unknown",
            "structure_role": "footnote",
            "normalized_sub_type": "footnote",
            "tags": ["footnote"],
            "source_text": "a P < 0.05; b adjusted confidence interval.",
            "bbox": [58.0, 720.0, 520.0, 742.0],
            "lines": [
                {
                    "bbox": [58.0, 720.0, 520.0, 731.0],
                    "spans": [{"type": "text", "content": "a P < 0.05; b adjusted confidence interval."}],
                }
            ],
        }
        page_font_size = 10.8
        page_line_pitch = 14.0
        page_line_height = 12.0
        density_baseline = 28.0

        body_font = estimate_font_size_pt(body, page_font_size, page_line_pitch, page_line_height, density_baseline)
        footnote_font = estimate_font_size_pt(footnote, page_font_size, page_line_pitch, page_line_height, density_baseline)

        self.assertLessEqual(footnote_font, 8.8)
        self.assertLess(footnote_font, body_font - 1.0)
        self.assertFalse(is_body_text_candidate(footnote, page_text_width_med=300.0))

    def test_source_visual_line_count_uses_observed_ocr_lines_not_text_length(self):
        item = {
            "block_type": "text",
            "source_text": (
                "This is a very long OCR line that would normally wrap by text-length prediction, "
                "but the source line count should still reflect the observed OCR line geometry only."
            ),
            "bbox": [40, 100, 220, 145],
            "lines": [
                {
                    "bbox": [40, 100, 220, 112],
                    "spans": [{"type": "text", "content": "This is a very long OCR line"}],
                }
            ],
        }

        self.assertEqual(source_visual_line_count(item), 1)
        self.assertGreater(visual_line_count(item), 1)

    def test_small_single_line_body_uses_original_bbox(self):
        items = [
            _sample_item(wide_aspect=False),
            {
                "item_id": "small-line",
                "block_type": "text",
                "source_text": "This is a body continuation line whose OCR bbox is too short for the real font size.",
                "bbox": [40, 220, 512, 228],
                "lines": [
                    {
                        "bbox": [40, 220, 510, 228],
                        "spans": [
                            {
                                "type": "text",
                                "content": "This is a body continuation line whose OCR bbox is too short.",
                            }
                        ],
                    }
                ],
                "protected_translated_text": "这是正文中的一行续写，OCR 给出的高度偏小，但字号应当跟随本页正文。",
            },
        ]

        blocks = build_render_blocks(items, page_width=612.0, page_height=792.0)
        body_block = next(block for block in blocks if block.block_id == "item-1")

        self.assertEqual(body_block.inner_bbox, items[1]["bbox"])

    def test_narrow_single_line_body_uses_original_bbox(self):
        items = [
            _sample_item(wide_aspect=False),
            {
                "item_id": "line-1",
                "block_type": "text",
                "source_text": "This normal body line provides the page body width reference for rendering.",
                "bbox": [40, 220, 512, 235],
                "lines": [
                    {
                        "bbox": [40, 220, 510, 235],
                        "spans": [{"type": "text", "content": "This normal body line provides the reference."}],
                    }
                ],
                "protected_translated_text": "这是正常宽度的正文行，用来提供页面正文宽度基准。",
            },
            {
                "item_id": "line-2",
                "block_type": "text",
                "source_text": "This middle body line has a clipped OCR bbox but should render at normal width.",
                "bbox": [40, 240, 250, 255],
                "lines": [
                    {
                        "bbox": [40, 240, 250, 255],
                        "spans": [{"type": "text", "content": "This middle body line has a clipped OCR bbox."}],
                    }
                ],
                "protected_translated_text": "这是中间一行正文，OCR 给出的宽度偏短，但排版不应该因此强制换行。",
            },
            {
                "item_id": "line-3",
                "block_type": "text",
                "source_text": "This following body line also keeps the normal page body text width.",
                "bbox": [40, 260, 512, 275],
                "lines": [
                    {
                        "bbox": [40, 260, 510, 275],
                        "spans": [{"type": "text", "content": "This following body line keeps normal width."}],
                    }
                ],
                "protected_translated_text": "这是后续正常宽度的正文行。",
            },
        ]

        blocks = build_render_blocks(items, page_width=612.0, page_height=792.0)
        narrow_block = next(block for block in blocks if block.block_id == "item-2")

        self.assertEqual(narrow_block.inner_bbox, items[2]["bbox"])
        self.assertLess(narrow_block.cover_bbox[0], 40)
        self.assertLess(narrow_block.cover_bbox[1], 240)
        self.assertGreater(narrow_block.cover_bbox[2], 250)
        self.assertGreater(narrow_block.cover_bbox[3], 255)

    def test_short_body_line_inherits_same_column_font_floor(self):
        items = [
            {
                "item_id": "body-anchor-1",
                "block_type": "text",
                "source_text": "A normal body paragraph establishes the same-column font.",
                "bbox": [44, 100, 382, 150],
                "lines": [
                    {"bbox": [44, 100, 380, 112], "spans": [{"type": "text", "content": "A normal body paragraph"}]},
                    {"bbox": [44, 116, 380, 128], "spans": [{"type": "text", "content": "establishes the same-column font."}]},
                ],
                "protected_translated_text": "这是一个普通正文段落，用来建立本栏的正文字号。",
            },
            {
                "item_id": "body-anchor-2",
                "block_type": "text",
                "source_text": "Another normal paragraph in the same column.",
                "bbox": [44, 170, 382, 220],
                "lines": [
                    {"bbox": [44, 170, 380, 182], "spans": [{"type": "text", "content": "Another normal paragraph"}]},
                    {"bbox": [44, 186, 380, 198], "spans": [{"type": "text", "content": "in the same column."}]},
                ],
                "protected_translated_text": "这是同一栏里的另一个普通正文段落。",
            },
            {
                "item_id": "body-anchor-3",
                "block_type": "text",
                "source_text": "A third paragraph makes the column signal stable.",
                "bbox": [44, 240, 382, 290],
                "lines": [
                    {"bbox": [44, 240, 380, 252], "spans": [{"type": "text", "content": "A third paragraph"}]},
                    {"bbox": [44, 256, 380, 268], "spans": [{"type": "text", "content": "makes the signal stable."}]},
                ],
                "protected_translated_text": "第三个段落让同栏正文字号信号更加稳定。",
            },
            {
                "item_id": "short-body-line",
                "block_type": "text",
                "source_text": "Remember that we are still dealing with spin-orbitals.",
                "bbox": [44, 320, 288, 332],
                "lines": [
                    {
                        "bbox": [44, 320, 288, 332],
                        "spans": [{"type": "text", "content": "Remember that we are still dealing with spin-orbitals."}],
                    }
                ],
                "protected_translated_text": "请记住仍在处理自旋轨道。",
            },
            {
                "item_id": "next-tight-line",
                "block_type": "text",
                "source_text": "A following line sits close enough to trigger collision fit.",
                "bbox": [44, 333, 382, 345],
                "lines": [
                    {
                        "bbox": [44, 333, 382, 345],
                        "spans": [{"type": "text", "content": "A following line sits close."}],
                    }
                ],
                "protected_translated_text": "下一行很近，会触发相邻碰撞压缩。",
            },
        ]

        blocks = build_render_blocks(items, page_width=430.0, page_height=655.0)
        short_block = next(block for block in blocks if block.source_item_id == "short-body-line")
        anchor_fonts = [
            block.font_size_pt
            for block in blocks
            if block.source_item_id in {"body-anchor-1", "body-anchor-2", "body-anchor-3"}
        ]

        self.assertGreaterEqual(short_block.font_size_pt, min(anchor_fonts) - 0.9)
        self.assertGreaterEqual(short_block.fit_min_font_size_pt, min(anchor_fonts) - 1.1)

    def test_similar_body_fonts_unify_before_underfill_growth(self):
        items = [
            {
                "item_id": "body-1",
                "block_type": "text",
                "source_text": "Normal body paragraph one establishes the first paragraph in the same column.",
                "bbox": [44, 100, 382, 150],
                "lines": [
                    {"bbox": [44, 100, 380, 112], "spans": [{"type": "text", "content": "Normal body paragraph one"}]},
                    {"bbox": [44, 116, 380, 128], "spans": [{"type": "text", "content": "establishes the first paragraph."}]},
                ],
                "protected_translated_text": "这是同一栏中的第一段正文。",
            },
            {
                "item_id": "body-2",
                "block_type": "text",
                "source_text": "Normal body paragraph two with similar size.",
                "bbox": [44, 170, 382, 222],
                "lines": [
                    {"bbox": [44, 170, 380, 183], "spans": [{"type": "text", "content": "Normal body paragraph two."}]},
                    {"bbox": [44, 186, 380, 199], "spans": [{"type": "text", "content": "with similar size."}]},
                ],
                "protected_translated_text": "这是第二段正文，字号应当与第一段统一。",
            },
            {
                "item_id": "body-3",
                "block_type": "text",
                "source_text": "Normal body paragraph three with similar size.",
                "bbox": [44, 242, 382, 294],
                "lines": [
                    {"bbox": [44, 242, 380, 256], "spans": [{"type": "text", "content": "Normal body paragraph three."}]},
                    {"bbox": [44, 259, 380, 273], "spans": [{"type": "text", "content": "with similar size."}]},
                ],
                "protected_translated_text": "这是第三段正文，字号也应当统一。",
            },
        ]

        blocks = build_render_blocks(items, page_width=430.0, page_height=655.0)
        fonts = [block.font_size_pt for block in blocks]

        self.assertLess(max(fonts) / min(fonts), 1.06)
        self.assertGreater(max(fonts), min(fonts))

    def test_low_height_body_inherits_tall_same_column_font(self):
        items = [
            {
                "item_id": "tall-body-1",
                "block_type": "text",
                "source_text": "A tall paragraph establishes the same-column font.",
                "bbox": [44, 80, 382, 150],
                "lines": [
                    {"bbox": [44, 80, 380, 94], "spans": [{"type": "text", "content": "A tall paragraph establishes"}]},
                    {"bbox": [44, 100, 380, 114], "spans": [{"type": "text", "content": "the same-column font."}]},
                ],
                "protected_translated_text": "这是一个较高的正文段落，用来建立同栏正文字号。",
            },
            {
                "item_id": "low-body",
                "block_type": "text",
                "source_text": "A lower-height paragraph in the same body column should not stay tiny.",
                "bbox": [44, 170, 382, 202],
                "lines": [
                    {"bbox": [44, 170, 380, 183], "spans": [{"type": "text", "content": "A lower-height paragraph"}]},
                    {"bbox": [44, 187, 380, 200], "spans": [{"type": "text", "content": "in the same body column."}]},
                ],
                "protected_translated_text": "这是同栏中高度较低的正文段落，字号应当向较高正文框看齐。",
            },
            {
                "item_id": "tall-body-2",
                "block_type": "text",
                "source_text": "Another tall paragraph stabilizes the same-column font.",
                "bbox": [44, 230, 382, 302],
                "lines": [
                    {"bbox": [44, 230, 380, 244], "spans": [{"type": "text", "content": "Another tall paragraph"}]},
                    {"bbox": [44, 250, 380, 264], "spans": [{"type": "text", "content": "stabilizes the same-column font."}]},
                ],
                "protected_translated_text": "另一个较高的正文段落让同栏字号信号更稳定。",
            },
        ]

        blocks = build_render_blocks(items, page_width=430.0, page_height=655.0)
        low_block = next(block for block in blocks if block.source_item_id == "low-body")
        tall_fonts = [
            block.font_size_pt
            for block in blocks
            if block.source_item_id in {"tall-body-1", "tall-body-2"}
        ]

        self.assertGreaterEqual(low_block.font_size_pt, min(tall_fonts) - 0.35)

    def test_dense_small_box_requires_geometry_density(self):
        self.assertFalse(
            is_dense_small_box(
                density_ratio=1.4,
                layout_density=0.55,
                page_box_area_ratio=0.03,
            )
        )
        self.assertFalse(
            is_heavy_dense_small_box(
                density_ratio=1.4,
                layout_density=0.55,
                page_box_area_ratio=0.03,
                heavy_compact_ratio=1.0,
            )
        )

    def test_dense_small_box_uses_geometry_as_primary_signal(self):
        self.assertTrue(
            is_dense_small_box(
                density_ratio=0.5,
                layout_density=0.9,
                page_box_area_ratio=0.03,
            )
        )
        self.assertTrue(
            is_heavy_dense_small_box(
                density_ratio=0.5,
                layout_density=1.02,
                page_box_area_ratio=0.03,
                heavy_compact_ratio=1.0,
            )
        )

    def test_short_body_context_height_can_relax_fit_budget(self):
        items = [
            {
                "item_id": "body-anchor-1",
                "block_type": "text",
                "source_text": "A normal paragraph establishes column body geometry.",
                "bbox": [44, 100, 382, 150],
                "lines": [
                    {"bbox": [44, 100, 380, 112], "spans": [{"type": "text", "content": "A normal paragraph"}]},
                    {"bbox": [44, 116, 380, 128], "spans": [{"type": "text", "content": "establishes geometry."}]},
                ],
                "protected_translated_text": "这是一个普通正文段落，用来建立同栏正文几何。",
            },
            {
                "item_id": "body-anchor-2",
                "block_type": "text",
                "source_text": "Another normal paragraph establishes column body geometry.",
                "bbox": [44, 170, 382, 222],
                "lines": [
                    {"bbox": [44, 170, 380, 183], "spans": [{"type": "text", "content": "Another normal paragraph"}]},
                    {"bbox": [44, 186, 380, 199], "spans": [{"type": "text", "content": "establishes geometry."}]},
                ],
                "protected_translated_text": "这是另一个普通正文段落，用来建立同栏正文几何。",
            },
            {
                "item_id": "short-body",
                "block_type": "text",
                "source_text": "Short OCR bbox should not be a hard height limit.",
                "bbox": [44, 250, 288, 262],
                "lines": [
                    {
                        "bbox": [44, 250, 288, 262],
                        "spans": [{"type": "text", "content": "Short OCR bbox should not be a hard height limit."}],
                    }
                ],
                "protected_translated_text": "短 OCR 框不应成为正文高度硬限制。",
            },
        ]

        blocks = build_render_blocks(items, page_width=430.0, page_height=655.0)
        short_block = next(block for block in blocks if block.source_item_id == "short-body")

        self.assertTrue(short_block.fit_to_box)
        self.assertGreater(short_block.fit_max_height_pt, short_block.inner_bbox[3] - short_block.inner_bbox[1])

    def test_wide_aspect_body_preserves_more_ocr_line_pitch_signal(self):
        base_item = _sample_item(wide_aspect=False)
        wide_item = _sample_item(wide_aspect=True)

        base_leading = estimate_leading_em(base_item, 14.0, 10.8)
        wide_leading = estimate_leading_em(wide_item, 14.0, 10.8)

        self.assertLessEqual(wide_leading, base_leading)
        self.assertGreaterEqual(wide_leading, 0.34)

    def test_large_body_font_does_not_force_tight_leading(self):
        leading = normalize_leading_em_for_font_size(
            11.8,
            0.52,
            reference_font_size_pt=10.6,
            min_leading_em=BODY_LEADING_MIN,
            max_leading_em=BODY_LEADING_MAX,
            strength=1.0,
        )

        self.assertGreaterEqual(leading, 0.52)

    def test_dense_body_fit_prefers_font_shrink_over_cramped_leading(self):
        item = {
            "block_type": "text",
            "source_text": "Dense body paragraph.",
            "bbox": [40, 100, 220, 148],
            "_render_inner_bbox": [40, 100, 220, 148],
            "_is_body_text_candidate": True,
            "_dense_small_box": True,
            "_heavy_dense_small_box": False,
        }
        text = "这是一个非常密集的正文段落，需要在有限高度内优先缩小字号，而不是把行距压得过低。" * 4

        font_size, leading = fit_translated_block_metrics(
            item,
            text,
            [],
            10.8,
            0.58,
            page_body_font_size_pt=10.8,
        )

        self.assertLess(font_size, 10.4)
        self.assertGreaterEqual(leading, 0.54)

    def test_dense_body_boxes_do_not_inherit_oversized_page_font(self):
        items = [
            {
                "item_id": "large-body",
                "block_type": "text",
                "source_text": "Large paragraph establishes the local page body size.",
                "bbox": [40, 80, 520, 230],
                "lines": [
                    {"bbox": [40, 80, 515, 96], "spans": [{"type": "text", "content": "Large paragraph"}]},
                    {"bbox": [40, 104, 515, 120], "spans": [{"type": "text", "content": "with generous geometry."}]},
                ],
                "protected_translated_text": "这是一个普通的大正文块，用来建立本页正文的字号基准。",
            },
            {
                "item_id": "dense-small",
                "block_type": "text",
                "source_text": "Dense small paragraph should stay visually modest.",
                "bbox": [40, 250, 220, 300],
                "lines": [
                    {"bbox": [40, 250, 218, 263], "spans": [{"type": "text", "content": "Dense small paragraph"}]},
                    {"bbox": [40, 266, 218, 279], "spans": [{"type": "text", "content": "with longer translated text."}]},
                ],
                "protected_translated_text": "这是一个密集的小正文框，译文比较长，但字号不应该继承过大的页级正文尺寸。" * 2,
            },
        ]

        blocks = build_render_blocks(items, page_width=612.0, page_height=792.0)
        dense_block = next(block for block in blocks if block.block_id == "item-1")

        self.assertLessEqual(dense_block.font_size_pt, 10.35)

    def test_wide_aspect_body_relaxes_leading_when_vertical_slack_exists(self):
        text = (
            "本文件提出了产业政策议程的初步构想，旨在确保向超级智能过渡的过程中以人为本。"
            "内容分为两部分：一是构建一个具有广泛参与、参与和共享繁荣的开放经济；"
            "二是通过问责、对齐和前沿风险管理来建设一个具有韧性的社会。"
        )
        relaxed = _relax_wide_aspect_body_leading(
            [82.0, 337.0, 530.0, 436.0],
            text,
            [],
            11.32,
            0.42,
        )
        self.assertGreater(relaxed, 0.42)

    def test_wide_aspect_body_keeps_leading_when_height_is_tight(self):
        text = (
            "然而，正是这些推动进步的能力，也将以前所未有的速度和规模重塑整个产业。"
            "部分工作岗位将消失，另一些将演变，而随着各组织学会如何部署先进人工智能，"
            "全新的工作形态也将应运而生。"
        )
        relaxed = _relax_wide_aspect_body_leading(
            [82.0, 454.0, 530.0, 493.0],
            text,
            [],
            11.32,
            0.42,
        )
        self.assertLessEqual(relaxed, 0.46)

    def test_underfilled_body_uses_font_growth_before_loose_leading(self):
        items = [
            {
                "item_id": "body-anchor",
                "block_type": "text",
                "source_text": "A normal paragraph establishes body size.",
                "bbox": [44, 80, 382, 132],
                "lines": [
                    {"bbox": [44, 80, 380, 93], "spans": [{"type": "text", "content": "A normal paragraph"}]},
                    {"bbox": [44, 96, 380, 109], "spans": [{"type": "text", "content": "establishes body size."}]},
                ],
                "protected_translated_text": "这是一个普通正文段落，用来建立正文字号。",
            },
            {
                "item_id": "underfilled",
                "block_type": "text",
                "source_text": "A short translated body paragraph has ample vertical room.",
                "bbox": [44, 160, 382, 250],
                "lines": [
                    {"bbox": [44, 160, 380, 173], "spans": [{"type": "text", "content": "A short translated body paragraph"}]},
                    {"bbox": [44, 176, 380, 189], "spans": [{"type": "text", "content": "has ample vertical room."}]},
                ],
                "protected_translated_text": "这是较短的正文。",
            },
            {
                "item_id": "body-anchor-2",
                "block_type": "text",
                "source_text": "Another normal paragraph establishes body size.",
                "bbox": [44, 280, 382, 332],
                "lines": [
                    {"bbox": [44, 280, 380, 293], "spans": [{"type": "text", "content": "Another normal paragraph"}]},
                    {"bbox": [44, 296, 380, 309], "spans": [{"type": "text", "content": "establishes body size."}]},
                ],
                "protected_translated_text": "这是另一个普通正文段落，用来建立正文字号。",
            },
        ]

        blocks = build_render_blocks(items, page_width=430.0, page_height=655.0)
        underfilled = next(block for block in blocks if block.source_item_id == "underfilled")
        anchors = [block for block in blocks if block.source_item_id in {"body-anchor", "body-anchor-2"}]

        self.assertGreaterEqual(underfilled.font_size_pt, min(block.font_size_pt for block in anchors) - 0.2)
        self.assertLessEqual(underfilled.leading_em, 0.68)


if __name__ == "__main__":
    unittest.main()
