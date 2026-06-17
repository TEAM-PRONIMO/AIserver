"""
PRONIMO AI 서버 라우트.

엔드포인트:
  - POST /analyze       : 발음 분석 + 2줄 한국어 텍스트
  - POST /feedback-wav  : analysis_text → mild + spicy 햄스터 wav
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from app.schemas.request import (
    AnalyzeRequest,
    AnalyzeResponse,
    FeedbackWavRequest,
    FeedbackWavResponse,
)
from app.services.audio_fetcher import download_audio_to_temp
from app.services.azure_pa import analyze_pronunciation
from app.services.feedback_payload_builder import build_feedback_payload
from app.services.frame_aligner import build_phoneme_windows
from app.services.fusion_scorer import fuse_phoneme_level, fuse_word_audio_visual
from app.services.llm_feedback import generate_feedback
from app.services.raw_frame_adapter import raw_frames_to_canonical_frames
from app.services.tts_supertone import synthesize as tts_synthesize
from app.services.visual_viseme_scorer import load_profile, score_word_visual_from_windows


demo_router = APIRouter()

_PROFILE = load_profile(
    Path(__file__).parent.parent / "data" / "viseme_feature_profile.json"
)


# ── /analyze 파이프라인 ────────────────────────────────────────────────────

async def _run_analyze(word: str, raw_frames: list, audio_path: str) -> Dict[str, Any]:
    canonical_frames = raw_frames_to_canonical_frames(raw_frames)
    if not canonical_frames:
        raise HTTPException(
            status_code=400,
            detail="유효한 얼굴 프레임을 추출할 수 없습니다. 카메라와 조명을 확인하세요.",
        )

    azure_result = analyze_pronunciation(audio_path, word)
    if azure_result.get("message") != "analyzed":
        raise HTTPException(
            status_code=400,
            detail=f"Azure 발음 분석 실패: {azure_result.get('reason', 'unknown')}",
        )

    phoneme_results = azure_result["phonemes"]
    audio_scoring   = azure_result["audio_scoring"]

    phoneme_windows = build_phoneme_windows(
        phoneme_results=phoneme_results,
        canonical_frames=canonical_frames,
    )

    visual_result = score_word_visual_from_windows(
        phoneme_windows=phoneme_windows,
        profile=_PROFILE,
        use_duration_weight=True,
    )

    fused_word = fuse_word_audio_visual(
        audio_scoring=audio_scoring,
        visual_scoring=visual_result,
        audio_weight=0.75,
        visual_weight=0.25,
    )

    fused_phonemes = fuse_phoneme_level(
        phoneme_audio_scores=audio_scoring["phoneme_scores"],
        scored_visemes=visual_result["scored_visemes"],
        audio_weight=0.75,
        visual_weight=0.25,
    )

    return build_feedback_payload(
        word=word,
        audio_scoring=audio_scoring,
        fused_word=fused_word,
        fused_phonemes=fused_phonemes,
    )


# ── /analyze ──────────────────────────────────────────────────────────────

@demo_router.post(
    "/analyze",
    response_model=AnalyzeResponse,
    summary="발음 분석",
    response_description="0~10 점수 + 2줄 한국어 피드백",
    tags=["analysis"],
)
async def analyze(req: AnalyzeRequest) -> Dict[str, Any]:
    temp_path: str | None = None
    try:
        if not req.frames:
            raise HTTPException(
                status_code=400,
                detail="frames 는 비어있지 않은 배열이어야 합니다.",
            )

        temp_path = await download_audio_to_temp(str(req.audio_url))
        raw_frames = [f.model_dump() for f in req.frames]
        return await _run_analyze(req.word, raw_frames, temp_path)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"서버 내부 오류: {str(e)}")
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)


# ── /feedback-wav ────────────────────────────────────────────────────────

@demo_router.post(
    "/feedback-wav",
    response_model=FeedbackWavResponse,
    summary="mild + spicy 햄스터 wav 생성",
    response_description="두 캐릭터 wav (base64)",
    tags=["feedback"],
)
async def feedback_wav(req: FeedbackWavRequest) -> Dict[str, Any]:
    """
    /analyze 응답의 analysis_text 만 받아:
      1) LLM × 2 (mild/spicy 햄스터 텍스트, 병렬)
      2) TTS × 2 (Supertone, 캐릭터별 고정 voice/style, 병렬)
    화면 표시용 text 는 반환하지 않는다 (wav 만).
    """
    texts = await generate_feedback(analysis_text=req.analysis_text)

    mild_tts, spicy_tts = await asyncio.gather(
        tts_synthesize(text=texts["mild"],  tone="mild"),
        tts_synthesize(text=texts["spicy"], tone="spicy"),
    )

    return {
        "mild_wav_base64":  mild_tts["audio_base64"],
        "spicy_wav_base64": spicy_tts["audio_base64"],
        "audio_format":     mild_tts.get("audio_format", "audio/wav"),
    }
