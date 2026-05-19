from pathlib import Path

import pikepdf


def split_pdf(input_path: Path, ranges: list[dict], output_dir: Path) -> list[dict]:
    """
    Split PDF by page ranges.
    ranges: [{"start": 1, "end": 10, "label": "part1"}, ...]
    Returns list of {file_name, page_count, file_size, label}
    """
    results = []
    with pikepdf.Pdf.open(input_path) as pdf:
        total_pages = len(pdf.pages)
        for i, rng in enumerate(ranges):
            start = max(1, int(rng.get("start", 1)))
            end = min(total_pages, int(rng.get("end", total_pages)))
            label = rng.get("label", f"part-{i + 1}")
            out_name = f"{Path(input_path).stem}-{label}.pdf"
            out_path = output_dir / out_name

            with pikepdf.Pdf.new() as out:
                for page_idx in range(start - 1, end):
                    out.pages.append(pdf.pages[page_idx])
                out.save(out_path)

            results.append({
                "file_name": out_name,
                "page_count": end - start + 1,
                "file_size": out_path.stat().st_size,
                "label": label,
            })
    return results
