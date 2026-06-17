"""
분석 텍스트 조립기.

`/analyze` 응답에 포함되는 2줄짜리 한국어 문자열을 만든다.
프론트는 이 문자열을 그대로 화면에 표시한다 (조립 로직 FE 측 없음).
점수는 UI 의 별도 영역에서 표시하므로 본 텍스트엔 포함하지 않는다.

형식 (항상 2줄):
    음성: <칭찬 또는 지적 1문장>
    입모양: <칭찬 또는 지적 1문장>

음성/입모양 각각 독립 판정:
  - "잘함" : 모든 음소의 해당 차원 점수가 임계치 이상 → best 음소 칭찬
  - "못함" : 임계치 미만 음소가 있음 → 가장 약한 음소 지적 + 교정
"""
from __future__ import annotations

from typing import Any, List, Mapping, Optional


# 70점 미만이면 해당 차원에서 "못함"으로 판정
_THRESHOLD_0_1 = 0.7


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return default if value is None else float(value)
    except (TypeError, ValueError):
        return default


def _heard_as(item: Mapping[str, Any]) -> Optional[str]:
    nbest = item.get("nbest_phonemes") or []
    if not nbest:
        return None
    top = nbest[0]
    ph = top.get("phoneme")
    return str(ph) if ph else None


# ── 음성 (audio) ───────────────────────────────────────────────────────────

def _audio_line(items: List[Mapping[str, Any]]) -> str:
    if not items:
        return "음성: 분석할 음성 데이터가 부족했어요."

    worst = min(items, key=lambda p: _safe_float(p.get("audio_score_0_1")))
    worst_score = _safe_float(worst.get("audio_score_0_1"))

    if worst_score >= _THRESHOLD_0_1:
        best = max(items, key=lambda p: _safe_float(p.get("audio_score_0_1")))
        ph = str(best.get("phoneme", "")).strip() or "전체"
        return f"음성: /{ph}/ 소리가 정확했어요."

    phoneme    = str(worst.get("phoneme", "")).strip()
    error_type = str(worst.get("error_type") or "None")
    heard      = _heard_as(worst)

    if error_type == "Omission":
        return f"음성: /{phoneme}/ 소리를 빠뜨렸어요. 발음할 때 빠짐없이 소리 내주세요."
    if heard:
        return f"음성: /{phoneme}/가 /{heard}/처럼 들렸어요. 정확한 소리로 다시 내봐요."
    return f"음성: /{phoneme}/ 발음이 부정확했어요. 다시 한 번 또렷하게 소리 내봐요."


# ── 입모양 (visual) ────────────────────────────────────────────────────────

def _visual_line(items: List[Mapping[str, Any]]) -> str:
    measurable = [p for p in items if _safe_float(p.get("visual_reliability")) > 0]
    if not measurable:
        return "입모양: 카메라로 평가할 수 있는 입모양 동작이 없었어요."

    worst = min(measurable, key=lambda p: _safe_float(p.get("visual_score_0_1")))
    worst_score = _safe_float(worst.get("visual_score_0_1"))

    if worst_score >= _THRESHOLD_0_1:
        best = max(measurable, key=lambda p: _safe_float(p.get("visual_score_0_1")))
        ph = str(best.get("phoneme", "")).strip() or "전체"
        return f"입모양: /{ph}/ 입모양을 정확하게 잡았어요."

    phoneme = str(worst.get("phoneme", "")).strip()
    tip     = (worst.get("diagnosis_tip") or "").strip()
    if tip:
        return f"입모양: /{phoneme}/ 입모양에서 {tip}"
    return f"입모양: /{phoneme}/ 입모양이 부정확했어요. 거울 보고 입 모양을 다시 잡아봐요."


# ── 엔트리 ────────────────────────────────────────────────────────────────

def build_analysis_text(items: List[Mapping[str, Any]]) -> str:
    """
    Args:
      items : fused_phonemes["items"] — 음소별 fused 결과.
              필요한 키: phoneme, audio_score_0_1, visual_score_0_1,
                        visual_reliability, error_type, nbest_phonemes,
                        diagnosis_tip

    Returns:
      "음성: ...\n입모양: ..." 2줄 문자열
    """
    return f"{_audio_line(items)}\n{_visual_line(items)}"
