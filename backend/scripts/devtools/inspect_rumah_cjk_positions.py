import fitz

p = fitz.open(r"D:\AmyProjects\business\WROK-CONTENT\malasia\清真寺施工图纸 11112025 翻译\清真寺施工图纸 11112025 翻译\03_Rumah Sampah_CONSTRUCTION_翻译.pdf")[0]
for b in p.get_text("dict").get("blocks", []):
    if b.get("type") != 0:
        continue
    for line in b.get("lines", []):
        for s in line.get("spans", []):
            t = s.get("text", "")
            if any("\u3400" <= c <= "\u9fff" for c in t):
                x0, y0, x1, y1 = s["bbox"]
                if x0 > 1050 and y0 < 420:
                    print(tuple(round(v, 1) for v in s["bbox"]), repr(t))
