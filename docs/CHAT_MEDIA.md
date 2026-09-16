# Character chat media

The character chat can optionally send generated media selected by Qwen3-VL.

Supported types:
- `photo` — generated character photo/selfie.
- `video_note` — short generated video converted to a square Telegram video note.
- `none` — normal text reply.

Media is intentionally optional. The chat model is instructed to use it only when the
conversation naturally calls for showing/sending something; normal messages remain text-only.

For a `video_note`, the bot generates a character image first, animates that exact image
with the existing LTXV Animate Image pipeline, then converts the portrait result to a
512x512 H.264 video note for Telegram.
