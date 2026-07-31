# DEPRECATED - historical V3.x evidence-only run. V4 production authority is
# services/engineering_drawing/run_v4.py (v4-run).
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(r"D:\AmyProjects\business\pdf-manager\output\pdf\engineering-drawing\01_Bilingual_Inline\agent-artifacts\sol-light-supervisor-verified-v311")

for sample in sorted(ROOT.glob("sample-*")):
    paths = sorted(sample.glob("page-*/page-*-source.png"))
    if not paths:
        continue
    thumbs = []
    for path in paths:
        im = Image.open(path).convert("RGB")
        im.thumbnail((700, 480))
        canvas = Image.new("RGB", (720, 520), "white")
        canvas.paste(im, ((720-im.width)//2, 28))
        ImageDraw.Draw(canvas).text((8, 6), path.parent.name, fill="black")
        thumbs.append(canvas)
    cols = 2
    rows = (len(thumbs)+cols-1)//cols
    out = Image.new("RGB", (cols*720, rows*520), "white")
    for idx, thumb in enumerate(thumbs):
        out.paste(thumb, ((idx%cols)*720, (idx//cols)*520))
    out.save(sample / "source-contact-sheet.jpg", quality=88)
