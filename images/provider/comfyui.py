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
from main.prompts.consistency import consistency_prompt
from PIL import Image

logger = logging.getLogger("comfyui.image")


class ComfyUIImageGenerator:
    def __init__(
        self,
        *,
        base_url: str,
        workflow_path: str,
        input_path: str,
        timeout: int,
        poll_interval: float,
        log_workflow: bool = True,
        reactor_input_faces_index: str = "0,1,2,3,4,5,6,7",
        reactor_workflow_path: str = "images/workflows/image_reface_api.json",
        controlnet_openpose_model: str = "control_v11p_sd15_openpose.pth",
        controlnet_depth_model: str = "control_v11f1p_sd15_depth.pth",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.workflow_path = Path(workflow_path)
        self.input_path = Path(input_path)
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.log_workflow = log_workflow
        self.reactor_input_faces_index = reactor_input_faces_index
        self.reactor_workflow_path = Path(reactor_workflow_path)
        self.controlnet_openpose_model = controlnet_openpose_model
        self.controlnet_depth_model = controlnet_depth_model
        self.logger = logger

    @staticmethod
    def _make_body_lock_reference(image_bytes: bytes) -> bytes:
        """Create a body-focused reference for IP-Adapter."""
        try:
            from io import BytesIO
            with Image.open(BytesIO(image_bytes)) as src:
                src = src.convert("RGB")
                src = src.resize((512, 768), Image.Resampling.LANCZOS)
                crop_top = 120
                body = src.crop((0, crop_top, 512, 768))
                canvas = Image.new("RGB", (512, 768), (128, 128, 128))
                canvas.paste(body, (0, crop_top))
                out = BytesIO()
                canvas.save(out, format="PNG", optimize=True)
                return out.getvalue()
        except Exception:
            return image_bytes

    def _prepare_workflow(self, character: Character, prompt: str, reference_image: bytes | None, workflow_path: str | None = None, reactor_input_faces_index: str | None = None, body_reference_image: bytes | None = None, pose_image: bytes | None = None, pose_visual_reference_image: bytes | None = None, depth_image: bytes | None = None, depth_strength: float | None = None, generation_seed: int | None = None, generation_size: tuple[int, int] | None = None) -> dict[str, Any]:
        selected_workflow = Path(workflow_path) if workflow_path else self.workflow_path
        if not selected_workflow.exists():
            raise ProviderError(f"Не найден workflow ComfyUI: {selected_workflow}")
        workflow = json.loads(selected_workflow.read_text(encoding="utf-8"))

        # Allow individual image-generation entry points to override the canvas
        # without changing the shared workflow on disk. Reference generation uses
        # portrait 512x768; all other callers keep their workflow dimensions.
        if generation_size is not None:
            width, height = generation_size
            size_node = next(
                (node for node in workflow.values()
                 if isinstance(node, dict) and node.get("class_type") == "EmptyLatentImage"),
                None,
            )
            if isinstance(size_node, dict):
                size_inputs = size_node.setdefault("inputs", {})
                size_inputs["width"] = int(width)
                size_inputs["height"] = int(height)
                self.logger.info("[IMAGE SIZE] generation canvas=%sx%s", width, height)

        if workflow_path and Path(workflow_path).name == "image_generate_ipadapter_api.json":
            if not any(isinstance(n, dict) and n.get("class_type") == "IPAdapterAdvanced" for n in workflow.values()):
                raise ProviderError("IP-Adapter workflow does not contain IPAdapterAdvanced.")
            if not any(isinstance(n, dict) and n.get("class_type") == "IPAdapterModelLoader" for n in workflow.values()):
                raise ProviderError("IP-Adapter workflow does not contain IPAdapterModelLoader.")
        positive_node = workflow.get("2")
        if not isinstance(positive_node, dict) or positive_node.get("class_type") != "CLIPTextEncode":
            positive_node = next((node for node in workflow.values() if isinstance(node, dict) and node.get("class_type") == "CLIPTextEncode"), None)
        if not isinstance(positive_node, dict):
            raise ProviderError("В workflow отсутствует позитивный CLIPTextEncode.")
        inputs = positive_node.get("inputs")
        if not isinstance(inputs, dict) or "text" not in inputs:
            raise ProviderError("В позитивном CLIPTextEncode отсутствует поле inputs.text.")

        if workflow_path and Path(workflow_path).name == "image_generate_ipadapter_api.json":
            consistency_weights = {"low": 0.17, "medium": 0.24, "high": 0.30, "maximum": 0.36}
            body_weight = consistency_weights.get(character.consistency_strength, 0.40)
            for node in workflow.values():
                if isinstance(node, dict) and node.get("class_type") == "IPAdapterAdvanced":
                    node.setdefault("inputs", {})["weight"] = body_weight
                    node.setdefault("inputs", {})["start_at"] = 0.0
                    node.setdefault("inputs", {})["end_at"] = 0.40
                    break

        prompt_parts = [prompt.strip(), consistency_prompt(character.consistency_strength)]
        inputs["text"] = ", ".join(p for p in prompt_parts if p)

        negative_node = workflow.get("3")
        if not isinstance(negative_node, dict) or negative_node.get("class_type") != "CLIPTextEncode":
            clip_nodes = [node for node in workflow.values() if isinstance(node, dict) and node.get("class_type") == "CLIPTextEncode"]
            negative_node = clip_nodes[1] if len(clip_nodes) > 1 else None
        if isinstance(negative_node, dict) and isinstance(negative_node.get("inputs"), dict):
            negative = str(negative_node["inputs"].get("text", ""))
            if character.weight_profile == "Толстая":
                negative += ", slim body, skinny body, thin arms, narrow waist, flat abdomen, slender build"
            elif character.weight_profile == "Худая":
                negative += ", obese body, very heavy body, extremely wide waist"
            bust_negative = {
                1: "large bust, large breasts, full breasts, very large breasts, prominent cleavage, heavy chest",
                2: "very large breasts, extremely large bust, exaggerated breast volume",
                3: "flat chest, very small breasts, minimal bust",
                4: "flat chest, very small breasts, small bust, minimal breast volume",
            }.get(character.bust_size)
            if bust_negative:
                negative += ", " + bust_negative
            age_negative = {
                "Молодая": "deep wrinkles, pronounced crow's feet, deep nasolabial folds, sagging skin, age spots, elderly facial features",
                "Милф": "elderly facial features, deep severe wrinkles, heavy sagging skin, extreme age spots",
                "Зрелая": "very young face, youthful facial features, baby face, perfectly smooth skin, no wrinkles, unlined skin",
            }.get(character.age_category)
            if age_negative:
                negative += ", " + age_negative
            if body_reference_image:
                negative += ", reference background, studio background, gray backdrop, reference pose, reference clothing, underwear from reference, original outfit, original clothes"
            if prompt and any(token in prompt.lower() for token in (
                "wearing ", "dressed in ", "jacket", "jeans", "dress", "shirt", "blouse", "coat", "pants", "trousers", "shorts", "skirt", "sweater", "hoodie", "sneakers", "shoes", "boots", "heels", "bikini", "swimsuit", "lingerie", "underwear", "top", "t-shirt"
            )):
                negative += ", nude, naked, bare torso, exposed torso, exposed breasts, topless, missing clothing, incomplete clothing, transparent clothing"
            negative_node["inputs"]["text"] = negative

        if reference_image:
            self.input_path.mkdir(parents=True, exist_ok=True)
            filename = f"telegram_face_{character.id}.jpg"
            (self.input_path / filename).write_bytes(reference_image)
            face_node = workflow.get("8")
            if isinstance(face_node, dict) and face_node.get("class_type") == "LoadImage":
                face_node.setdefault("inputs", {})["image"] = filename

        if body_reference_image:
            self.input_path.mkdir(parents=True, exist_ok=True)
            body_filename = f"telegram_body_lock_{character.id}.png"
            body_lock_bytes = self._make_body_lock_reference(body_reference_image)
            (self.input_path / body_filename).write_bytes(body_lock_bytes)
            body_node = workflow.get("4")
            if isinstance(body_node, dict) and body_node.get("class_type") == "LoadImage":
                body_node.setdefault("inputs", {})["image"] = body_filename
                self.logger.info("[BODY LOCK 2.0] Using body-focused reference %s; face/background are intentionally de-emphasized before IP-Adapter.", body_filename)

        if pose_visual_reference_image is not None:
            self.logger.info("[POSE VISUAL REFERENCE] Original image received for orientation only; visual conditioning disabled to prevent appearance/style copying.")

        if pose_image is not None:
            self.input_path.mkdir(parents=True, exist_ok=True)
            pose_filename = f"telegram_pose_control_{uuid.uuid4().hex}.png"
            pose_path = self.input_path / pose_filename
            pose_path.write_bytes(pose_image)
            pose_node = workflow.get("10")
            if not isinstance(pose_node, dict) or pose_node.get("class_type") != "LoadImage":
                raise ProviderError("В start-frame workflow отсутствует LoadImage node 10.")
            pose_node.setdefault("inputs", {})["image"] = pose_filename
            control_node = workflow.get("11")
            if not isinstance(control_node, dict) or control_node.get("class_type") != "ControlNetLoader":
                raise ProviderError("В start-frame workflow отсутствует ControlNetLoader node 11.")
            control_node.setdefault("inputs", {})["control_net_name"] = self.controlnet_openpose_model
            openpose_apply = workflow.get("12")
            if isinstance(openpose_apply, dict) and openpose_apply.get("class_type") == "ControlNetApplyAdvanced":
                oi = openpose_apply.setdefault("inputs", {})
                oi["strength"] = 1.0
                oi["start_percent"] = 0.0
                oi["end_percent"] = 1.0
                oi["strength_model"] = 1.0
                oi["strength_clip"] = 1.0
            logger.info("[POSE CONTROL V8] OpenPose=%s exists=%s model=%s strength=1.0 end=1.0", pose_filename, pose_path.is_file(), self.controlnet_openpose_model)

            # Reference uses a clean single-pose OpenPose plus a synchronized depth map.
            # Give the body IP-Adapter enough influence to preserve the character's
            # body profile while leaving OpenPose in charge of exact joint geometry.
            if body_reference_image and depth_strength is not None and abs(float(depth_strength) - 0.15) < 1e-6:
                body_ipadapter = workflow.get("5")
                if isinstance(body_ipadapter, dict) and body_ipadapter.get("class_type") == "IPAdapterAdvanced":
                    bi = body_ipadapter.setdefault("inputs", {})
                    bi["weight"] = 0.30
                    bi["start_at"] = 0.0
                    bi["end_at"] = 0.65
                    self.logger.info("[BODY LOCK REFERENCE] IP-Adapter weight=0.30 end=0.65")

            depth_filename = None
            depth_path = None
            applied_depth_strength = None
            if depth_image is None:
                sampler = next((node for node in workflow.values() if isinstance(node, dict) and node.get("class_type") == "KSampler"), None)
                if isinstance(sampler, dict):
                    si = sampler.setdefault("inputs", {})
                    si["positive"] = ["12", 0]
                    si["negative"] = ["12", 1]
            if depth_image is not None:
                depth_filename = f"telegram_pose_depth_{uuid.uuid4().hex}.png"
                depth_path = self.input_path / depth_filename
                depth_path.write_bytes(depth_image)
                depth_load = workflow.get("13")
                depth_loader = workflow.get("14")
                depth_apply = workflow.get("15")
                if not all(isinstance(x, dict) for x in (depth_load, depth_loader, depth_apply)):
                    raise ProviderError("В start-frame workflow отсутствует Depth ControlNet branch (nodes 13/14/15).")
                if depth_load.get("class_type") != "LoadImage":
                    raise ProviderError("Depth node 13 должен быть LoadImage.")
                if depth_loader.get("class_type") != "ControlNetLoader":
                    raise ProviderError("Depth node 14 должен быть ControlNetLoader.")
                if depth_apply.get("class_type") != "ControlNetApplyAdvanced":
                    raise ProviderError("Depth node 15 должен быть ControlNetApplyAdvanced.")
                depth_load.setdefault("inputs", {})["image"] = depth_filename
                depth_loader.setdefault("inputs", {})["control_net_name"] = self.controlnet_depth_model
                di = depth_apply.setdefault("inputs", {})
                di["positive"] = ["12", 0]
                di["negative"] = ["12", 1]
                di["control_net"] = ["14", 0]
                di["image"] = ["13", 0]
                di["vae"] = ["1", 2]
                applied_depth_strength = max(0.0, min(1.0, float(depth_strength))) if depth_strength is not None else 0.65
                di["strength"] = applied_depth_strength
                di["start_percent"] = 0.0
                di["end_percent"] = 1.0
                di["strength_model"] = 1.0
                di["strength_clip"] = 1.0
                sampler = next((node for node in workflow.values() if isinstance(node, dict) and node.get("class_type") == "KSampler"), None)
                if isinstance(sampler, dict):
                    si = sampler.setdefault("inputs", {})
                    si["positive"] = ["15", 0]
                    si["negative"] = ["15", 1]
            if generation_seed is not None:
                sampler = next((node for node in workflow.values() if isinstance(node, dict) and node.get("class_type") == "KSampler"), None)
                if isinstance(sampler, dict):
                    sampler.setdefault("inputs", {})["seed"] = int(generation_seed)
            logger.info("[POSE DEPTH V8] Depth=%s exists=%s model=%s strength=%s end=1.0", depth_filename or "none", bool(depth_path and depth_path.is_file()), self.controlnet_depth_model, applied_depth_strength if applied_depth_strength is not None else "none")

        for node in workflow.values():
            if isinstance(node, dict) and node.get("class_type") == "KSampler":
                if generation_seed is None:
                    node.setdefault("inputs", {})["seed"] = random.randint(0, 2**32 - 1)
                break
        return workflow

    def _log_request(self, client_id: str, workflow: dict[str, Any]) -> None:
        if not self.log_workflow:
            return
        payload = {"prompt": workflow, "client_id": client_id}
        logger.info("\n========== COMFYUI IMAGE REQUEST ==========")
        logger.info("[ComfyUI][IMAGE] POST %s/prompt", self.base_url)
        logger.info("[ComfyUI][IMAGE] JSON PAYLOAD SENT:\n%s", json.dumps(payload, ensure_ascii=False, indent=2))
        logger.info("========== END COMFYUI IMAGE REQUEST ==========\n")

    async def _free_comfy_memory(self, session: aiohttp.ClientSession) -> None:
        try:
            async with session.post(f"{self.base_url}/free", json={"unload_models": True, "free_memory": True}) as response:
                if response.status < 300:
                    logger.info("[ComfyUI][IMAGE] Requested full model unload before ReActor workflow")
                else:
                    logger.warning("[ComfyUI][IMAGE] /free returned HTTP %s", response.status)
        except aiohttp.ClientError as exc:
            logger.warning("[ComfyUI][IMAGE] Failed to free ComfyUI memory: %s", exc)

    def _prepare_reface_workflow(self, image_filename: str, face_filename: str, reactor_input_faces_index: str | None = None) -> dict[str, Any]:
        if not self.reactor_workflow_path.exists():
            raise ProviderError(f"Не найден image ReActor workflow: {self.reactor_workflow_path}")
        workflow = json.loads(self.reactor_workflow_path.read_text(encoding="utf-8"))
        load_image = workflow.get("1")
        load_face = workflow.get("2")
        reactor = workflow.get("3")
        if not all(isinstance(x, dict) for x in (load_image, load_face, reactor)):
            raise ProviderError("В image ReActor workflow отсутствуют обязательные узлы 1/2/3.")
        load_image.setdefault("inputs", {})["image"] = image_filename
        load_face.setdefault("inputs", {})["image"] = face_filename
        ri = reactor.setdefault("inputs", {})
        ri["input_faces_index"] = reactor_input_faces_index or self.reactor_input_faces_index
        ri["source_faces_index"] = "0"
        ri["swap_model"] = "inswapper_128.onnx"
        ri["facedetection"] = "retinaface_resnet50"
        ri["face_restore_model"] = "none"
        ri["enabled"] = True
        return workflow

    async def reface(self, *, image: bytes, face_reference: bytes, reactor_input_faces_index: str | None = None) -> bytes:
        self.input_path.mkdir(parents=True, exist_ok=True)
        image_filename = f"telegram_reactor_input_{uuid.uuid4().hex}.png"
        face_filename = f"telegram_reactor_face_{uuid.uuid4().hex}.png"
        (self.input_path / image_filename).write_bytes(image)
        (self.input_path / face_filename).write_bytes(face_reference)
        workflow = self._prepare_reface_workflow(image_filename, face_filename, reactor_input_faces_index)
        client_id = str(uuid.uuid4())
        self._log_request(client_id, workflow)
        timeout = aiohttp.ClientTimeout(total=self.timeout + 30)
        try:
            return await self._run_reface(image_filename, face_filename, workflow, client_id, timeout)
        finally:
            for path in (self.input_path / image_filename, self.input_path / face_filename):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    logger.debug("[ComfyUI][IMAGE][REACTOR] Temporary file cleanup failed: %s", path)

    async def _run_reface(self, image_filename: str, face_filename: str, workflow: dict[str, Any], client_id: str, timeout: aiohttp.ClientTimeout) -> bytes:
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(f"{self.base_url}/prompt", json={"prompt": workflow, "client_id": client_id}) as response:
                    if response.status >= 300:
                        raise ProviderError(f"ComfyUI ReActor вернул HTTP {response.status}: {(await response.text())[:300]}")
                    payload = await response.json()
                prompt_id = payload.get("prompt_id")
                if not prompt_id:
                    raise ProviderError("ComfyUI ReActor не вернул prompt_id.")
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
                    if status.get("status_str") == "error":
                        raise ProviderError("ComfyUI ReActor workflow завершился с ошибкой.")
                    for node_output in result.get("outputs", {}).values():
                        if isinstance(node_output, list):
                            node_output = node_output[0] if node_output else {}
                        if not isinstance(node_output, dict):
                            continue
                        for info in node_output.get("images", []):
                            filename = info.get("filename")
                            if not filename:
                                continue
                            params = {"filename": filename, "subfolder": info.get("subfolder", ""), "type": info.get("type", "output")}
                            async with session.get(f"{self.base_url}/view", params=params) as ir:
                                if ir.status == 200:
                                    return await ir.read()
                raise ProviderError(f"ReActor не вернул изображение за {self.timeout} секунд.")
        except aiohttp.ClientError as exc:
            raise ProviderError(f"ComfyUI недоступен: {exc}") from exc

    async def generate(self, *, character: Character, prompt: str, reference_image: bytes | None, workflow_path: str | None = None, reactor_input_faces_index: str | None = None, body_reference_image: bytes | None = None, pose_image: bytes | None = None, pose_visual_reference_image: bytes | None = None, depth_image: bytes | None = None, depth_strength: float | None = None, generation_seed: int | None = None, generation_size: tuple[int, int] | None = None) -> bytes:
        workflow = self._prepare_workflow(character, prompt, reference_image, workflow_path=workflow_path, reactor_input_faces_index=reactor_input_faces_index, body_reference_image=body_reference_image, pose_image=pose_image, pose_visual_reference_image=pose_visual_reference_image, depth_image=depth_image, depth_strength=depth_strength, generation_seed=generation_seed, generation_size=generation_size)
        client_id = str(uuid.uuid4())
        self._log_request(client_id, workflow)
        timeout = aiohttp.ClientTimeout(total=self.timeout + 30)
        return await self._run_generate(workflow, client_id, timeout)

    async def _run_generate(self, workflow: dict[str, Any], client_id: str, timeout: aiohttp.ClientTimeout) -> bytes:
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(f"{self.base_url}/prompt", json={"prompt": workflow, "client_id": client_id}) as response:
                    if response.status >= 300:
                        details = await response.text()
                        raise ProviderError(f"ComfyUI вернул HTTP {response.status}: {details[:300]}")
                    payload = await response.json()
                prompt_id = payload.get("prompt_id")
                logger.info("[ComfyUI][IMAGE] prompt_id=%s", prompt_id)
                if not prompt_id:
                    raise ProviderError("ComfyUI не вернул prompt_id.")
                deadline = time.monotonic() + self.timeout
                while time.monotonic() < deadline:
                    await asyncio.sleep(self.poll_interval)
                    async with session.get(f"{self.base_url}/history/{prompt_id}") as history_response:
                        if history_response.status >= 300:
                            continue
                        history = await history_response.json()
                    result = history.get(prompt_id)
                    if not result:
                        continue
                    status_info = result.get("status", {})
                    status_str = status_info.get("status_str")
                    logger.info("[ComfyUI][IMAGE] prompt_id=%s status=%s", prompt_id, status_str)
                    if status_str == "error":
                        logger.error("[ComfyUI][IMAGE] error payload: %s", json.dumps(result, ensure_ascii=False, indent=2)[:10000])
                        raise ProviderError("ComfyUI завершил задачу с ошибкой.")
                    outputs = result.get("outputs", {})
                    for node_output in outputs.values():
                        if isinstance(node_output, list):
                            node_output = node_output[0] if node_output else {}
                        if not isinstance(node_output, dict):
                            continue
                        for image_info in node_output.get("images", []):
                            filename = image_info.get("filename")
                            if not filename:
                                continue
                            params = {"filename": filename, "subfolder": image_info.get("subfolder", ""), "type": image_info.get("type", "output")}
                            logger.info("[ComfyUI][IMAGE] downloading result %s", params)
                            async with session.get(f"{self.base_url}/view", params=params) as image_response:
                                if image_response.status == 200:
                                    return await image_response.read()
                raise ProviderError(f"ComfyUI не вернул изображение за {self.timeout} секунд.")
        except aiohttp.ClientError as exc:
            raise ProviderError(f"ComfyUI недоступен: {exc}") from exc
