import fitz

src = fitz.open(r"D:\AmyProjects\business\WROK-CONTENT\malasia\03_CONSTRUCTION DWG_MASJID_11 NOV 2025\A1 WORKING DRAWING\03_Rumah Sampah_CONSTRUCTION.pdf")
ref = fitz.open(r"D:\AmyProjects\business\WROK-CONTENT\malasia\清真寺施工图纸 11112025 翻译\清真寺施工图纸 11112025 翻译\03_Rumah Sampah_CONSTRUCTION_翻译.pdf")
ys = [55.3,148.1,248.2,348.4,484.7,550.7,659.3,778.4,872.9,970.2,1070.3,1170.4,1266.2,1362.2,1398.6,1451.6,1542.6,1628.5]
for i, (a, b) in enumerate(zip(ys, ys[1:])):
    clip = fitz.Rect(2083, a, 2327, b)
    s = " ".join(src[0].get_text("text", clip=clip, sort=True).split())
    z = " ".join(ref[0].get_text("text", clip=clip, sort=True).split())
    print(f"\nP{i}\nSRC {s}\nREF {z}")
