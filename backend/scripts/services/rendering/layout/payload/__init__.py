from services.rendering.layout.payload.blocks import build_render_blocks
from services.rendering.layout.payload import body_policy_facade as body_policy
from services.rendering.layout.payload.prepare import prepare_render_payloads_by_page


__all__ = [
    "body_policy",
    "build_render_blocks",
    "prepare_render_payloads_by_page",
]
