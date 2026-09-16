@echo off
setlocal
cd /d C:\AI\ComfyUI_windows_portable
if not exist "ComfyUI\custom_nodes" mkdir "ComfyUI\custom_nodes"
if exist "ComfyUI\custom_nodes\ComfyUI-QwenVL-F" (
  echo QwenVL-F already exists.
) else (
  git clone https://github.com/id-fa/ComfyUI-QwenVL-F ComfyUI/custom_nodes/ComfyUI-QwenVL-F
)
python_embeded\python.exe -s -m pip install -r ComfyUI\custom_nodes\ComfyUI-QwenVL-F\requirements.txt
python_embeded\python.exe -s ComfyUI\custom_nodes\ComfyUI-QwenVL-F\tools\install_helper.py --python "C:\AI\ComfyUI_windows_portable\python_embeded\python.exe"
echo.
echo Restart ComfyUI after installing the CUDA llama-cpp wheel reported above.
pause
