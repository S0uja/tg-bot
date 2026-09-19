import asyncio
import json
import logging
import random
import re
import time
import uuid
from pathlib import Path
from typing import Any

import aiohttp

from main.domain.errors import ProviderError
from main.domain.models import ImagePromptContext

logger = logging.getLogger("comfyui.qwen")

PROMPT_ENGINE_BASE = (
    "You are a prompt engine for image and video generation. "
    "Convert the user's request into a concise English generation prompt. "
    "Preserve the requested subject, action, scene and intent. "
    "Do not invent people, objects, clothing, locations, poses or camera movement. "
    "Return only the requested final text, with no explanation."
)
IMAGE_PROMPT_SYSTEM = PROMPT_ENGINE_BASE + " Target: CyberRealistic SD 1.5 photorealistic image generation. Return ONLY valid JSON with exactly these string fields: subject, action, environment, composition, camera, lighting, atmosphere, details. Keep each field concise, factual and in English. Preserve the user's requested scene and intent. If structured pose or clothing constraints are supplied, do not invent or replace them; do not restate pose geometry in action. Do not describe body shape, bust size, age, hairstyle, hair color, facial identity or character profile; the application adds those separately. Do not add model, sampler, CFG, resolution, negative-prompt terms, reference-image instructions, or identity-lock instructions."
VIDEO_PROMPT_SYSTEM = PROMPT_ENGINE_BASE + " Target: LTXV image-to-video. Describe the visible starting state and then one continuous, clearly visible requested motion. The source image is authoritative for identity, face, hair, body, clothing, environment, composition, framing, aspect ratio and lighting. Preserve those facts exactly. Translate the action into physical movement: specify what body parts move, direction, posture change and beginning-to-end sequence. Make the requested action obvious and substantial. Do not invent extra actions. If camera movement is not explicitly requested, keep the camera static. Write 60-100 English words focused on motion, amplitude and continuity."
CHARACTER_ANALYSIS_SYSTEM = """Analyze the supplied reference image only for the five character profile parameters below. Return ONLY valid JSON. Never return a face description or facial identity analysis. Never identify the person, infer ethnicity, or infer private/sensitive attributes. Do not invent details that are not visible. Use null for unknown/not visible values. The character is an adult.

JSON schema:
{
  "parameters": {
    "weight_profile": "Очень худая|Худая|Нормальная|Пышная|Толстая|null",
    "bust_size": 1|2|3|4|null,
    "age_category": "Молодая|Милф|Зрелая|null",
    "hairstyle": "Длинные прямые|Длинные волнистые|Длинные кудрявые|Каре|Удлинённое каре|Каскад|Пикси|Высокий хвост|Низкий хвост|Коса|Пучок|null",
    "hair_color": "Чёрные|Тёмно-каштановые|Каштановые|Светло-каштановые|Блонд|Платиновый блонд|Рыжие|Тёмно-рыжие|Седые|null"
  },
  "confidence": {
    "weight_profile": 0.0, "bust_size": 0.0, "age_category": 0.0, "hairstyle": 0.0, "hair_color": 0.0
  }
}

Rules: classify weight/bust only when enough of the body is visible; otherwise null. For bust, use only the visible silhouette and do not guess when obscured. For age, choose only an adult category when the image clearly supports it; never output a minor category. For hairstyle, select the closest available option. Do not output face shape, eyes, eyebrows, nose, lips, jawline, skin, distinctive features, pose, expression, clothing, accessories, lighting, background, or any free-form description."""


POSE_ORIENTATION_SYSTEM = """Analyze the supplied pose reference image for the subject's camera-facing orientation.
Return JSON only:
{"orientation":"front|back|left_side|right_side|three_quarter_front|three_quarter_back|unknown","face_visible":true|false,"confidence":0.0}
Use the whole visible subject and the camera viewpoint, not the limb coordinates alone.
"back" means the subject is primarily facing away from the camera; a visible back of the head/body is strong evidence.
"front" means the subject primarily faces the camera.
Use a side or three-quarter value when that is clearly the dominant orientation.
Do not infer orientation from the filename or folder name.
Do not describe the pose, clothing, attractiveness, identity, ethnicity, age, or other traits.
"""

POSE_METADATA_SYSTEM = """Analyze this image only as a reusable human-pose reference for image generation. It may be an OpenPose skeleton instead of a photograph; infer only the visible body geometry. Return ONLY valid JSON; do not identify the person or describe face, attractiveness, ethnicity, age, body shape, nudity, clothing details, background, or private traits.

JSON schema:
{
  "posture": "standing|sitting|lying|kneeling|all_fours|crouching|bent_over|unknown",
  "orientation": "front|back|left_side|right_side|three_quarter_front|three_quarter_back|unknown",
  "activity_tags": ["short English action or use tag, maximum 6"],
  "support": ["floor|bed|chair|wall|hands|knees|back|feet|unknown"],
  "arms": "brief factual arrangement, or unknown",
  "legs": "brief factual arrangement, or unknown",
  "framing": "full_body|upper_body|lower_body|partial|unknown",
  "keywords_ru": ["short Russian search tags, maximum 10"],
  "confidence": 0.0
}

Rules: describe only clearly visible pose geometry and physical action. Use unknown when uncertain. activity_tags and keywords_ru must be concise, lowercase, unique, and useful for matching a future request such as 'упражнение на полу'."""

CAMERA_STATIC_SUFFIX = "camera completely static and locked in place, fixed camera position, fixed focal length, fixed perspective, unchanged framing from frame 0, unchanged aspect ratio and orientation, no zoom in, no zoom out, no dolly, no tracking, no pan, no tilt, no reframing, no camera angle change, no shot scale change, no crop change, preserve the background position relative to the frame, only the requested subject action changes"
MOTION_SUFFIX = "clear and noticeable physical movement, visible beginning-to-end action, natural body displacement matching the requested action, complete the requested motion rather than only starting it"
CONTINUITY_SUFFIX = "exact same face as the first frame, same facial identity, same facial proportions, preserve facial identity throughout the entire video, consistent natural skin tone throughout the entire video, consistent face appearance"


def _explicit_camera_motion_requested(prompt: str) -> bool:
    text = prompt.lower().replace("ё", "е")
    return any(re.search(p, text) for p in (
        r"\b(?:camera|камера)\s+(?:moves?|moving|движется|двигается|перемещается|следит|tracking)",
        r"\b(?:zoom|зум|приближается|приближение|приблизить|отдаляется|отъезд|наезд)",
        r"\b(?:pan|панорама|панорамирует|поворот камеры|камера поворач)",
        r"\b(?:dolly|tracking shot|камера следует|камера плавно движется)\b",
    ))


class ComfyUIQwenLLM:
    """PromptEnhancer backed by the QwenVL GGUF node inside ComfyUI.

    The provider discovers the exact model name exposed by the installed QwenVL
    custom node, so workflows do not depend on one author's catalog naming.
    """
    node_type = "AILab_QwenVL_GGUF"

    def __init__(self, *, base_url: str, input_path: str, create_workflow_path: str,
                 vision_workflow_path: str, model_match: str, timeout: int,
                 poll_interval: float, log_workflow: bool = True) -> None:
        self.base_url = base_url.rstrip("/")
        self.input_path = Path(input_path)
        self.create_workflow_path = Path(create_workflow_path)
        self.vision_workflow_path = Path(vision_workflow_path)
        self.model_match = model_match.lower().replace(" ", "")
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.log_workflow = log_workflow
        self._model_name: str | None = None
        self._object_info: dict[str, Any] | None = None

    async def _get_object_info(self, session: aiohttp.ClientSession) -> dict[str, Any]:
        if self._object_info is not None:
            return self._object_info
        async with session.get(f"{self.base_url}/object_info/{self.node_type}") as response:
            if response.status >= 300:
                details = await response.text()
                raise ProviderError(f"ComfyUI не содержит QwenVL node {self.node_type}: HTTP {response.status}: {details[:300]}")
            data = await response.json()
        info = data.get(self.node_type)
        if not isinstance(info, dict):
            raise ProviderError(f"ComfyUI не вернул описание QwenVL node {self.node_type}.")
        self._object_info = info
        return info

    async def _resolve_model(self, session: aiohttp.ClientSession) -> str:
        if self._model_name:
            return self._model_name
        info = await self._get_object_info(session)
        required = (info.get("input", {}) or {}).get("required", {})
        model_spec = required.get("model_name")
        choices = model_spec[0] if isinstance(model_spec, list) and model_spec else []
        choices = [str(x) for x in choices]
        for choice in choices:
            normalized = choice.lower().replace(" ", "")
            if self.model_match in normalized:
                self._model_name = choice
                logger.info("[ComfyUI][QWEN] Using model: %s", choice)
                return choice
        # Also allow a direct exact model name when the node exposes it.
        if self.model_match in (x.lower().replace(" ", "") for x in choices):
            self._model_name = next(x for x in choices if self.model_match == x.lower().replace(" ", ""))
            return self._model_name
        available = ", ".join(choices[:30]) or "<none>"
        raise ProviderError(
            f"Qwen3-VL модель не найдена в ComfyUI. Ищу '{self.model_match}'. "
            f"Доступные модели: {available}"
        )

    @staticmethod
    def _set_if_present(inputs: dict[str, Any], name: str, value: Any) -> None:
        if name in inputs:
            inputs[name] = value

    @staticmethod
    def _find_qwen_node(workflow: dict[str, Any], node_type: str) -> tuple[str, dict[str, Any]]:
        for node_id, node in workflow.items():
            if isinstance(node, dict) and node.get("class_type") == node_type:
                return str(node_id), node
        raise ProviderError(f"В Qwen workflow отсутствует {node_type} node.")

    @staticmethod
    def _find_load_image_node(workflow: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        for node_id, node in workflow.items():
            if isinstance(node, dict) and node.get("class_type") == "LoadImage":
                return str(node_id), node
        raise ProviderError("В vision Qwen workflow отсутствует LoadImage node.")

    @staticmethod
    def _find_text_output_node(workflow: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
        for node_id, node in workflow.items():
            if not isinstance(node, dict):
                continue
            if node.get("class_type") in {"SaveText", "PreviewAny"}:
                return str(node_id), node
        return None

    async def _build_workflow(
        self,
        session: aiohttp.ClientSession,
        workflow_path: Path,
        custom_prompt: str,
        image_filename: str | None,
    ) -> dict[str, Any]:
        if not workflow_path.exists():
            raise ProviderError(f"Не найден Qwen workflow: {workflow_path}")

        workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
        qwen_id, qwen = self._find_qwen_node(workflow, self.node_type)
        inputs = qwen.setdefault("inputs", {})

        model_name = await self._resolve_model(session)
        self._set_if_present(inputs, "model_name", model_name)
        self._set_if_present(inputs, "custom_prompt", custom_prompt)
        self._set_if_present(inputs, "preset_prompt", "🖼️ Detailed Description")
        self._set_if_present(inputs, "device", "auto")
        self._set_if_present(inputs, "max_tokens", 256)
        self._set_if_present(inputs, "keep_model_loaded", False)
        self._set_if_present(inputs, "seed", random.randint(1, 2**32 - 1))

        if image_filename:
            load_id, load = self._find_load_image_node(workflow)
            load.setdefault("inputs", {})["image"] = image_filename
            self._set_if_present(inputs, "image", [load_id, 0])

        output = self._find_text_output_node(workflow)
        if output is None:
            raise ProviderError("В Qwen workflow отсутствует текстовый output node (SaveText/PreviewAny).")

        output_id, output_node = output
        output_inputs = output_node.setdefault("inputs", {})
        if output_node.get("class_type") == "SaveText":
            output_inputs["text"] = [qwen_id, 0]
            output_inputs["filename_prefix"] = f"qwen_prompt_{uuid.uuid4().hex}"
            if "format" in output_inputs:
                output_inputs["format"] = "txt"
        elif output_node.get("class_type") == "PreviewAny":
            output_inputs["source"] = [qwen_id, 0]

        return workflow

    async def _run(self, prompt: str, image: bytes | None, workflow_path: Path, *, preset_prompt: str = "🖼️ Detailed Description", max_tokens: int = 256) -> str:
        self.input_path.mkdir(parents=True, exist_ok=True)
        image_filename = None
        if image is not None:
            image_filename = f"telegram_qwen_{uuid.uuid4().hex}.png"
            (self.input_path / image_filename).write_bytes(image)
        timeout = aiohttp.ClientTimeout(total=self.timeout + 30)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                workflow = await self._build_workflow(session, workflow_path, prompt, image_filename)
                qwen_id, qwen = self._find_qwen_node(workflow, self.node_type)
                qinputs = qwen.setdefault("inputs", {})
                self._set_if_present(qinputs, "preset_prompt", preset_prompt)
                self._set_if_present(qinputs, "max_tokens", max_tokens)
                client_id = str(uuid.uuid4())
                if self.log_workflow:
                    safe_log = json.dumps({"prompt": workflow, "client_id": client_id}, ensure_ascii=False, indent=2)
                    logger.info("[ComfyUI][QWEN] Request:\n%s", safe_log[:16000])
                async with session.post(f"{self.base_url}/prompt", json={"prompt": workflow, "client_id": client_id}) as response:
                    if response.status >= 300:
                        raise ProviderError(f"ComfyUI Qwen вернул HTTP {response.status}: {(await response.text())[:500]}")
                    payload = await response.json()
                prompt_id = payload.get("prompt_id")
                if not prompt_id:
                    raise ProviderError("ComfyUI Qwen не вернул prompt_id.")
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
                        logger.error("[ComfyUI][QWEN] error: %s", json.dumps(result, ensure_ascii=False)[:12000])
                        raise ProviderError("ComfyUI Qwen workflow завершился с ошибкой.")
                    for node_output in result.get("outputs", {}).values():
                        if not isinstance(node_output, dict):
                            continue
                        for info in node_output.get("images", []) or []:
                            if not isinstance(info, dict) or not info.get("filename"):
                                continue
                            params = {"filename": info["filename"], "subfolder": info.get("subfolder", ""), "type": info.get("type", "output")}
                            async with session.get(f"{self.base_url}/view", params=params) as vr:
                                if vr.status == 200:
                                    text = (await vr.read()).decode("utf-8", errors="replace").strip()
                                    if text:
                                        return " ".join(text.split()).strip(" \"'“”‘’")
                    # Some SaveText versions expose text metadata instead of images.
                    for node_output in result.get("outputs", {}).values():
                        if isinstance(node_output, dict) and isinstance(node_output.get("text"), list):
                            values = node_output["text"]
                            if values and isinstance(values[0], str) and values[0].strip():
                                return " ".join(values[0].split()).strip(" \"'“”‘’")
                raise ProviderError(f"ComfyUI Qwen не вернул текст за {self.timeout} секунд.")
        except aiohttp.ClientError as exc:
            raise ProviderError(f"ComfyUI недоступен: {exc}") from exc
        finally:
            if image_filename:
                try:
                    (self.input_path / image_filename).unlink(missing_ok=True)
                except OSError:
                    pass

    async def chat(self, prompt: str) -> str:
        """Generate a conversational reply through the local Qwen3-VL GGUF workflow."""
        return await self._run(
            prompt,
            None,
            self.create_workflow_path,
            # custom_prompt fully replaces the preset inside AILab_QwenVL_GGUF;
            # keep a valid combo-box value here for ComfyUI compatibility.
            preset_prompt="🖼️ Simple Description",
            max_tokens=384,
        )

    async def analyze_character(self, image: bytes) -> dict:
        text = await self._run(
            CHARACTER_ANALYSIS_SYSTEM, image, self.vision_workflow_path,
            preset_prompt="🖼️ Detailed Description", max_tokens=512,
        )
        from characters.analysis import extract_json_object
        return extract_json_object(text)


    async def analyze_pose_orientation(self, image: bytes) -> dict:
        text = await self._run(
            POSE_ORIENTATION_SYSTEM,
            image,
            self.vision_workflow_path,
            preset_prompt="🖼️ Detailed Description",
            max_tokens=128,
        )
        try:
            return json.loads(text)
        except (TypeError, ValueError):
            # Recover a JSON object if the vision node added harmless prose.
            match = re.search(r"\{.*\}", text, flags=re.S)
            if match:
                try:
                    return json.loads(match.group(0))
                except (TypeError, ValueError):
                    pass
        raise ProviderError(f"Qwen не вернул корректный анализ ориентации позы: {text[:300]}")

    async def analyze_pose_metadata(self, image: bytes) -> dict:
        text = await self._run(
            POSE_METADATA_SYSTEM,
            image,
            self.vision_workflow_path,
            preset_prompt="🖼️ Detailed Description",
            max_tokens=384,
        )
        from characters.analysis import extract_json_object
        return extract_json_object(text)

    async def classify_scene_posture(self, scene: str) -> str:
        system = (
            "Classify the main requested body posture. Return ONLY valid JSON: "
            "{\"posture\":\"standing|sitting|lying|kneeling|all_fours|crouching|bent_over|unknown\"}. "
            "Choose the primary posture requested by the user. Use unknown if none is specified."
        )
        text = await self._run(system + "\n\nUSER SCENE:\n" + scene.strip(), None, self.create_workflow_path, max_tokens=64)
        from characters.analysis import extract_json_object
        data = extract_json_object(text)
        posture = str(data.get("posture", "unknown")).strip().lower()
        allowed = {"standing", "sitting", "lying", "kneeling", "all_fours", "crouching", "bent_over", "unknown"}
        if posture not in allowed:
            raise ProviderError(f"Qwen вернул недопустимую позу: {posture}")
        return posture

    async def select_pose_candidate(self, scene: str, candidates: list[dict]) -> int:
        system = (
            "Choose the single best pose candidate for the user's request. Return ONLY valid JSON: "
            "{\"index\":1}. The index MUST be one of the supplied candidates. "
            "Compare posture, arms, legs, support, framing and activity tags."
        )
        text = await self._run(
            system + "\n\nREQUEST:\n" + scene.strip()
            + "\n\nCANDIDATES:\n" + json.dumps(candidates, ensure_ascii=False),
            None, self.create_workflow_path, max_tokens=128,
        )
        from characters.analysis import extract_json_object
        data = extract_json_object(text)
        try:
            index = int(data["index"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError("Qwen вернул некорректный индекс позы.") from exc
        valid = {int(item["index"]) for item in candidates}
        if index not in valid:
            raise ProviderError(f"Qwen вернул индекс позы вне списка: {index}")
        return index

    async def enhance_image_prompt(self, context: ImagePromptContext) -> str:
        parts = [f"USER IMAGE REQUEST: {context.scene.strip()}"]
        if context.pose.strip(): parts.append(f"STRUCTURED POSE CONSTRAINT: {context.pose.strip()}")
        if context.clothing.strip(): parts.append(f"STRUCTURED CLOTHING CONSTRAINT: {context.clothing.strip()}")
        pose_metadata = getattr(context, 'pose_metadata', None)
        if pose_metadata:
            parts.append(f"POSE LIBRARY METADATA: {json.dumps(pose_metadata, ensure_ascii=False)}")
        parts.append("Structured character profile is authoritative and will be appended by the application. Do not guess or contradict it.")
        return await self._run(IMAGE_PROMPT_SYSTEM + "\n\n" + "\n".join(parts), None, self.create_workflow_path)


    async def translate_video_prompt(self, prompt: str, image: bytes | None = None) -> str:
        user = (
            VIDEO_PROMPT_SYSTEM + "\n\nVIDEO REQUEST:\n" + prompt.strip() +
            "\n\nUse the source image as visual ground truth. Convert the requested action into concrete, visible beginning-to-end movement. "
            "Do not replace the action with a generic description. If camera movement is not requested, the camera must remain fixed."
        )
        text = await self._run(user, image, self.vision_workflow_path)
        if MOTION_SUFFIX.lower() not in text.lower(): text = f"{text}, {MOTION_SUFFIX}"
        if CONTINUITY_SUFFIX.lower() not in text.lower(): text = f"{text}, {CONTINUITY_SUFFIX}"
        if not _explicit_camera_motion_requested(prompt) and CAMERA_STATIC_SUFFIX.lower() not in text.lower():
            text = f"{text}, {CAMERA_STATIC_SUFFIX}"
        return text[:1400].rsplit(".", 1)[0].strip() if len(text) > 1400 else text
