# Backend ↔ AI 서버 DTO

Spring Boot 가 AI 서버 두 엔드포인트(`/analyze`, `/feedback-wav`)에 보낼 요청/응답 정의.

- AI 서버 base URL: `http://<ec2-host>:8000`
- 두 엔드포인트 모두 `Content-Type: application/json`
- 에러: FastAPI 표준 `{"detail": "..."}`
- **모든 점수는 0~10 스케일**

---

## 1) `POST /analyze`

### 입력 (변경 없음)

```json
{
  "word": "apple",
  "audio_url": "https://<s3-presigned-https-url>",
  "frames": [
    {
      "t_ms": 0,
      "face_landmarks": [ {"x":0.59,"y":0.48,"z":-0.03}, "...478개" ],
      "face_blendshapes": {
        "jawOpen": 0.72, "mouthClose": 0.03, "mouthFunnel": 0.15,
        "mouthPucker": 0.08, "mouthStretchLeft": 0.12, "mouthStretchRight": 0.10,
        "mouthPressLeft": 0.05, "mouthPressRight": 0.06,
        "mouthUpperUpLeft": 0.20, "mouthUpperUpRight": 0.22,
        "mouthLowerDownLeft": 0.30, "mouthLowerDownRight": 0.28,
        "mouthRollLower": 0.04, "mouthRollUpper": 0.02,
        "tongueOut": 0.0
      }
    }
  ]
}
```

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `word` | string | ✅ | 정답 영어 단어 |
| `audio_url` | string (HTTPS URL) | ✅ | S3 GET presigned URL. `audio/*` 또는 `application/octet-stream`. ≤25MB |
| `frames` | array | ✅ | MediaPipe raw frame. 비어있으면 안 됨 |

### 응답

```json
{
  "word": "apple",
  "scores": {
    "overall_0_10": 8.2,
    "audio_0_10":   8.5,
    "visual_0_10":  7.1,
    "band":         "good"
  },
  "analysis_text": "음성: /p/가 /b/처럼 들렸어요. 정확한 소리로 다시 내봐요.\n입모양: /p/ 입모양을 정확하게 잡았어요."
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `word` | string | 요청에 들어온 단어 echo |
| `scores.overall_0_10` | number (0~10) | 종합 점수 — **UI 메인 표시** |
| `scores.audio_0_10` | number (0~10) | 음성 점수 |
| `scores.visual_0_10` | number (0~10) | 입모양 점수 |
| `scores.band` | string | `"excellent"` / `"good"` / `"needs_attention"` / `"weak"` |
| `analysis_text` | string | **항상 2줄**. `"음성: ...\n입모양: ..."` 형식. FE 가 그대로 표시 |

#### band 기준 (0~10)
| band | 점수 |
|---|---|
| `excellent` | 9.5 ~ 10 |
| `good` | 8.5 ~ 9.4 |
| `needs_attention` | 7.0 ~ 8.4 |
| `weak` | 0 ~ 6.9 |

#### Spring 처리 흐름
1. `scores` → 점수 UI 영역에 표시
2. `analysis_text` → 텍스트 영역에 그대로 표시 (FE 조립 로직 ❌)
3. `analysis_text` 만 보관 → `[🔊 듣기]` 클릭 시 `/feedback-wav` 에 그대로 forward

#### 구 응답과의 차이 (Migration)
| 구 (제거) | 신 (대체) |
|---|---|
| `score_0_10` | `scores.overall_0_10` |
| `audio_score_0_10` / `visual_score_0_10` | `scores.audio_0_10` / `scores.visual_0_10` |
| `band` (root) | `scores.band` 안으로 이동 |
| `llm_context.{audio_issue, visual_issue, praise_point}` | 통합 → `analysis_text` 2줄 |
| `azure_raw` | **제거** (백엔드 들고 다닐 필요 없음) |
| `?debug=1` | 제거 |

### 에러
| HTTP | detail 예시 | 원인 |
|---|---|---|
| 400 | `"audio_url 다운로드 실패 (HTTP 403)"` | presigned URL 만료/권한 |
| 400 | `"유효한 얼굴 프레임을 추출할 수 없습니다..."` | frames 부족 |
| 400 | `"Azure 발음 분석 실패: ..."` | Azure 인식 실패 |
| 422 | FastAPI 표준 검증 에러 | JSON 스키마 위반 |
| 500 | `"서버 내부 오류: ..."` | 기타 예외 |

---

## 2) `POST /feedback-wav`

`/analyze` 응답의 `analysis_text` 만 받아 mild(다정한 햄스터) + spicy(빈정대는 햄스터) wav 두 개를 한 번에 생성. 내부에서 LLM×2 + TTS×2 모두 `asyncio.gather` 병렬.

### 입력

```json
{
  "analysis_text": "음성: /p/가 /b/처럼 들렸어요. 정확한 소리로 다시 내봐요.\n입모양: /p/ 입모양을 정확하게 잡았어요."
}
```

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `analysis_text` | string | ✅ | `/analyze` 응답의 `analysis_text` 그대로 |

> 끝. word / azure_raw / band 같은 거 안 받음 — AI 서버가 analysis_text 만 보고 처리.

### 응답

```json
{
  "mild_wav_base64":  "UklGR...",
  "spicy_wav_base64": "UklGR...",
  "audio_format":     "audio/wav"
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `mild_wav_base64` | string (base64) | 다정한 햄스터가 읽어준 wav |
| `spicy_wav_base64` | string (base64) | 빈정대는 햄스터가 읽어준 wav |
| `audio_format` | string | 보통 `"audio/wav"`. FE Blob mime type 으로 사용 |

> LLM 이 생성한 텍스트는 응답에 포함하지 않음 (FE 가 화면에 안 띄움).

### Spring 처리 흐름
- 단순 프록시 (`POST /api/feedback-wav` 같은 경로) — body 그대로 forward
- 응답 그대로 FE 에 전달 (DB 저장은 정책에 따라)
- FE: base64 → Blob → `URL.createObjectURL` → `<audio>` 재생

### 에러
| HTTP | detail 예시 | 원인 |
|---|---|---|
| 422 | FastAPI 표준 검증 에러 | analysis_text 누락/타입 오류 |
| 500 | `"OPENAI_API_KEY ..."` | LLM 키 미설정 |
| 500 | `"SUPERTONE_API_KEY ..."` | TTS 키 미설정 |
| 502 | `"LLM 호출 실패: ..."` | OpenAI 네트워크/rate limit |
| 502 | `"Supertone API 오류 (401): ..."` | TTS 호출 실패 |

### 지연 시간
- LLM × 2 병렬: ~1.5~2초
- TTS × 2 병렬: ~1~2초
- 총 ~3~4초 (LLM → TTS 순차, 각 단계 내부는 병렬)

---

## 3) Spring DTO 클래스 스케치

```java
// ── /analyze ──────────────────────────────────────────────────────────
public record AnalyzeRequest(
    String word,
    String audioUrl,           // "audio_url"
    List<RawFrame> frames
) {}

public record AnalyzeResponse(
    String word,
    Scores scores,
    String analysisText        // "analysis_text"
) {
    public record Scores(
        double overall_0_10,
        double audio_0_10,
        double visual_0_10,
        String band            // "excellent"|"good"|"needs_attention"|"weak"
    ) {}
}

// ── /feedback-wav ─────────────────────────────────────────────────────
public record FeedbackWavRequest(
    String analysisText        // "analysis_text"
) {}

public record FeedbackWavResponse(
    String mildWavBase64,      // "mild_wav_base64"
    String spicyWavBase64,     // "spicy_wav_base64"
    String audioFormat         // "audio_format"
) {}
```

> Jackson 사용 시 `@JsonProperty("...")` 로 snake_case 매핑하거나
> `spring.jackson.property-naming-strategy=SNAKE_CASE` 글로벌 설정 권장.

---

## 4) FE 가 받는 최종 형태 (참고)

Spring 은 두 응답 모두 가공 없이 패스해도 됨.

1. **첫 분석 후** `scores` → 점수 UI / `analysis_text` → 텍스트 영역
2. **세션에 `analysis_text` 보관**
3. **`[🔊 듣기]` 클릭** → `/feedback-wav` 호출 → mild/spicy 두 wav 캐싱
4. **모드 토글**: 캐시된 wav 즉시 재생 (재호출 ❌)
