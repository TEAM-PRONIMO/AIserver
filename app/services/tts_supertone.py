"""
Supertone TTS 통합 모듈.

LLM 피드백 텍스트(mild/spicy)를 한국어 음성으로 합성.

캐릭터별 voice/style 고정 (점수와 무관):
  mild  → 다정한 햄스터  (현재 voice placeholder: Anna, style "happy")
  spicy → 빈정대는 햄스터 (현재 voice placeholder: Bert, style "angry")

⚠️ 햄스터 캐릭터에 맞는 voice ID / pitch / speed / style 은
   디테일 확정 시 VOICE_PRESETS 값을 교체.
"""
from __future__ import annotations

import base64
import os
from typing import Any, Dict

import httpx
from dotenv import load_dotenv
from fastapi import HTTPException

load_dotenv()


# ── Supertone API ─────────────────────────────────────────────────────────
_API_BASE  = "https://supertoneapi.com"
_TTS_MODEL = "sona_speech_1"
_TIMEOUT_S = 30.0


# ── 캐릭터 프리셋 (mode → 고정 voice/style) ──────────────────────────────
VOICE_PRESETS: Dict[str, Dict[str, Any]] = {
    "mild": {
        "voice_id":   "259d4ac1ecf560c0f76e08",   # Anna (placeholder)
        "voice_name": "Anna",
        "style":      "happy",
        "voice_settings": {
            "pitch_shift":    0,
            "pitch_variance": 1.0,
            "speed":          1.0,
        },
    },
    "spicy": {
        "voice_id":   "816bc977b4111a3034146a",   # Bert (placeholder)
        "voice_name": "Bert",
        "style":      "angry",
        "voice_settings": {
            "pitch_shift":    -1,
            "pitch_variance": 1.3,
            "speed":          1.05,
        },
    },
}


async def synthesize(text: str, tone: str) -> Dict[str, Any]:
    """
    Supertone API 로 한국어 TTS 합성.

    Args:
      text : 합성할 한국어 텍스트
      tone : "mild" 또는 "spicy"

    Returns:
      {audio_base64, audio_format, voice_id, voice_name, style}
    """
    api_key = os.getenv("SUPERTONE_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="SUPERTONE_API_KEY 가 .env 에 설정되지 않았습니다.",
        )

    preset = VOICE_PRESETS.get(tone)
    if not preset:
        raise HTTPException(status_code=400, detail=f"알 수 없는 tone: {tone}")

    payload = {
        "text":           text,
        "language":       "ko",
        "style":          preset["style"],
        "model":          _TTS_MODEL,
        "voice_settings": preset["voice_settings"],
    }
    url     = f"{_API_BASE}/v1/text-to-speech/{preset['voice_id']}"
    headers = {
        "x-sup-api-key": api_key,
        "Content-Type":  "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            resp = await client.post(url, headers=headers, json=payload)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Supertone 호출 실패: {e}")

    if resp.status_code != 200:
        detail = resp.text[:500] if resp.text else f"status={resp.status_code}"
        raise HTTPException(
            status_code=502,
            detail=f"Supertone API 오류 ({resp.status_code}): {detail}",
        )

    return {
        "audio_base64": base64.b64encode(resp.content).decode("ascii"),
        "audio_format": resp.headers.get("content-type", "audio/wav"),
        "voice_id":     preset["voice_id"],
        "voice_name":   preset["voice_name"],
        "style":        preset["style"],
    }
