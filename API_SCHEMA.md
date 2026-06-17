# PRONIMO AI 서버 연동 스키마

엔드포인트 2개 — 모든 점수 **0~10** 스케일:
- **`POST /analyze`** — 발음 분석 + 2줄 한국어 피드백 (LLM 호출 없음)
- **`POST /feedback-wav`** — `analysis_text` → mild(다정한 햄스터) + spicy(빈정대는 햄스터) wav

---

## 흐름

```
[FE]  웹캠 + 마이크
   │ ① word + WAV + frames_json
   ▼
[Spring Boot]
  WAV → S3 PUT → presigned GET URL
   │ ② word + audio_url + frames
   ▼
[AI 서버]  /analyze
  Azure Speech + MediaPipe 융합
   │ ③ { word, scores, analysis_text }
   ▼
[FE]
  점수 + 2줄 텍스트 즉시 표시
  + [🔊 듣기] 노출

====== 사용자가 🔊 클릭 ======

[FE]
   │ ④ { analysis_text }
   ▼
[Spring]  /api/feedback-wav (단순 프록시)
   ▼
[AI 서버]  /feedback-wav
  LLM × 2 (mild/spicy) 병렬 + TTS × 2 병렬
   │ ⑤ { mild_wav_base64, spicy_wav_base64 }
   ▼
[FE]  두 wav 캐싱 + 모드 토글 즉시 재생
```

---

## ① 프론트 → Spring Boot

**형식:** `multipart/form-data`

| 필드 | 타입 | 설명 |
|---|---|---|
| `word` | string | 정답 영어 단어 |
| `audio_file` | File (WAV) | 사용자 녹음 |
| `frames_json` | string (JSON) | MediaPipe raw frame 배열 |

---

## ② Spring → AI `POST /analyze`

**요청 (`application/json`):**

| 필드 | 타입 | 설명 |
|---|---|---|
| `word` | string | 정답 단어 |
| `audio_url` | string (HTTPS URL) | S3 presigned GET URL (≤25MB, `audio/*` 또는 octet-stream) |
| `frames` | array\<RawFrame\> | ①의 `frames_json` 안쪽 배열 |

**제약:** URL scheme=HTTPS, 파일 ≤25MB.

---

## ③ AI → Spring (`/analyze` 응답)

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

### `analysis_text` 규칙 (항상 2줄, 점수는 미포함 — UI 점수 영역에 따로 표시)
```
음성: <칭찬 또는 지적 1문장>
입모양: <칭찬 또는 지적 1문장>
```

차원별 70점(=7.0/10) 미만이면 "못함":

| 음성 | 입모양 | 결과 |
|---|---|---|
| ✅ | ✅ | best 음소 칭찬 / best 입모양 칭찬 |
| ❌ | ✅ | worst 음소 지적 + 교정 / 입모양 칭찬 |
| ✅ | ❌ | 음성 칭찬 / worst 입모양 + diagnosis_tip |
| ❌ | ❌ | worst 음소 지적 / worst 입모양 + tip |

### band 기준 (0~10)
| band | 점수 |
|---|---|
| `excellent` | 9.5~10 |
| `good` | 8.5~9.4 |
| `needs_attention` | 7.0~8.4 |
| `weak` | 0~6.9 |

**에러:** FastAPI `{"detail": "..."}`. 400 (URL 다운로드/크기/Azure/frames), 422 (스키마), 500 (내부).

---

## ④ [🔊 클릭] FE → Spring → AI `POST /feedback-wav`

**Spring:** `POST /api/feedback-wav` 단순 프록시  
**AI 서버:** `POST /feedback-wav`

### 요청

```json
{ "analysis_text": "음성: ...\n입모양: ..." }
```

오직 `analysis_text` 하나만. (word/azure_raw/band 다 없음 — AI 서버가 텍스트만 보고 캐릭터 wav 생성)

### 내부 처리 (모두 병렬)
1. **LLM × 2** (GPT-4o-mini, `asyncio.gather`)
   - mild 프롬프트 → 다정한 햄스터 텍스트
   - spicy 프롬프트 → 빈정대는 햄스터 텍스트
2. **TTS × 2** (Supertone, 캐릭터별 고정 voice/style, `asyncio.gather`)

### 응답

```json
{
  "mild_wav_base64":  "UklGR...",
  "spicy_wav_base64": "UklGR...",
  "audio_format":     "audio/wav"
}
```

- LLM 텍스트는 응답에 포함하지 않음 (FE 화면 표시 안 함)
- 모든 점수/스타일 분기 제거: 캐릭터는 점수와 무관하게 일정

**에러:** 500 (API 키 미설정), 502 (LLM/Supertone 호출 실패).

---

## ⑤ FE wav 재생 + 캐싱

```ts
const cache = new Map<string, string>(); // key: `${word}|${mode}`

async function load(word, analysisText) {
  const { mild_wav_base64, spicy_wav_base64 } =
    await fetch("/api/feedback-wav", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ analysis_text: analysisText }),
    }).then(r => r.json());

  cache.set(`${word}|mild`,  base64ToObjectURL(mild_wav_base64));
  cache.set(`${word}|spicy`, base64ToObjectURL(spicy_wav_base64));
}

function play(word, mode) {
  new Audio(cache.get(`${word}|${mode}`)!).play();
}
```

- 두 wav 한 번에 받아 캐싱 → 모드 토글 즉시 재생, 재호출 없음

---

## 캐릭터 정의 (placeholder)

| mode | 캐릭터 | 톤 |
|---|---|---|
| `mild` | 다정한 햄스터 | 따뜻한 격려, 존댓말 |
| `spicy` | 화난·빈정대는 햄스터 | 까칠한 잔소리, 반말 허용 |

⚠️ 캐릭터 디테일(말끝 습관 / 호칭 / 금칙어 / 이모지 정책)은 추후 확정해
`app/services/llm_feedback.py` 의 `SYSTEM_PROMPT_MILD`, `SYSTEM_PROMPT_SPICY` 와
`app/services/tts_supertone.py` 의 `VOICE_PRESETS` 에서 마무리.

---

## 환경변수

```
AZURE_SPEECH_KEY=...
AZURE_SPEECH_REGION=...
OPENAI_API_KEY=...
SUPERTONE_API_KEY=...
```
