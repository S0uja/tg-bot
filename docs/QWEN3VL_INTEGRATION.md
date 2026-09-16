# Qwen3-VL integration

The prompt pipeline is now fully local through ComfyUI-QwenVL.

## Flow

Create Video:
1. User request
2. Qwen3-VL text prompt
3. CyberRealistic start-frame generation
4. Qwen3-VL vision pass on the generated start frame
5. LTXV I2V

Animate Image:
1. Existing image
2. Qwen3-VL vision pass on that image
3. LTXV I2V

Smart Prompt Builder is not used.

## Required ComfyUI model

- Qwen3VL-8B-Instruct-Q4_K_M.gguf
- mmproj-Qwen3VL-8B-Instruct-F16.gguf

The QwenVL node must expose `AILab_QwenVL_GGUF`.

The ComfyUI embedded Python must contain a vision-capable `llama-cpp-python` build with the Qwen3-VL chat handler.
