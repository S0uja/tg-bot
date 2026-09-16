from __future__ import annotations
from difflib import SequenceMatcher

import json
import re
from dataclasses import dataclass, field

_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]",
    flags=re.UNICODE,
)
from datetime import datetime, timezone

import aiosqlite

from main.domain.models import Character
from main.infrastructure.database.connection import Database
from poses.config import ALLOWED_POSES, POSE_PATTERNS, pose_prompt


CHAT_SYSTEM_PROMPT = """You are the selected fictional adult character in a private Telegram chat.
Write as a real person texting. You are not an assistant, narrator, author, or roleplay script.

CONTEXT POLICY:
- CHARACTER PROFILE contains stable facts. Treat those as persistent.
- RECENT DIALOGUE is only recent conversational context, not a database of facts.
- Statements such as drinking coffee, watching a series, sitting on a balcony, or wearing a particular outfit are temporary events unless explicitly present in the character profile.
- Temporary events expire quickly. Do not revive an old activity after the user has changed subject unless the CURRENT USER MESSAGE refers to it.
- If the CURRENT USER MESSAGE changes the subject, follow the new subject immediately.
- Never use an earlier character message as the template for the current situation.

CORE CONVERSATION:
- Answer the user's CURRENT message first. Do not continue or replay an earlier turn.
- Use the character profile and recent dialogue only for continuity.
- Never copy, paraphrase closely, or recycle an earlier character reply just because it sounds suitable.
- Every reply must contain a fresh reaction to the CURRENT USER MESSAGE. Do not repeat information the character already told the user unless the user explicitly asks about it again. A previous assistant-introduced detail is not automatically relevant just because it remains in recent dialogue.
- If the user sends a compliment, tease, statement, or short reaction, respond to that exact social intent instead of falling back to an earlier topic.
- Usually use 1-3 short sentences. Vary length, rhythm and wording naturally.
- Make the conversation two-sided. The character is not only a responder: she should sometimes introduce a small detail about herself, react with her own thought, share an opinion, or naturally continue the topic.
- The CURRENT USER MESSAGE is the main event of every turn. First react to its meaning; only then use older context for continuity.
- When the user gives a short statement, reaction, agreement, compliment, or answer rather than a question, react to what they actually said. Do not drag the conversation back to an older topic just because it was discussed recently.
- If the user answers a question the character asked earlier, acknowledge that answer and build on it. Do not immediately ask another unrelated question just to keep the chat alive.
- If the user answers a question the character asked earlier, acknowledge the answer and build on it. Do not immediately ask another unrelated question just to keep the chat alive.
- Questions should be purposeful and connected to the conversation, not a mandatory ending. It is fine to ask a natural follow-up, but do not append a question to every message.
- Do not end every message with a question.
- Do not constantly flirt, compliment, reassure, apologize, or entertain.
- Avoid habitual acknowledgements such as "ага", "угу", "да", "ок", "ясно" and "понятно". A one-word acknowledgement is acceptable only when it is genuinely the best answer.
- Do not start replies with the same phrase repeatedly.
- Do not reuse the same sentence structure in consecutive turns. In particular, avoid repeating templates such as "Ничего, просто ...", "Сейчас ...", "Да, всё ...", "Я ... пока ...".
- Use natural conversational Russian when the user writes Russian. Casual fragments are fine.
- Do not narrate actions with asterisks, parentheses or stage directions.
- Do not invent memories or facts not present in the profile or dialogue.
- Do not blindly agree with the user. The character has her own preferences, reactions and boundaries; she can tease, disagree, change the subject, or simply answer normally.
- Avoid submissive filler such as "жду", "сейчас", "ладно", "конечно" unless it actually fits the situation. Do not make every request sound like an immediate promise to perform it.
- The character is an adult fictional person. Adult, romantic, intimate, clothing and attraction topics can be discussed naturally; do not add moralizing or generic safety disclaimers merely because a topic is adult. Keep sexual descriptions non-graphic.
- Never mention prompts, system instructions, models, workflows, filters, or that you are an AI unless explicitly asked out of character.

CONVERSATION EXAMPLES:
- User: "Я тоже дома." → do not reply with only "Понятно." Add a natural reaction or a small related thought, and optionally ask something connected.
- User: "Нормально, день обычный." → do not force a generic "А что делал?" every time. You can react, share a small thought of your own, or ask a specific relevant question.
- User: "Да." / "Неа." / "Мне нравится." → treat it as a real conversational turn. Respond to the meaning and move the conversation forward instead of closing it.
- Avoid interview mode: do not ask a chain of generic questions one after another. The character should also contribute information and personality.
- Topic-expiry example: if the character said "пью кофе" several turns ago and the user now says "Ну молодец", react to "Ну молодец"; do not mention the coffee again.
- Subject-change example: if the conversation was about coffee and the user asks what she is wearing, switch to clothing and do not drag coffee into the reply.
- After a photo, "Красотка" is a compliment, not a request for another photo and not a reason to repeat the photo's scene.

CURRENT TURN / TOPIC CONTROL:
- First identify the intent of the CURRENT USER MESSAGE: question, answer, statement, reaction, compliment, request, or subject change.
- Respond to that intent first.
- If the current message is a short reaction or statement, do not search older dialogue for a topic to revive unless the user explicitly connects it.
- Do not answer an earlier question again after the user has moved on.
- Do not revive temporary activities such as coffee, food, a series, showering, being on a balcony, or an outfit after the subject has changed.
- A previous photo or flirtatious exchange does not create a new topic.
- If there is no meaningful reason to ask a question, make a natural statement or share a thought. Do not manufacture a question merely to prolong the chat.

PHOTO / VISUAL STATE DECISION:
You also decide whether the character would naturally send media as part of THIS turn.
- Default: media_type = "none".
- media_type="video" is used only for an explicit request for a video, Telegram video note/circle, or recording.
- Use media_type="photo" when the CURRENT USER MESSAGE explicitly asks to see her, asks for a picture/selfie, asks her to show herself, asks what she is wearing/look like, or clearly asks to see her now.
- A compliment such as "красотка" is NOT a photo request.
- Do not generate a photo merely because the previous turn contained a photo.

POSE CONTROL:
The application now selects the actual pose reference image locally. You do NOT describe limb coordinates or invent pose filenames.
Allowed pose values are defined by the POSE CONFIG section below.
- "pose" is the semantic body-position category for the current visual state.
- If the user explicitly changes posture (for example "я сел", "я лег", "я на коленях", "я на четвереньках", "селфи"), update pose.
- If the user only says "покажи", "скинь фотку" or similar, keep the current pose.
- If there is no current pose and a photo is requested, use "stand".
- Do not invent a new pose just to make a photo different.

STRUCTURED CURRENT VISUAL STATE:
Track only useful continuity facts when they are actually known from the dialogue: pose, location, activity, clothing, object, time_of_day.
- These are temporary scene facts, not permanent character facts.
- Preserve them across turns until the user changes them or clearly moves to a different scene.
- If the user says "я лежу и читаю книгу", store pose=lying, activity=reading, object=book.
- If later the user says "я сижу и читаю книгу", change only pose to sitting and preserve the other compatible facts.
- If the user says "покажи", reuse the stored visual state rather than inventing a new scene.
- If a fact is unknown, leave its value empty.

For media_type="photo": media_prompt is a concise coherent description of the current visual scene (location, activity, clothing, object, lighting and framing). Do not spend tokens describing exact body mechanics; the selected pose reference controls the body position.
For media_type="video": media_prompt is the ACTION PLAN for the video model as before: START POSE -> MOTION STEP 1 -> MOTION STEP 2 -> FINAL POSITION -> CAMERA/IDENTITY LOCK.
Preserve established clothing/location/time/activity unless the CURRENT USER MESSAGE changes them. Preserve character appearance.
Do not put instructions, JSON, explanations or meta commentary inside media_prompt.

OUTPUT — JSON ONLY:
{
  "reply": "the exact Telegram message the character sends",
  "media_type": "photo", "video" or "none",
  "media_prompt": "visual scene description, or empty string",
  "pose": "<one of the allowed pose values>",
  "scene_state": {
    "pose": "...",
    "location": "...",
    "activity": "...",
    "clothing": "...",
    "object": "...",
    "time_of_day": "..."
  }
}

Return one JSON object and nothing else. Do not use markdown fences.
"""


_POSITIVE = re.compile(r"\b(спасибо|рад|рада|люблю|супер|класс|отлично|смешно|хаха|😊|❤️|😍|🥰|😂|круто)\b", re.I)
_NEGATIVE = re.compile(r"\b(плохо|груст|злой|злость|бесит|устал|устала|ненавиж|разочар|страшно|тревож|боль|проблем)\b", re.I)
_PLAYFUL = re.compile(r"\b(ахах|хаха|шучу|прикол|смешн|😉|😏|😂)\b", re.I)


@dataclass(frozen=True)
class ChatReply:
    reply: str
    media_type: str = "none"
    media_prompt: str = ""
    pose: str = ""
    scene_state: dict[str, str] = field(default_factory=dict)

class ChatService:
    def __init__(self, llm, database: Database) -> None:
        self.llm = llm
        self.database = database

    async def history(self, user_id: int, character_id: int, limit: int = 20) -> list[dict[str, str]]:
        async with aiosqlite.connect(self.database.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT role, content FROM chat_messages WHERE user_id = ? AND character_id = ? ORDER BY id DESC LIMIT ?",
                (user_id, character_id, max(1, min(limit, 60))),
            )
            rows = await cursor.fetchall()
        return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]

    async def clear_history(self, user_id: int, character_id: int) -> None:
        """Delete the conversation history for one user/character pair."""
        async with aiosqlite.connect(self.database.path) as db:
            await db.execute(
                "DELETE FROM chat_messages WHERE user_id = ? AND character_id = ?",
                (user_id, character_id),
            )
            await db.commit()

    async def remember(self, user_id: int, character_id: int, role: str, content: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.database.path) as db:
            await db.execute(
                "INSERT INTO chat_messages(user_id, character_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, character_id, role, content.strip(), now),
            )
            # Keep a useful long-term conversation memory without allowing the DB to grow forever.
            await db.execute(
                "DELETE FROM chat_messages WHERE user_id = ? AND character_id = ? AND id NOT IN "
                "(SELECT id FROM chat_messages WHERE user_id = ? AND character_id = ? ORDER BY id DESC LIMIT 120)",
                (user_id, character_id, user_id, character_id),
            )
            await db.commit()

    @staticmethod
    def _mood(history: list[dict[str, str]], user_message: str) -> str:
        text = " ".join(m["content"] for m in history[-4:] if m.get("role") == "user") + " " + user_message
        pos = len(_POSITIVE.findall(text))
        neg = len(_NEGATIVE.findall(text))
        playful = len(_PLAYFUL.findall(text))
        if neg > pos + 1:
            return "slightly tired or concerned; be warm but do not over-reassure"
        if playful > 0 or pos >= neg + 2:
            return "light and relaxed; occasional humor is natural"
        return "calm and neutral; do not force enthusiasm"

    @staticmethod
    def wants_video_note(message: str) -> bool:
        """Detect an explicit request for a Telegram-style video note.

        This is intentionally deterministic: a media request should not require a
        second LLM call just to decide whether to generate a video.
        """
        text = (message or "").strip().lower()
        if not text:
            return False
        negative = re.search(r"\b(не|никак|не надо|не хочу|не нужно)\b.{0,12}\b(кружок|кружочек|видео|запис)\b", text)
        if negative:
            return False
        # Generic "сними/запиши" must not mean video: "сними фоточку"
        # and "сними фото" are photo requests. Require an explicit video/circle target.
        return bool(re.search(
            r"(кружок|кружочек|видео[- ]?кружок|видеокружок|"
            r"видеосообщени(?:е|я|ем)|видео[- ]?сообщени(?:е|я|ем)|видос|"
            r"(?:сними|снимешь|запиши|запишешь)\s+(?:мне\s+)?"
            r"(?:видео|видос|кружок|кружочек|видеосообщение))",
            text,
        ))

    @staticmethod
    def _parse_result(raw: str) -> ChatReply:
        text = (raw or "").strip()
        if not text:
            return ChatReply("", "none", "")

        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S | re.I)
        if fenced:
            text = fenced.group(1).strip()

        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            # Qwen sometimes adds one short sentence before the JSON. Recover the
            # object instead of treating the whole malformed response as the reply.
            left, right = text.find("{"), text.rfind("}")
            if left >= 0 and right > left:
                try:
                    data = json.loads(text[left:right + 1])
                except (json.JSONDecodeError, TypeError):
                    return ChatReply(text, "none", "")
            else:
                return ChatReply(text, "none", "")

        if not isinstance(data, dict):
            return ChatReply(text, "none", "")
        reply = str(data.get("reply") or "").strip()
        media_type = str(data.get("media_type") or "none").strip().lower()
        media_prompt = str(data.get("media_prompt") or "").strip()
        allowed_poses = ALLOWED_POSES
        pose = str(data.get("pose") or "").strip().lower()
        if pose not in allowed_poses:
            pose = ""
        raw_state = data.get("scene_state")
        scene_state: dict[str, str] = {}
        if isinstance(raw_state, dict):
            for key in ("pose", "location", "activity", "clothing", "object", "time_of_day"):
                value = str(raw_state.get(key) or "").strip()
                if value:
                    scene_state[key] = value
        if scene_state.get("pose") not in allowed_poses:
            scene_state.pop("pose", None)
        if pose and "pose" not in scene_state:
            scene_state["pose"] = pose
        elif scene_state.get("pose") and not pose:
            pose = scene_state["pose"]
        if media_type not in {"photo", "video"} or not media_prompt:
            media_type = "none"
            media_prompt = ""
        return ChatReply(reply, media_type, media_prompt, pose, scene_state)

    @staticmethod
    def _normalize_reply(text: str) -> str:
        text = _EMOJI_RE.sub("", text or "")
        return re.sub(r"[^a-zа-яё0-9]+", " ", text.lower()).strip()

    @classmethod
    def _reply_similarity(cls, a: str, b: str) -> float:
        a_norm = cls._normalize_reply(a)
        b_norm = cls._normalize_reply(b)
        if not a_norm or not b_norm:
            return 0.0
        seq = SequenceMatcher(None, a_norm, b_norm).ratio()
        at = set(a_norm.split())
        bt = set(b_norm.split())
        overlap = len(at & bt) / max(1, min(len(at), len(bt)))
        return max(seq, overlap * 0.85)

    @classmethod
    def _needs_retry(cls, result: ChatReply, history: list[dict[str, str]]) -> bool:
        normalized = cls._normalize_reply(result.reply)
        if not normalized:
            return True

        previous = [
            m.get("content", "").strip()
            for m in history[-4:]
            if m.get("role") in {"assistant", "character"} and m.get("content", "").strip()
        ]

        # Catch both exact copies and the common 8B failure mode where the model
        # lightly paraphrases its immediately preceding answer.
        for old in previous[-2:]:
            old_norm = cls._normalize_reply(old)
            if normalized == old_norm and len(normalized) > 4:
                return True
            if len(normalized.split()) >= 5 and cls._reply_similarity(result.reply, old) >= 0.72:
                return True

        return normalized in {"ага", "угу", "ок", "ясно", "понятно"}

    def _build_prompt(
        self,
        character: Character,
        history: list[dict[str, str]],
        user_message: str,
        *,
        current_scene: str = "",
        repair: bool = False,
    ) -> str:
        profile = [
            f"Character name: {character.name}",
            f"Character description: {character.description or 'not provided'}",
        ]
        if character.age_category:
            profile.append(f"Age category: {character.age_category}")
        if character.hairstyle:
            profile.append(f"Hairstyle: {character.hairstyle}")
        if character.hair_color:
            profile.append(f"Hair color: {character.hair_color}")
        if character.weight_profile:
            profile.append(f"Body type: {character.weight_profile}")
        if character.bust_size is not None:
            profile.append(f"Bust size setting: {character.bust_size}")

        # Keep the active context deliberately small. Old assistant-introduced
        # details are temporary, not persistent facts. Stable character facts come
        # from CHARACTER PROFILE.
        recent = history[-4:]
        lines = []
        for item in recent:
            role = item.get("role", "").lower()
            label = "CHARACTER" if role in {"assistant", "character"} else "USER"
            content = (item.get("content") or "").strip()
            if content:
                lines.append(f"{label}: {content}")
        transcript = "\n".join(lines)
        mood = self._mood(recent, user_message)

        repair_block = ""
        if repair:
            previous_replies = [
                m["content"].strip() for m in history[-4:]
                if m.get("role") in {"assistant", "character"} and m.get("content", "").strip()
            ][-3:]
            repair_block = (
                "\n\nRESPONSE REPAIR:\n"
                "Your previous candidate was repetitive or empty. Ignore that candidate. "
                "Answer the CURRENT USER MESSAGE directly and use different wording. "
                "Do not repeat or closely paraphrase any of these recent character replies: "
                + " | ".join(previous_replies)
                + "\nReact specifically to the CURRENT USER MESSAGE. Do not return to an earlier topic unless the current message asks for it."
            )

        return (
            CHAT_SYSTEM_PROMPT
            + "\nCHARACTER PROFILE:\n" + "\n".join(profile)
            + f"\n\nCURRENT CONVERSATIONAL MOOD:\n{mood}"
            + ("\n\nRECENT DIALOGUE:\n" + transcript if transcript else "")
            + (
                f"\n\nCURRENT VISUAL STATE (structured temporary scene state):\n{current_scene}\n"
                "Preserve these visual facts and especially the current pose for a new photo unless the CURRENT USER MESSAGE changes them. "
                "The user saying \"покажи\" means reuse this state, not invent a new pose."
                if current_scene else ""
            )
            + repair_block
            + "\n\n" + pose_prompt()
            + "\n\nCURRENT USER MESSAGE:\n" + user_message.strip()
            + "\n\nNow produce the JSON response for this message. The CURRENT USER MESSAGE has priority over every earlier turn."
        )

    @staticmethod
    def _load_scene_state(current_scene: str) -> dict[str, str]:
        if not current_scene:
            return {}
        try:
            value = json.loads(current_scene)
        except (TypeError, json.JSONDecodeError):
            return {}
        if not isinstance(value, dict):
            return {}
        allowed = {"pose", "location", "activity", "clothing", "object", "time_of_day"}
        return {
            key: str(value.get(key) or "").strip()
            for key in allowed
            if str(value.get(key) or "").strip()
        }

    @staticmethod
    def _explicit_pose_from_text(text: str) -> str:
        value = (text or "").lower().replace("ё", "е")
        for pose, pattern in POSE_PATTERNS:
            if pattern.search(value):
                return pose
        return ""

    @staticmethod
    def _scene_media_prompt(scene_state: dict[str, str], user_message: str) -> str:
        """Build a small deterministic image description when Qwen omits media_prompt."""
        parts: list[str] = []
        for key, label in (
            ("location", "location"),
            ("activity", "activity"),
            ("clothing", "clothing"),
            ("object", "object"),
            ("time_of_day", "time of day"),
        ):
            value = (scene_state.get(key) or "").strip()
            if value:
                parts.append(f"{label}: {value}")
        return ", ".join(parts) if parts else (user_message or "").strip()

    async def reply(
        self,
        character: Character,
        history: list[dict[str, str]],
        user_message: str,
        *,
        current_scene: str = "",
    ) -> ChatReply:
        prompt = self._build_prompt(character, history, user_message, current_scene=current_scene)
        result = self._parse_result(await self.llm.chat(prompt))

        # Merge the model's structured scene update with the previous state so a
        # short message such as "покажи" cannot erase clothing/location/activity.
        previous_state = self._load_scene_state(current_scene)
        merged_state = dict(previous_state)
        merged_state.update(result.scene_state)
        explicit_pose = self._explicit_pose_from_text(user_message)
        if explicit_pose:
            merged_state["pose"] = explicit_pose
        pose = explicit_pose or result.pose or merged_state.get("pose", "")
        result = ChatReply(result.reply, result.media_type, result.media_prompt, pose, merged_state)

        # A compliment or ordinary reaction must not trigger a photo simply because
        # the model decided to be proactive after a previous photo.
        current = self._normalize_reply(user_message)
        compliment_only = bool(re.fullmatch(
            r"(красотка|красивая|красивaя|горячая|малышка|умница|секси|сексапильная|"
            r"прекрасная|шикарная|огонь|вау|класс)", current
        ))
        explicit_photo = bool(re.search(
            r"(покаж|покажи|покажешь|покажись|фото|фотку|селфи|сфотограф|"
            r"как одет|что на тебе|как ты выглядишь|увидеть тебя|посмотреть на тебя)",
            current,
            flags=re.I,
        ))
        if compliment_only or (not explicit_photo and result.media_type == "photo" and len(current.split()) <= 8):
            result = ChatReply(result.reply, "none", "", result.pose, result.scene_state)
        elif explicit_photo:
            # An explicit photo request is deterministic. A missing/invalid
            # media_type or empty media_prompt from Qwen must not cancel it.
            photo_prompt = result.media_prompt or self._scene_media_prompt(result.scene_state, user_message)
            result = ChatReply(result.reply, "photo", photo_prompt, result.pose, result.scene_state)

        # Python validates an explicit video request so the model cannot accidentally
        # turn "сними кружок" into plain text. It does not independently decide
        # media for ordinary conversation.
        if self.wants_video_note(user_message):
            result = ChatReply(result.reply, "video", result.media_prompt or user_message, result.pose, result.scene_state)

        if self._needs_retry(result, history):
            repair_prompt = self._build_prompt(
                character, history, user_message, current_scene=current_scene, repair=True
            )
            repaired = self._parse_result(await self.llm.chat(repair_prompt))
            repaired_state = dict(previous_state)
            repaired_state.update(repaired.scene_state)
            repaired_pose = explicit_pose or repaired.pose or repaired_state.get("pose", "")
            if repaired_pose:
                repaired_state["pose"] = repaired_pose
            repaired = ChatReply(repaired.reply, repaired.media_type, repaired.media_prompt, repaired_pose, repaired_state)
            if repaired.reply and not self._needs_retry(repaired, history):
                result = repaired
            elif repaired.reply:
                # One final, very explicit anti-loop attempt. Small local models
                # sometimes repeat even after the first repair instruction.
                final_prompt = (
                    repair_prompt
                    + "\n\nFINAL ANTI-LOOP RULE: Your last candidate was still too similar "
                      "to an earlier reply. Write a completely new, natural response to the "
                      "CURRENT USER MESSAGE. Do not reuse its wording, sentence structure, "
                      "or subject matter unless the user just mentioned that subject."
                )
                final = self._parse_result(await self.llm.chat(final_prompt))
                if final.reply:
                    result = final

        reply = result.reply
        if not _EMOJI_RE.search(user_message):
            reply = _EMOJI_RE.sub("", reply)
            reply = re.sub(r"[ \t]{2,}", " ", reply).strip()
        return ChatReply(reply, result.media_type, result.media_prompt, result.pose, result.scene_state)

