"""Audio transcription via Groq Whisper API (not an LLM tool — used by telegram.py)."""

import logging
import requests

from agent.config import cfg

logger = logging.getLogger(__name__)


def transcribe_audio(file_path: str) -> str:
    """Transcribe an audio file using Groq Whisper API. Returns the transcription text."""
    with open(file_path, "rb") as f:
        resp = requests.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {cfg.groq_api_key}"},
            files={"file": f},
            data={"model": "whisper-large-v3"},
            timeout=30,
        )
    resp.raise_for_status()
    text = resp.json().get("text", "")
    logger.info("Audio transcribed: %s chars", len(text))
    return text
