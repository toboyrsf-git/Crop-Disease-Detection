"""
Model Export & Quantization Script
Exports trained model to ONNX and INT8 Quantized formats for edge deployment.
"""

import os
import json
import argparse

try:
    import torch
    from train_pipeline import build_mobilenetv3_model
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False


def export_to_onnx(model_path: str = "crop_mobilenetv3.pth", output_onnx: str = "model.onnx"):
    """
    Exports PyTorch model weights to ONNX format with dynamic batching.
    Input tensor: [BatchSize, 3, 224, 224]
    Output tensor: [BatchSize, 39] (Class Logits / Softmax probabilities)
    """
    print(f"[*] Starting ONNX model export...")
    if not TORCH_AVAILABLE:
        print("[!] PyTorch not found. Export script requires PyTorch.")
        return

    model = build_mobilenetv3_model(num_classes=39, pretrained=False)
    if os.path.exists(model_path):
        model.load_state_dict(torch.load(model_path, map_location="cpu"))
        print(f"[SUCCESS] Loaded weights from {model_path}")
    else:
        print(f"[Notice] Checkpoint {model_path} not found. Exporting initialized architecture.")

    model.eval()
    dummy_input = torch.randn(1, 3, 224, 224)

    torch.onnx.export(
        model,
        dummy_input,
        output_onnx,
        export_params=True,
        opset_version=14,
        do_constant_folding=True,
        input_names=["input_leaf_image"],
        output_names=["disease_logits"],
        dynamic_axes={
            "input_leaf_image": {0: "batch_size"},
            "disease_logits": {0: "batch_size"}
        }
    )
    print(f"[SUCCESS] Successfully exported ONNX model to {output_onnx}")
    print(f"[*] Model size: {os.path.getsize(output_onnx) / (1024 * 1024):.2f} MB")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export Crop Disease Model to ONNX")
    parser.add_argument("--checkpoint", type=str, default="models/crop_mobilenetv3.pth")
    parser.add_argument("--output", type=str, default="models/model.onnx")
    args = parser.parse_args()

    export_to_onnx(args.checkpoint, args.output)
