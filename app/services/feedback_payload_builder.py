"""
/analyze 응답 payload 빌더.

분석 파이프라인 결과를 슬림한 응답 dict 으로 패키징한다.

반환 구조 (모든 점수 0~10 스케일):
    {
      "word": str,
      "scores": {
        "overall_0_10": float,
        "audio_0_10":   float,
        "visual_0_10":  float,
        "band":         "excellent"|"good"|"needs_attention"|"weak"
      },
      "analysis_text": str   # 2줄 "음성:...\n입모양:..." (FE 가 그대로 표시)
    }
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping

from app.services.analysis_text_builder import build_analysis_text


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return default if value is None else float(value)
    except (TypeError, ValueError):
        return default


def _score_band(score_0_10: float) -> str:
    if score_0_10 >= 9.5:
        return "excellent"
    if score_0_10 >= 8.5:
        return "good"
    if score_0_10 >= 7.0:
        return "needs_attention"
    return "weak"


def build_feedback_payload(
    word: str,
    audio_scoring: Mapping[str, Any],
    fused_word: Mapping[str, Any],
    fused_phonemes: Mapping[str, Any],
) -> Dict[str, Any]:
    items: List[Mapping[str, Any]] = list(fused_phonemes.get("items", []))

    overall_audio  = _safe_float(audio_scoring.get("custom_audio_score_0_1")) * 10.0
    overall_fused  = _safe_float(fused_word.get("fused_score_0_1")) * 10.0
    # skip-only 단어는 fused_word.visual_score_0_1 가 audio 와 동일하게 fold 됨.
    overall_visual = _safe_float(fused_word.get("visual_score_0_1")) * 10.0

    return {
        "word": word,
        "scores": {
            "overall_0_10": round(overall_fused, 1),
            "audio_0_10":   round(overall_audio, 1),
            "visual_0_10":  round(overall_visual, 1),
            "band":         _score_band(overall_fused),
        },
        "analysis_text": build_analysis_text(items),
    }
