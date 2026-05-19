from pathlib import Path

import fitz


def rotate_pdf(
    input_path: Path, output_path: Path, degrees: int = 90, pages: str = "all"
) -> dict:
    """
    Rotate PDF pages.
    degrees: 0, 90, 180, 270 (clockwise)
    pages: "all" or comma-separated 1-based indices like "1,3,5"
    """
    doc = fitz.open(input_path)
    total = len(doc)

    target_indices = list(range(total))
    if pages != "all":
        target_indices = [
            int(p.strip()) - 1
            for p in pages.split(",")
            if p.strip().isdigit()
        ]
        target_indices = [i for i in target_indices if 0 <= i < total]

    for i in target_indices:
        current = doc[i].rotation or 0
        doc[i].set_rotation((current + degrees) % 360)

    doc.save(output_path, deflate=True, garbage=4)
    doc.close()

    return {
        "rotated_pages": len(target_indices),
        "total_pages": total,
    }
