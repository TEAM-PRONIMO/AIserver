"""
PRONIMO AI 서버 요청/응답 스키마.

엔드포인트 2개:
  - POST /analyze       : 발음 분석 → scores + analysis_text
  - POST /feedback-wav  : analysis_text → mild/spicy 햄스터 wav (병렬)
"""
from typing import Dict, List, Literal

from pydantic import BaseModel, Field, HttpUrl


# ── /analyze 요청 ─────────────────────────────────────────────────────────

class Landmark(BaseModel):
    x: float
    y: float
    z: float


class RawFrame(BaseModel):
    """
    프론트엔드가 보내는 MediaPipe raw frame 1개.
      t_ms            : WAV 녹음 시작 기준 경과 시간 (ms)
      face_landmarks  : 478개 NormalizedLandmark
      face_blendshapes: 52개 blendshape {categoryName: score}
    """
    t_ms: float
    face_landmarks: List[Landmark]
    face_blendshapes: Dict[str, float]


class AnalyzeRequest(BaseModel):
    """
    POST /analyze 의 JSON 본문.
    백엔드 흐름: FE WAV → S3 PUT → presigned URL 발급 → {word, audio_url, frames} POST.
    """
    word: str
    audio_url: HttpUrl
    frames: List[RawFrame]


# ── /analyze 응답 ─────────────────────────────────────────────────────────

Band = Literal["excellent", "good", "needs_attention", "weak"]


class Scores(BaseModel):
    """모두 0~10 스케일."""
    overall_0_10: float = Field(..., ge=0, le=10, examples=[8.2])
    audio_0_10:   float = Field(..., ge=0, le=10, examples=[8.5])
    visual_0_10:  float = Field(..., ge=0, le=10, examples=[7.1])
    band:         Band  = Field(..., examples=["good"])


class AnalyzeResponse(BaseModel):
    """POST /analyze 응답."""
    word:          str    = Field(..., examples=["apple"])
    scores:        Scores
    analysis_text: str    = Field(
        ...,
        description="2줄 한국어 피드백 '음성: ...\\n입모양: ...'. FE 가 그대로 표시.",
        examples=["음성: /p/가 /b/처럼 들렸어요. 정확한 소리로 다시 내봐요.\n입모양: /p/ 입모양을 정확하게 잡았어요."],
    )


# ── /feedback-wav 요청/응답 ───────────────────────────────────────────────

class FeedbackWavRequest(BaseModel):
    """
    POST /feedback-wav 요청.

    백엔드는 /analyze 응답의 analysis_text 만 그대로 전달.
    AI 서버 내부에서:
      1) LLM × 2 (mild/spicy 햄스터 캐릭터 텍스트, 병렬)
      2) TTS × 2 (Supertone, 캐릭터별 고정 voice/style, 병렬)
    """
    analysis_text: str = Field(
        ...,
        description="/analyze 응답의 analysis_text 그대로",
        examples=["음성: /p/가 /b/처럼 들렸어요. 정확한 소리로 다시 내봐요.\n입모양: /p/ 입모양을 정확하게 잡았어요."],
    )


class FeedbackWavResponse(BaseModel):
    """POST /feedback-wav 응답. wav 두 개만 반환."""
    mild_wav_base64:  str = Field(..., description="다정한 햄스터 wav (base64)")
    spicy_wav_base64: str = Field(..., description="빈정대는 햄스터 wav (base64)")
    audio_format:     str = Field("audio/wav", examples=["audio/wav"])
