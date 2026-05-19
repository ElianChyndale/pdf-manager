from pathlib import Path

import pikepdf


def merge_pdfs(input_paths: list[Path], output_path: Path) -> dict:
    """
    Merge multiple PDFs end-to-end. Returns {page_count, file_size, file_name}.
    """
    total_pages = 0
    with pikepdf.Pdf.new() as pdf:
        for input_path in input_paths:
            with pikepdf.Pdf.open(input_path) as src:
                pdf.pages.extend(src.pages)
                total_pages += len(src.pages)
        pdf.save(output_path, compress_streams=True)

    return {
        "page_count": total_pages,
        "file_size": output_path.stat().st_size,
        "file_name": output_path.name,
    }


def merge_pdfs_with_metadata(
    input_paths: list[Path],
    output_path: Path,
    toc_entries: list[dict] | None = None,
) -> dict:
    """
    Merge with optional TOC remapping.
    toc_entries: [{"title": "Ch1", "page": 1, "file_index": 0}, ...]
    """
    result = merge_pdfs(input_paths, output_path)
    if toc_entries:
        import fitz
        doc = fitz.open(output_path)
        toc = []
        for entry in toc_entries:
            toc.append([1, entry["title"], entry["page"]])
        doc.set_toc(toc)
        doc.save(output_path, incremental=False, deflate=True, garbage=4)
        doc.close()
        result["toc_count"] = len(toc)
    return result
