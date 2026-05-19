"""
CLI entry point for PDF tools, called by the Rust API via subprocess.

Usage:
    python -m services.pdf_tools.cli <tool_name> <input_path> <output_path> [options]
"""
import json
import sys
import tempfile
from pathlib import Path

# Ensure backend/scripts is on path
_SCRIPTS_DIR = Path(__file__).resolve().parents[2]
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


def cmd_merge(args: list[str]) -> None:
    from services.pdf_tools.merger import merge_pdfs

    raw_inputs = json.loads(args[0])
    input_paths = [Path(p) for p in raw_inputs]
    output_path = Path(args[1])
    result = merge_pdfs(input_paths, output_path)
    print(json.dumps(result))


def cmd_split(args: list[str]) -> None:
    from services.pdf_tools.splitter import split_pdf

    input_path = Path(args[0])
    output_dir = Path(tempfile.mkdtemp())
    ranges = json.loads(args[1])
    results = split_pdf(input_path, ranges, output_dir)
    # Return first result for single-range split
    print(json.dumps(results[0] if len(results) == 1 else results))


def cmd_compress(args: list[str]) -> None:
    from services.pdf_tools.compressor import compress_pdf

    input_path = Path(args[0])
    output_path = Path(args[1])
    dpi = int(args[2]) if len(args) > 2 else 150
    result = compress_pdf(input_path, output_path, dpi=dpi)
    print(json.dumps(result))


def cmd_rotate(args: list[str]) -> None:
    from services.pdf_tools.rotator import rotate_pdf

    input_path = Path(args[0])
    output_path = Path(args[1])
    degrees = int(args[2]) if len(args) > 2 else 90
    pages = args[3] if len(args) > 3 else "all"
    result = rotate_pdf(input_path, output_path, degrees=degrees, pages=pages)
    print(json.dumps(result))


def cmd_read_metadata(args: list[str]) -> None:
    from services.pdf_tools.metadata_editor import read_metadata

    input_path = Path(args[0])
    result = read_metadata(input_path)
    print(json.dumps(result))


def cmd_write_metadata(args: list[str]) -> None:
    from services.pdf_tools.metadata_editor import write_metadata

    input_path = Path(args[0])
    output_path = Path(args[1])
    updates = json.loads(args[2])
    result = write_metadata(input_path, output_path, updates)
    print(json.dumps(result))


def cmd_encrypt(args: list[str]) -> None:
    from services.pdf_tools.encryptor import encrypt_pdf

    input_path = Path(args[0])
    output_path = Path(args[1])
    params = json.loads(args[2]) if len(args) > 2 else {}
    result = encrypt_pdf(input_path, output_path, **params)
    print(json.dumps(result))


def cmd_decrypt(args: list[str]) -> None:
    from services.pdf_tools.encryptor import decrypt_pdf

    input_path = Path(args[0])
    output_path = Path(args[1])
    password = args[2] if len(args) > 2 else ""
    result = decrypt_pdf(input_path, output_path, password=password)
    print(json.dumps(result))


COMMANDS = {
    "merge": cmd_merge,
    "split": cmd_split,
    "compress": cmd_compress,
    "rotate": cmd_rotate,
    "read-metadata": cmd_read_metadata,
    "write-metadata": cmd_write_metadata,
    "encrypt": cmd_encrypt,
    "decrypt": cmd_decrypt,
}


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m services.pdf_tools.cli <command> [args...]", file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]
    args = sys.argv[2:]

    handler = COMMANDS.get(command)
    if not handler:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)

    try:
        handler(args)
    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
