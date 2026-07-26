from __future__ import annotations

import argparse
import json
import traceback
from pathlib import Path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--model", default="deepseek-ai/DeepSeek-OCR-2")
    parser.add_argument("--prompt", default="<image>\nFree OCR.")
    parser.add_argument("--base-size", type=int, default=1024)
    parser.add_argument("--image-size", type=int, default=768)
    parser.add_argument(
        "--quantization",
        choices=("auto", "none", "offload"),
        default="auto",
        help="Offload part of the BF16 model to CPU automatically on GPUs with less than 12 GiB VRAM.",
    )
    return parser


def _clean_result(value: object) -> str:
    text = str(value or "").strip()
    for marker in ("<|ref|>", "<|/ref|>", "<|det|>", "<|/det|>"):
        text = text.replace(marker, " ")
    return " ".join(text.split()).strip()


def main() -> int:
    args = _parser().parse_args()
    import torch
    from transformers import AutoModel, AutoTokenizer

    if not torch.cuda.is_available():
        raise RuntimeError("DeepSeek-OCR-2 requires an NVIDIA CUDA GPU")
    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    total_vram = torch.cuda.get_device_properties(0).total_memory
    quantization = (
        "offload"
        if args.quantization == "auto" and total_vram < 12 * 1024**3
        else args.quantization
    )
    if quantization == "auto":
        quantization = "none"
    load_error = None
    model = None
    for attention in ("sdpa", "eager"):
        try:
            load_options = {
                "trust_remote_code": True,
                "use_safetensors": True,
                "low_cpu_mem_usage": True,
                "_attn_implementation": attention,
            }
            if quantization == "offload":
                args.output.parent.mkdir(parents=True, exist_ok=True)
                device_map = {
                    "model.view_seperator": 0,
                    "model.embed_tokens": 0,
                    "model.sam_model": 0,
                    "model.qwen2_model": 0,
                    "model.projector": 0,
                    "model.norm": "cpu",
                    "lm_head": "cpu",
                }
                device_map.update(
                    {
                        f"model.layers.{index}": 0 if index < 8 else "cpu"
                        for index in range(12)
                    }
                )
                load_options.update(
                    {
                        "device_map": device_map,
                        "offload_folder": str(args.output.parent / ".deepseek-offload"),
                        "torch_dtype": torch.bfloat16,
                    }
                )
            else:
                load_options["torch_dtype"] = torch.bfloat16
            model = AutoModel.from_pretrained(
                args.model,
                **load_options,
            )
            break
        except Exception as exc:
            load_error = exc
    if model is None:
        raise RuntimeError(f"failed to load DeepSeek-OCR-2: {load_error}")
    model = model.eval()
    if quantization == "offload" and model.model.view_seperator.device.type == "meta":
        from safetensors import safe_open

        weights_path = Path(args.model) / "model-00001-of-000001.safetensors"
        with safe_open(weights_path, framework="pt", device="cpu") as weights:
            separator = weights.get_tensor("model.view_seperator")
        model.model.view_seperator = torch.nn.Parameter(
            separator.to(device="cuda", dtype=torch.bfloat16),
            requires_grad=False,
        )
    if quantization == "none":
        model = model.cuda()

    if args.manifest:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    elif args.input:
        manifest = {
            "items": [
                {
                    "id": "full",
                    "image_path": str(args.input),
                    "prompt": args.prompt,
                }
            ]
        }
    else:
        raise RuntimeError("provide --input or --manifest")
    results = []
    for item in manifest.get("items", []):
        record = {
            "id": str(item.get("id", "")),
            "source_text": str(item.get("source_text", "")),
            "text": "",
            "error": "",
        }
        try:
            prompt = str(item.get("prompt") or "<image>\nFree OCR.")
            value = model.infer(
                tokenizer,
                prompt=prompt,
                image_file=str(item["image_path"]),
                output_path=str(args.output.parent),
                base_size=args.base_size,
                image_size=args.image_size,
                crop_mode=False,
                save_results=False,
                eval_mode=True,
            )
            record["text"] = _clean_result(value)
        except torch.OutOfMemoryError as exc:
            torch.cuda.empty_cache()
            record["error"] = f"cuda_oom: {exc}"
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
            record["traceback"] = "\n".join(traceback.format_exc().splitlines()[-30:])
        results.append(record)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "engine": "deepseek-ai/DeepSeek-OCR-2",
                "quantization": quantization,
                "items": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
