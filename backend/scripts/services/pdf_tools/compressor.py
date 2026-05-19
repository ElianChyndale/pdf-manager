from pathlib import Path

import fitz

from services.rendering.source.compression.image_pipeline import compress_pdf_images_only_impl


def compress_pdf(input_path: Path, output_path: Path, dpi: int = 150) -> dict:
    """
    Compress PDF images to target DPI. Returns {original_size, compressed_size, page_count}.
    """
    original_size = input_path.stat().st_size
    compress_pdf_images_only_impl(input_path, output_path, dpi=dpi)
    compressed_size = output_path.stat().st_size

    doc = fitz.open(output_path)
    page_count = len(doc)
    doc.close()

    return {
        "original_size": original_size,
        "compressed_size": compressed_size,
        "saved_bytes": original_size - compressed_size,
        "page_count": page_count,
    }
