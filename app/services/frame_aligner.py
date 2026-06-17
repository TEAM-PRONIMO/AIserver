from typing import Any, Dict, List, Mapping, Sequence


# 음소 윈도우 양쪽 패딩 (ms).
# 입모양은 음성 신호보다 약간 앞서 준비되고 끝난 뒤 잠시 유지되므로,
# Azure 가 알려준 음소 [start_ms, end_ms] 양쪽으로 PAD_MS 씩 확장한 범위에서
# 프레임을 모은다. 가중치 계산용 duration_ms 는 원본 그대로 유지한다.
# 50 → 80: 짧은 단어(sheep, stop 등)에서 /p/, /t/ 같은 짧은 폐쇄음 음소가
# INSUFFICIENT_FRAMES 로 떨어지는 문제를 완화하기 위해 확대.
WINDOW_PAD_MS = 80.0


def slice_frames_by_time(
    frames: Sequence[Mapping[str, Any]],
    start_ms: float,
    end_ms: float,
) -> List[Dict[str, Any]]:
    """t_ms가 [start_ms, end_ms] 구간에 포함되는 프레임만 반환."""
    return [
        dict(frame)
        for frame in frames
        if start_ms <= float(frame.get("t_ms", -1)) <= end_ms
    ]


def build_phoneme_windows(
    phoneme_results: Sequence[Mapping[str, Any]],
    canonical_frames: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Azure phoneme 결과 + canonical frames → phoneme별 window 구조.

    window 구조:
    {
        "phoneme":       str,
        "viseme":        str,
        "start_ms":      float,
        "end_ms":        float,
        "duration_ms":   float,
        "frame_count":   int,      ← 추가: 프레임 수 (< 3이면 visual 분석 신뢰 불가)
        "frame_features": [...],   ← canonical feature 프레임 목록
        "audio_accuracy": float | None,
        "error_type":    str,      ← 추가: Azure ErrorType (Mispronunciation 등)
        "nbest_phonemes": [...],   ← 추가: 사용자가 실제로 낸 소리 후보
    }
    """
    windows: List[Dict[str, Any]] = []

    for item in phoneme_results:
        start_ms    = float(item["offset_ms"])
        duration_ms = float(item["duration_ms"])
        end_ms      = start_ms + duration_ms

        # 프레임 수집 범위는 패딩 적용
        padded_start = max(0.0, start_ms - WINDOW_PAD_MS)
        padded_end   = end_ms + WINDOW_PAD_MS
        window_frames = slice_frames_by_time(canonical_frames, padded_start, padded_end)

        windows.append({
            "phoneme":        item["phoneme"],
            "viseme":         item["viseme"],
            "start_ms":       start_ms,       # 원본 (가중치 계산용)
            "end_ms":         end_ms,         # 원본
            "duration_ms":    duration_ms,    # 원본
            "frame_count":    len(window_frames),
            "frame_features": window_frames,
            "audio_accuracy": item.get("accuracy"),
            "error_type":     item.get("error_type", "None"),
            "nbest_phonemes": list(item.get("nbest_phonemes") or []),
        })

    return windows
