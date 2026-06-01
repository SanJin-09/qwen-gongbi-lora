---
license: other
base_model: Qwen/Qwen-Image-Edit-2511
library_name: diffsynth
tags:
- lora
- qwen-image-edit
- image-to-image
- gongbi
- chinese-painting
---

# Qwen-Image-Edit-2511 Gongbi LoRA v1

LoRA trained for converting portrait and landscape images into traditional Chinese gongbi painting style.

## Base Model

- Qwen/Qwen-Image-Edit-2511

## Training Summary

- Dataset: 403 image-edit pairs
- Categories: portrait and landscape
- Epochs: 2
- Dataset repeat: 10
- LoRA rank: 16
- Max pixels: 524288
- Training framework: DiffSynth-Studio

## Main File

- `qwen_image_edit_2511_gongbi_lora_v1.safetensors`

## Intended Use

Image-to-image style conversion toward traditional Chinese gongbi painting aesthetics.

## Notes

Use with Qwen-Image-Edit-2511 compatible DiffSynth-Studio inference.
