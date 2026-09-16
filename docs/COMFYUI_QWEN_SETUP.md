# ComfyUI Qwen3-VL setup

The bot uses the **ComfyUI-QwenVL** GGUF node and Qwen3-VL 8B Q4_K_M locally. Prompt generation no longer uses LM Studio.

## Model

Place these files under the directory exposed by ComfyUI-QwenVL:

```text
ComfyUI/models/llm/GGUF/Qwen/Qwen3-VL-8B-Instruct-GGUF/
  Qwen3VL-8B-Instruct-Q4_K_M.gguf
  mmproj-Qwen3VL-8B-Instruct-F16.gguf
```

The bot resolves the exact model name from the QwenVL node's `/object_info` endpoint.

## Workflows

`qwen_prompt_create_api.json` converts user text into a concise English generation prompt.

`qwen_prompt_vision_api.json` receives the actual generated/source image and converts the requested action into a concrete LTXV motion prompt.

Both workflows use the standard `AILab_QwenVL_GGUF` node and `SaveText` as the API output.

## Python

Qwen3-VL GGUF requires a vision-capable `llama-cpp-python` build. The normal PyPI package is not sufficient for the Qwen vision handlers.

The bot itself only needs the Python packages in `requirements.txt`; `llama-cpp-python` is provided by the ComfyUI embedded Python environment.
