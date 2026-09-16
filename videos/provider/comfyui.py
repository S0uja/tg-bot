import asyncio
import json
import logging
import random
import time
import uuid
from pathlib import Path
from typing import Any

import aiohttp

from main.domain.errors import ProviderError
from main.domain.models import Character

logger = logging.getLogger("comfyui.video")


def _image_dimensions(image: bytes) -> tuple[int, int] | None:
    """Read common PNG/JPEG dimensions without adding a heavyweight imaging dependency."""
    if len(image) >= 24 and image[:8] == b"\x89PNG\r\n\x1a\n" and image[12:16] == b"IHDR":
        width = int.from_bytes(image[16:20], "big")
        height = int.from_bytes(image[20:24], "big")
        return width, height

    # Minimal JPEG SOF parser. Generated Telegram/ComfyUI images are normally PNG,
    # but this keeps aspect-ratio preservation working for JPEG source images too.
    if len(image) >= 4 and image[:2] == b"\xff\xd8":
        i = 2
        sof_markers = {
            *range(0xC0, 0xC4), *range(0xC5, 0xC8), *range(0xC9, 0xCC), *range(0xCD, 0xD0)
        }
        while i + 9 < len(image):
            if image[i] != 0xFF:
                i += 1
                continue
            while i < len(image) and image[i] == 0xFF:
                i += 1
            if i >= len(image):
                break
            marker = image[i]
            i += 1
            if marker in (0xD8, 0xD9):
                continue
            if i + 2 > len(image):
                break
            segment_length = int.from_bytes(image[i:i + 2], "big")
            if segment_length < 2 or i + segment_length > len(image):
                break
            if marker in sof_markers and segment_length >= 7:
                height = int.from_bytes(image[i + 3:i + 5], "big")
                width = int.from_bytes(image[i + 5:i + 7], "big")
                return width, height
            i += segment_length
    return None


def _video_dimensions_for_source(image: bytes) -> tuple[int, int]:
    """Return the project's fixed portrait video format: 512x768.

    Both Create Video and Animate Image must produce the same portrait frame
    size. The source image is used for composition, not for selecting a
    different output orientation.
    """
    return 512, 768


class ComfyUIVideoGenerator:
    def __init__(self, *, base_url: str, workflow_path: str, create_workflow_path: str | None = None, animate_workflow_path: str | None = None, decode_workflow_path: str = "videos/workflows/video_decode_api.json", decode_fallback_workflow_path: str = "videos/workflows/video_decode_tiled_api.json", input_path: str, timeout: int, poll_interval: float, log_workflow: bool = True, text_encoder_name: str = "t5xxl_fp8_e4m3fn.safetensors", reactor_workflow_path: str = "videos/workflows/video_reface_api.json") -> None:
        self.base_url = base_url.rstrip("/")
        self.workflow_path = Path(workflow_path)
        self.create_workflow_path = Path(create_workflow_path) if create_workflow_path else self.workflow_path
        self.animate_workflow_path = Path(animate_workflow_path) if animate_workflow_path else self.workflow_path
        self.decode_workflow_path = Path(decode_workflow_path)
        self.decode_fallback_workflow_path = Path(decode_fallback_workflow_path)
        self.input_path = Path(input_path)
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.log_workflow = log_workflow
        self.text_encoder_name = text_encoder_name
        self.reactor_workflow_path = Path(reactor_workflow_path)

    def _prepare_workflow(self, character: Character, prompt: str, reference_image: bytes, identity_image: bytes | None = None, duration_frames: int = 97, workflow_path: Path | None = None, strength: float | None = None) -> dict[str, Any]:
        selected_workflow = workflow_path or self.workflow_path
        if not selected_workflow.exists():
            raise ProviderError(f"Не найден workflow LTXV: {selected_workflow}")
        workflow = json.loads(selected_workflow.read_text(encoding="utf-8"))
        clip_node = workflow.get("38")
        if isinstance(clip_node, dict) and clip_node.get("class_type") == "CLIPLoader":
            clip_inputs = clip_node.setdefault("inputs", {})
            # Node 38 is the LTXV T5 text encoder. It must NOT point at the
            # LTXV diffusion checkpoint. Always overwrite the workflow value so
            # an old/exported workflow cannot silently select the wrong model.
            previous_clip = clip_inputs.get("clip_name")
            if previous_clip != self.text_encoder_name:
                logger.warning(
                    "[ComfyUI][VIDEO] Replacing node 38 text encoder %r with %r",
                    previous_clip,
                    self.text_encoder_name,
                )
            clip_inputs["clip_name"] = self.text_encoder_name
            logger.info(
                "[ComfyUI][VIDEO] LTXV text encoder node 38: %s; checkpoint node 44 remains workflow-defined",
                self.text_encoder_name,
            )
        self.input_path.mkdir(parents=True, exist_ok=True)
        filename = f"telegram_video_source_{character.id}.png"
        (self.input_path / filename).write_bytes(reference_image)
        load_node = workflow.get("78")
        if not isinstance(load_node, dict) or load_node.get("class_type") != "LoadImage":
            raise ProviderError("В LTXV workflow не найден LoadImage node 78.")
        load_node.setdefault("inputs", {})["image"] = filename
        # Fixed project video format for both I2V entry points.
        video_width, video_height = _video_dimensions_for_source(reference_image)
        ltxv_node = workflow.get("95")
        if isinstance(ltxv_node, dict):
            ltxv_inputs = ltxv_node.setdefault("inputs", {})
            # Official LTXV 0.9.8 multi-scale pipeline: render a smaller first
            # pass, latent-upscale it spatially, then run a short refinement pass.
            # 352x512 is chosen because the spatial upscaler produces ~528x768;
            # the decode stage center-crops that to the project's exact 512x768.
            if isinstance(workflow.get("103"), dict) and workflow.get("103", {}).get("class_type") == "LTXVLatentUpsamplerModelLoader":
                ltxv_inputs["width"] = 352
                ltxv_inputs["height"] = 512
                logger.info("[ComfyUI][VIDEO] Spatial refinement enabled: first pass 352x512 -> latent upscale -> 528x768 -> final crop 512x768")
            else:
                ltxv_inputs["width"] = video_width
                ltxv_inputs["height"] = video_height
        positive = workflow.get("6")
        if isinstance(positive, dict):
            positive.setdefault("inputs", {})["text"] = prompt
            logger.info("[ComfyUI][VIDEO] Final English prompt: %s", prompt)

        # V27: preserve the opening frame as strongly as the native LTXV I2V node allows.
        # Keep strength at 1.0 (maximum preservation); lowering it weakens frame-0 identity.
        ltxv_node = workflow.get("95")
        if isinstance(ltxv_node, dict) and ltxv_node.get("class_type") == "LTXVImgToVideo":
            inputs = ltxv_node.setdefault("inputs", {})
            video_width, video_height = _video_dimensions_for_source(reference_image)
            if isinstance(workflow.get("103"), dict) and workflow.get("103", {}).get("class_type") == "LTXVLatentUpsamplerModelLoader":
                inputs["width"] = 352
                inputs["height"] = 512
            else:
                inputs["width"] = video_width
                inputs["height"] = video_height
            logger.info(
                "[ComfyUI][VIDEO] Source aspect ratio preserved: %sx%s -> LTXV %sx%s",
                *_image_dimensions(reference_image) if _image_dimensions(reference_image) else ("?", "?"),
                video_width, video_height,
            )
            if strength is not None:
                inputs["strength"] = float(strength)
            # LTXV requires length = 8n + 1. The service converts user duration to this form.
            requested_frames = int(duration_frames)
            duration_frames = max(9, 1 + 8 * round((requested_frames - 1) / 8))
            inputs["length"] = duration_frames
            logger.info(
                "[ComfyUI][VIDEO] LTXV length FINAL: requested=%s -> node95.length=%s frames (~%.2fs at 24 FPS)",
                requested_frames, duration_frames, duration_frames / 24.0,
            )
            logger.info("[ComfyUI][VIDEO] LTXV image conditioning strength: %s", inputs.get("strength"))

        preprocess = workflow.get("82")
        if isinstance(preprocess, dict) and preprocess.get("class_type") == "LTXVPreprocess":
            preprocess.setdefault("inputs", {})["img_compression"] = 0
            logger.info("[ComfyUI][VIDEO] LTXV image compression: 0 (preserve facial detail)")
        noise = workflow.get("102")
        if isinstance(noise, dict):
            noise.setdefault("inputs", {})["noise_seed"] = random.randint(0, 2**32 - 1)
        return workflow

    async def _free_comfy_memory(self, session: aiohttp.ClientSession) -> None:
        try:
            async with session.post(f"{self.base_url}/free", json={"unload_models": True, "free_memory": True}) as response:
                if response.status < 300:
                    logger.info("[ComfyUI][VIDEO] Requested full model unload before ReActor workflow")
                else:
                    logger.warning("[ComfyUI][VIDEO] /free returned HTTP %s", response.status)
        except aiohttp.ClientError as exc:
            logger.warning("[ComfyUI][VIDEO] Failed to free ComfyUI memory: %s", exc)

    def _prepare_reface_workflow(self, video_filename: str, face_filename: str) -> dict[str, Any]:
        if not self.reactor_workflow_path.exists():
            raise ProviderError(f"Не найден video ReActor workflow: {self.reactor_workflow_path}")
        workflow = json.loads(self.reactor_workflow_path.read_text(encoding="utf-8"))
        load_video = workflow.get("1")
        load_face = workflow.get("2")
        reactor = workflow.get("3")
        combine = workflow.get("4")
        if not all(isinstance(x, dict) for x in (load_video, load_face, reactor, combine)):
            raise ProviderError("В video ReActor workflow отсутствуют обязательные узлы 1/2/3/4.")
        load_video.setdefault("inputs", {})["video"] = video_filename
        load_face.setdefault("inputs", {})["image"] = face_filename
        ri=reactor.setdefault("inputs", {})
        ri["input_image"]=["1",0]
        ri["source_image"]=["2",0]
        ri["input_faces_index"]="0"
        ri["source_faces_index"]="0"
        ri["swap_model"]="inswapper_128.onnx"
        ri["facedetection"]="retinaface_resnet50"
        ri["face_restore_model"]="none"
        ri["enabled"]=True
        combine.setdefault("inputs", {})["images"]=["3",0]
        combine["inputs"]["frame_rate"]=24
        return workflow

    async def reface(self, *, video: bytes, face_reference: bytes) -> bytes:
        self.input_path.mkdir(parents=True, exist_ok=True)
        video_filename=f"telegram_reactor_video_{uuid.uuid4().hex}.mp4"
        face_filename=f"telegram_reactor_face_{uuid.uuid4().hex}.png"
        (self.input_path/video_filename).write_bytes(video)
        (self.input_path/face_filename).write_bytes(face_reference)
        workflow=self._prepare_reface_workflow(video_filename, face_filename)
        client_id=str(uuid.uuid4())
        self._log_request(client_id, workflow)
        timeout=aiohttp.ClientTimeout(total=self.timeout + 30)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                # Unload LTXV/other models before ReActor to avoid VRAM pressure.
                # We intentionally do NOT call /free after ReActor, so its staged
                # weights remain reusable by ComfyUI dynamic VRAM.
                # Do not fully unload ComfyUI before ReActor. DynamicVRAM
                # will evict/swap what it needs and avoids a cold model reload.
                async with session.post(f"{self.base_url}/prompt", json={"prompt":workflow,"client_id":client_id}) as response:
                    if response.status>=300:
                        raise ProviderError(f"ComfyUI ReActor вернул HTTP {response.status}: {(await response.text())[:300]}")
                    payload=await response.json()
                prompt_id=payload.get("prompt_id")
                if not prompt_id:
                    raise ProviderError("ComfyUI ReActor не вернул prompt_id.")
                deadline=time.monotonic()+self.timeout
                while time.monotonic()<deadline:
                    await asyncio.sleep(self.poll_interval)
                    async with session.get(f"{self.base_url}/history/{prompt_id}") as hr:
                        if hr.status>=300: continue
                        history=await hr.json()
                    result=history.get(prompt_id)
                    if not result: continue
                    status=result.get("status",{})
                    if status.get("status_str")=="error":
                        logger.error("[ComfyUI][VIDEO][REACTOR] error: %s", json.dumps(result,ensure_ascii=False)[:10000])
                        raise ProviderError("ComfyUI ReActor video workflow завершился с ошибкой.")
                    for node_output in result.get("outputs",{}).values():
                        if not isinstance(node_output,dict): continue
                        for key in ("gifs","videos","images"):
                            for info in node_output.get(key,[]) or []:
                                filename=info.get("filename") if isinstance(info,dict) else None
                                if not filename: continue
                                params={"filename":filename,"subfolder":info.get("subfolder",""),"type":info.get("type","output")}
                                async with session.get(f"{self.base_url}/view",params=params) as mr:
                                    if mr.status==200: return await mr.read()
                raise ProviderError(f"ReActor не вернул видео за {self.timeout} секунд.")
        except aiohttp.ClientError as exc:
            raise ProviderError(f"ComfyUI недоступен: {exc}") from exc
        finally:
            for path in (self.input_path / video_filename, self.input_path / face_filename):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    logger.debug("[ComfyUI][VIDEO][REACTOR] Temporary file cleanup failed: %s", path)

    def _log_request(self, client_id: str, workflow: dict[str, Any]) -> None:
        if not self.log_workflow:
            return
        payload = {"prompt": workflow, "client_id": client_id}
        logger.info("\n========== COMFYUI VIDEO REQUEST ==========")
        logger.info("[ComfyUI][VIDEO] POST %s/prompt", self.base_url)
        logger.info("[ComfyUI][VIDEO] JSON PAYLOAD SENT:\n%s", json.dumps(payload, ensure_ascii=False, indent=2))
        logger.info("========== END COMFYUI VIDEO REQUEST ==========\n")

    async def _submit_and_wait(self, session: aiohttp.ClientSession, workflow: dict[str, Any], *, label: str, output_keys: tuple[str, ...]) -> tuple[dict[str, Any], dict[str, Any]]:
        client_id = str(uuid.uuid4())
        self._log_request(client_id, workflow)
        async with session.post(f"{self.base_url}/prompt", json={"prompt": workflow, "client_id": client_id}) as response:
            if response.status >= 300:
                raise ProviderError(f"ComfyUI {label} вернул HTTP {response.status}: {(await response.text())[:500]}")
            payload = await response.json()
        prompt_id = payload.get("prompt_id")
        logger.info("[ComfyUI][VIDEO][%s] prompt_id=%s", label, prompt_id)
        if not prompt_id:
            raise ProviderError(f"ComfyUI {label} не вернул prompt_id.")
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            await asyncio.sleep(self.poll_interval)
            async with session.get(f"{self.base_url}/history/{prompt_id}") as hr:
                if hr.status >= 300:
                    continue
                history = await hr.json()
            result = history.get(prompt_id)
            if not result:
                continue
            status = result.get("status", {})
            status_str = status.get("status_str")
            if status_str == "error":
                logger.error("[ComfyUI][VIDEO][%s] error: %s", label, json.dumps(result, ensure_ascii=False, indent=2)[:12000])
                raise ProviderError(f"ComfyUI {label} workflow завершился с ошибкой.")
            outputs = result.get("outputs", {})
            for node_output in outputs.values():
                if not isinstance(node_output, dict):
                    continue
                for key in output_keys:
                    items = node_output.get(key, []) or []
                    if items:
                        info = items[0]
                        if isinstance(info, dict) and info.get("filename"):
                            return result, info
        raise ProviderError(f"ComfyUI {label} не вернул результат за {self.timeout} секунд.")

    async def _download_view(self, session: aiohttp.ClientSession, info: dict[str, Any]) -> bytes:
        params = {
            "filename": info.get("filename"),
            "subfolder": info.get("subfolder", ""),
            "type": info.get("type", "output"),
        }
        async with session.get(f"{self.base_url}/view", params=params) as response:
            if response.status != 200:
                raise ProviderError(f"ComfyUI не смог отдать файл {params} (HTTP {response.status}).")
            return await response.read()

    def _prepare_decode_workflow(self, workflow_path: Path, latent_filename: str) -> dict[str, Any]:
        if not workflow_path.exists():
            raise ProviderError(f"Не найден workflow декодирования видео: {workflow_path}")
        workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
        load_node = workflow.get("1")
        if not isinstance(load_node, dict) or load_node.get("class_type") != "LoadLatent":
            raise ProviderError(f"В decode workflow {workflow_path} не найден LoadLatent node 1.")
        load_node.setdefault("inputs", {})["latent"] = latent_filename
        return workflow

    async def _decode_latent_to_video(self, session: aiohttp.ClientSession, latent_filename: str) -> bytes:
        logger.info("[ComfyUI][VIDEO][DECODE] Primary path: tiled VideoVAE decode")
        workflow = self._prepare_decode_workflow(self.decode_workflow_path, latent_filename)
        try:
            _, video_info = await self._submit_and_wait(
                session, workflow, label="DECODE_FAST", output_keys=("gifs", "videos", "images")
            )
        except ProviderError as exc:
            logger.warning("[ComfyUI][VIDEO][DECODE] Standard VAEDecode failed: %s", exc)
            logger.warning("[ComfyUI][VIDEO][DECODE] Falling back to tiled VideoVAE decode")
            await self._free_comfy_memory(session)
            fallback = self._prepare_decode_workflow(self.decode_fallback_workflow_path, latent_filename)
            _, video_info = await self._submit_and_wait(
                session, fallback, label="DECODE_TILED_FALLBACK", output_keys=("gifs", "videos", "images")
            )
        logger.info("[ComfyUI][VIDEO][DECODE] Downloading decoded video %s", video_info.get("filename"))
        return await self._download_view(session, video_info)

    async def generate(self, *, character: Character, prompt: str, reference_image: bytes | None, identity_image: bytes | None = None, duration_frames: int = 97, workflow_path: str | Path | None = None, strength: float | None = None) -> bytes:
        if not reference_image:
            raise ProviderError("Для LTXV требуется исходное изображение персонажа.")
        workflow = self._prepare_workflow(character, prompt, reference_image, identity_image, duration_frames, Path(workflow_path) if workflow_path else None, strength)
        timeout = aiohttp.ClientTimeout(total=self.timeout + 60)
        latent_filename = f"telegram_ltxv_latent_{uuid.uuid4().hex}.latent"
        # SaveLatent uses the filename prefix to create a root-level .latent file in output.
        save_node = workflow.get("110")
        if isinstance(save_node, dict) and save_node.get("class_type") == "SaveLatent":
            save_node.setdefault("inputs", {})["filename_prefix"] = latent_filename.removesuffix(".latent")
        else:
            raise ProviderError("В LTXV workflow не найден SaveLatent node 110.")
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                logger.info("[ComfyUI][VIDEO] Stage 1/2: LTXV sampling only; VideoVAE decode is deferred to a separate prompt")
                _, latent_info = await self._submit_and_wait(session, workflow, label="LTXV", output_keys=("latents",))
                logger.info("[ComfyUI][VIDEO] LTXV produced latent %s", latent_info.get("filename"))
                latent_bytes = await self._download_view(session, latent_info)
                # LoadLatent only enumerates .latent files in ComfyUI/input, so copy the
                # generated latent there before submitting the independent decode prompt.
                self.input_path.mkdir(parents=True, exist_ok=True)
                actual_name = Path(latent_info["filename"]).name
                (self.input_path / actual_name).write_bytes(latent_bytes)
                logger.info("[ComfyUI][VIDEO] Copied latent to ComfyUI input: %s", actual_name)
                # IMPORTANT: do NOT call /free here. The LTXV stage has just finished and
                # its checkpoint/VideoVAE may already be resident in ComfyUI's LRU cache.
                # Calling /free forces a cold VideoVAE preparation (the visible
                # "0 models unloaded" -> "VideoVAE ... 2378MB Staged" pause).
                # The decode is a separate prompt, so ComfyUI can reuse the cached VAE and
                # dynamically evict only what is necessary.
                logger.info(
                    "[ComfyUI][VIDEO] Stage 2/2: decoding latent without full /free; "
                    "reuse ComfyUI LRU VideoVAE cache"
                )
                result = await self._decode_latent_to_video(session, actual_name)
                logger.info(
                    "[ComfyUI][VIDEO] Decoded video payload: %d bytes (expected duration target %.2fs)",
                    len(result), duration_frames / 24.0,
                )
                await self._free_comfy_memory(session)
                return result
        except aiohttp.ClientError as exc:
            raise ProviderError(f"ComfyUI недоступен: {exc}") from exc
        finally:
            try:
                (self.input_path / latent_filename).unlink(missing_ok=True)
            except OSError:
                logger.debug("[ComfyUI][VIDEO] Temporary latent cleanup failed: %s", latent_filename)
