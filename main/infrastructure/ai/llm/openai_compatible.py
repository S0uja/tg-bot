import base64
import json

import aiohttp

from main.domain.errors import ProviderError
from main.domain.models import ImagePromptContext


# Shared instruction: the local Qwen model is used as a prompt engineer, not as a
# chat assistant. Every generation-related call must return a clean prompt tailored
# to the actual downstream model instead of commentary or generic prose.
PROMPT_ENGINE_BASE = (
    "You are a prompt engine for image and video generation. "
    "Convert the user's request into a concise English generation prompt. "
    "Preserve the requested subject, action, scene and intent. "
    "Do not invent people, objects, clothing, locations, poses or camera movement. "
    "Return only the prompt, with no explanation."
)

IMAGE_PROMPT_SYSTEM = (
    PROMPT_ENGINE_BASE + " "
    "Target: CyberRealistic SD 1.5 photorealistic image generation. "
    "Return ONLY valid JSON with exactly these string fields: subject, action, environment, composition, camera, lighting, atmosphere, details. "
    "Keep each field concise, factual and in English. "
    "Preserve the user's requested scene and intent. "
    "If structured pose or clothing constraints are supplied, do not invent or replace them; do not restate pose geometry in action. "
    "Do not describe body shape, bust size, age, hairstyle, hair color, facial identity or character profile; the application adds those separately. "
    "Do not add model, sampler, CFG, resolution, negative-prompt terms, reference-image instructions, or identity-lock instructions."
)

VIDEO_PROMPT_SYSTEM = (
    PROMPT_ENGINE_BASE + " "
    "Target: LTXV image-to-video. "
    "Describe the visible starting state and then one continuous, clearly visible requested motion. "
    "The source image is authoritative for identity, face, hair, body, clothing, environment, composition, framing, aspect ratio and lighting. "
    "Preserve those facts exactly. Do not change the source orientation or recompose the shot to another aspect ratio. "
    "Translate the action into physical movement, not a vague label: specify what body parts move, the direction of movement, "
    "the change of posture or position, and the beginning-to-end sequence. Make the requested action obvious and substantial, "
    "with natural but noticeable displacement. Do not invent extra actions. "
    "Use strong action verbs such as leans, turns, raises, lowers, reaches, steps, shifts, falls, sits, stands, lies down, "
    "and completes the motion when appropriate. Avoid words that weaken the requested action such as barely, subtly, almost, "
    "slightly or minimal unless the user explicitly asks for a very small movement. "
    "If camera movement is not explicitly requested, keep the camera static; do not invent zoom, dolly, tracking, pan, tilt or reframing. "
    "Write 60-100 English words focused on the requested motion, its amplitude and continuity."
)

CHARACTER_ANALYSIS_SYSTEM = (
    "Analyze the supplied reference image only for five adult character profile parameters and return ONLY valid JSON. "
    "Never return a face description or facial identity analysis. Never identify the person, infer ethnicity, or infer private/sensitive attributes. "
    "Do not invent details that are not visible. Use null for unknown/not visible values. "
    "Return parameters exactly with these Russian labels: "
    "weight_profile = Очень худая, Худая, Нормальная, Пышная, Толстая; "
    "bust_size = 1,2,3,4; age_category = Молодая, Милф, Зрелая; "
    "hairstyle = Длинные прямые, Длинные волнистые, Длинные кудрявые, Каре, Удлинённое каре, Каскад, "
    "Пикси, Высокий хвост, Низкий хвост, Коса, Пучок; "
    "hair_color = Чёрные, Тёмно-каштановые, Каштановые, Светло-каштановые, Блонд, Платиновый блонд, "
    "Рыжие, Тёмно-рыжие, Седые. "
    "Classify weight/bust only when enough of the body is visible; otherwise null. "
    "For bust, use only visible silhouette and do not guess when obscured. "
    "For age, choose only an adult category when clearly supported; never output a minor category. "
    "For hairstyle, choose the closest available option. "
    "Also return confidence values 0.0-1.0 for exactly these five fields. "
    "Do not output face shape, eyes, eyebrows, nose, lips, jawline, skin, distinctive features, pose, expression, clothing, accessories, lighting, background, identity or free-form description. "
    'JSON schema: {"parameters":{"weight_profile":null,"bust_size":null,"age_category":null,"hairstyle":null,"hair_color":null},'
    '"confidence":{"weight_profile":0.0,"bust_size":0.0,"age_category":0.0,"hairstyle":0.0,"hair_color":0.0}}'
)



CAMERA_STATIC_SUFFIX = (
    "camera completely static and locked in place, fixed camera position, fixed focal length, fixed perspective, "
    "unchanged framing from frame 0, unchanged aspect ratio and orientation, no zoom in, no zoom out, "
    "no dolly, no tracking, no pan, no tilt, no reframing, no camera angle change, no shot scale change, "
    "no crop change, preserve the same framing and approximately the same subject size throughout, "
    "preserve the background position relative to the frame, only the requested subject action changes"
)


def _explicit_camera_motion_requested(prompt: str) -> bool:
    """Return True only for clear user-requested camera motion."""
    import re

    text = prompt.lower().replace("ё", "е")
    patterns = (
        r"\b(?:camera|камера)\s+(?:moves?|moving|движется|двиг(?:ается|аться)|перемещается|следит|tracking)",
        r"\b(?:zoom|зум|приближ(?:ается|ение|ить)|отдал(?:яется|ение|ить)|наезд|отъезд)",
        r"\b(?:pan|панорам(?:а|ирует|ируетcя)|поворот камеры|камера поворач)",
        r"\b(?:dolly|tracking shot|камера следует|камера плавно движется)",
        r"\b(?:camera\s+(?:push|pull|pushes|pulls)\s+(?:in|out))\b",
    )
    return any(re.search(pattern, text) for pattern in patterns)



COMBINED_VIDEO_PROMPTS_SYSTEM = (
    "You are a prompt engine for a two-stage video pipeline. "
    "Return ONLY valid JSON with exactly two string fields: "
    "\"image_prompt\" and \"video_prompt\"." 
    "The image_prompt is for CyberRealistic SD 1.5 and must describe one coherent exact opening still frame. "
    "The video_prompt is for LTXV image-to-video and must describe one continuous visible motion starting from that frame. "
    "Preserve the user's subject, scene, clothing, pose, action and intent. "
    "Do not invent extra actions or camera movement. If camera movement is not requested, keep it static. "
    "Use concise English prompts; image_prompt 40-70 words, video_prompt 60-100 words."
)


class OpenAICompatibleLLM:
    def __init__(
        self,
        *,
        url: str,
        api_key: str,
        model: str,
        vision_model: str,
    ) -> None:
        self.url = url
        self.api_key = api_key
        self.model = model
        self.vision_model = vision_model

    async def _chat(self, payload: dict) -> dict:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            timeout = aiohttp.ClientTimeout(total=120)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(self.url, json=payload, headers=headers) as response:
                    if response.status >= 300:
                        details = await response.text()
                        raise ProviderError(
                            f"LLM вернул HTTP {response.status}: {details[:300]}"
                        )
                    return await response.json()
        except aiohttp.ClientError as exc:
            raise ProviderError(f"LLM недоступен: {exc}") from exc

    @staticmethod
    def _extract_text(result: dict, error_message: str) -> str:
        try:
            text = result["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(error_message) from exc
        if not text:
            raise ProviderError(error_message)
        return " ".join(text.split()).strip(" \"'“”‘’")

    async def analyze_character(self, image: bytes) -> dict:
        encoded = base64.b64encode(image).decode("ascii")
        payload = {
            "model": self.vision_model,
            "temperature": 0.1,
            "max_tokens": 512,
            "messages": [
                {"role": "system", "content": CHARACTER_ANALYSIS_SYSTEM},
                {"role": "user", "content": [
                    {"type": "text", "text": "Analyze this reference image and return the requested JSON profile."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}},
                ]},
            ],
        }
        result = await self._chat(payload)
        text = self._extract_text(result, "Vision LLM вернул ответ без анализа персонажа.")
        from characters.analysis import extract_json_object
        return extract_json_object(text)


    async def classify_scene_posture(self, scene: str) -> str:
        system = (
            "Classify the main requested body posture. Return ONLY valid JSON: "
            "{\"posture\":\"standing|sitting|lying|kneeling|all_fours|crouching|bent_over|unknown\"}. "
            "Choose the primary posture requested by the user. Use unknown if none is specified."
        )
        payload = {"model": self.model, "temperature": 0.0, "max_tokens": 64, "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": scene.strip()},
        ]}
        result = await self._chat(payload)
        text = self._extract_text(result, "LLM не определил позу сцены.")
        from characters.analysis import extract_json_object
        data = extract_json_object(text)
        posture = str(data.get("posture", "unknown")).strip().lower()
        allowed = {"standing", "sitting", "lying", "kneeling", "all_fours", "crouching", "bent_over", "unknown"}
        if posture not in allowed:
            raise ProviderError(f"LLM вернул недопустимую позу: {posture}")
        return posture

    async def select_pose_candidate(self, scene: str, candidates: list[dict]) -> int:
        system = (
            "Choose the single best pose candidate for the user's request. Return ONLY valid JSON: "
            "{\"index\":1}. The index MUST be one of the supplied candidates. "
            "Compare posture, arms, legs, support, framing and activity tags."
        )
        payload = {"model": self.model, "temperature": 0.0, "max_tokens": 64, "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": f"REQUEST:\n{scene.strip()}\n\nCANDIDATES:\n{json.dumps(candidates, ensure_ascii=False)}"},
        ]}
        result = await self._chat(payload)
        text = self._extract_text(result, "LLM не выбрал подходящую позу.")
        from characters.analysis import extract_json_object
        data = extract_json_object(text)
        try:
            index = int(data["index"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError("LLM вернул некорректный индекс позы.") from exc
        valid = {int(item["index"]) for item in candidates}
        if index not in valid:
            raise ProviderError(f"LLM вернул индекс позы вне списка: {index}")
        return index

    async def enhance_image_prompt(self, context: ImagePromptContext) -> str:
        user_parts = [
            f"USER IMAGE REQUEST: {context.scene.strip()}",
        ]
        if context.pose.strip():
            user_parts.append(f"STRUCTURED POSE CONSTRAINT: {context.pose.strip()}")
        if context.clothing.strip():
            user_parts.append(f"STRUCTURED CLOTHING CONSTRAINT: {context.clothing.strip()}")
        pose_metadata = getattr(context, 'pose_metadata', None)
        if pose_metadata:
            user_parts.append(f"POSE LIBRARY METADATA: {json.dumps(pose_metadata, ensure_ascii=False)}")
        user_parts.append(
            "Structured character profile (body/age/hair attributes) is authoritative and will be appended by the application. "
            "Do not guess or contradict it."
        )
        payload = {
            "model": self.model,
            "temperature": 0.15,
            "max_tokens": 128,
            "messages": [
                {"role": "system", "content": IMAGE_PROMPT_SYSTEM},
                {"role": "user", "content": "\n".join(user_parts)},
            ],
        }
        result = await self._chat(payload)
        return self._extract_text(result, "LLM вернул ответ без текста промпта.")



    async def build_video_prompts(self, prompt: str, start_frame_context: str) -> tuple[str, str]:
        payload = {
            "model": self.model,
            "temperature": 0.1,
            "max_tokens": 320,
            "messages": [
                {"role": "system", "content": COMBINED_VIDEO_PROMPTS_SYSTEM},
                {"role": "user", "content": (
                    f"VIDEO REQUEST:\n{prompt.strip()}\n\n"
                    f"OPENING FRAME REQUIREMENTS:\n{start_frame_context.strip()}\n\n"
                    "Return JSON only."
                )},
            ],
        }
        result = await self._chat(payload)
        # IMPORTANT: do not use _extract_text() here. It normalizes all whitespace,
        # which turns a multi-line Markdown JSON fence into one line and makes the
        # old fence remover delete the entire response (e.g. ```json {...} ```).
        try:
            raw = result["choices"][0]["message"]["content"]
            if not isinstance(raw, str) or not raw.strip():
                raise ValueError("empty LLM response")

            cleaned = raw.strip().lstrip("\ufeff")

            # Strip optional Markdown fences without assuming line breaks.
            if cleaned.startswith("```"):
                first_newline = cleaned.find("\n")
                if first_newline >= 0:
                    cleaned = cleaned[first_newline + 1:]
                else:
                    # Handles the compact form: ```json {...} ```
                    cleaned = cleaned[3:]
                    if cleaned.lower().startswith("json"):
                        cleaned = cleaned[4:]
                if cleaned.rstrip().endswith("```"):
                    cleaned = cleaned.rstrip()[:-3].rstrip()

            try:
                data = json.loads(cleaned)
            except json.JSONDecodeError:
                # Last-resort tolerant extraction: decode the first JSON object
                # embedded in the response. This handles harmless prose around JSON.
                start = cleaned.find("{")
                if start < 0:
                    raise
                data, _ = json.JSONDecoder().raw_decode(cleaned[start:])

            if not isinstance(data, dict):
                raise ValueError("video prompt response is not an object")
            if not isinstance(data.get("image_prompt"), str) or not isinstance(data.get("video_prompt"), str):
                raise ValueError("image_prompt and video_prompt must be strings")

            image_prompt = " ".join(data["image_prompt"].split()).strip(" \"'“”‘’")
            video_prompt = " ".join(data["video_prompt"].split()).strip(" \"'“”‘’")
        except Exception as exc:
            raise ProviderError("LLM вернул некорректный JSON для двух видео-промптов.") from exc
        if not image_prompt or not video_prompt:
            raise ProviderError("LLM вернул пустой image_prompt или video_prompt.")
        return image_prompt, video_prompt

    async def translate_video_prompt(self, prompt: str, image: bytes | None = None) -> str:
        """Turn text and, when available, the source image into an LTXV-ready prompt."""
        user_content: list[dict] = [
            {
                "type": "text",
                "text": (
                    "VIDEO REQUEST:\n"
                    f"{prompt.strip()}\n\n"
                    "Use the source image as the visual ground truth. Convert the requested action into a concrete, visible "
                    "beginning-to-end movement. State the main body movement, direction, posture change and noticeable amplitude. "
                    "Do not replace the action with a generic description and do not add unrelated actions. "
                    "If the user did not request camera movement, the camera must remain fixed."
                ),
            }
        ]
        if image:
            encoded = base64.b64encode(image).decode("ascii")
            user_content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{encoded}"},
                }
            )
        payload = {
            "model": self.vision_model if image else self.model,
            "temperature": 0.1,
            "max_tokens": 200,
            "messages": [
                {"role": "system", "content": VIDEO_PROMPT_SYSTEM},
                {"role": "user", "content": user_content},
            ],
        }
        result = await self._chat(payload)
        text = self._extract_text(result, "LLM вернул ответ без перевода промпта видео.")
        motion_suffix = (
            "clear and noticeable physical movement, visible beginning-to-end action, "
            "natural body displacement matching the requested action, complete the requested motion rather than only starting it"
        )
        if motion_suffix.lower() not in text.lower():
            text = f"{text}, {motion_suffix}"

        continuity_suffix = (
            "exact same face as the first frame, same facial identity, same facial proportions, "
            "same eyes, same nose, same lips, same jawline, same cheekbones, same hairline, "
            "preserve facial identity throughout the entire video, no facial reinterpretation, "
            "consistent natural skin tone throughout the entire video, stable skin color, "
            "consistent face appearance, consistent hand and face color from the first frame"
        )
        if continuity_suffix.lower() not in text.lower():
            text = f"{text}, {continuity_suffix}"

        # when the user describes only subject motion, lock the camera instead of
        # letting LTXV invent a zoom/pull-back to accommodate the action. Explicit camera
        # requests are left untouched. This is deterministic and therefore also survives
        # the second vision-grounding pass used by the two-stage video pipeline.
        if not _explicit_camera_motion_requested(prompt):
            if CAMERA_STATIC_SUFFIX.lower() not in text.lower():
                text = f"{text}, {CAMERA_STATIC_SUFFIX}"
        if len(text) > 1400:
            text = text[:1400].rsplit(".", 1)[0].strip() or text[:1400].strip()
        return text
