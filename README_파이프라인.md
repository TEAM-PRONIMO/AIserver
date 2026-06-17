# pronimo — End-to-End 파이프라인 기술 README

> **무엇을 하는가:** 사용자가 영어 단어를 발음하면 **음성(Azure)** 과 **입모양(MediaPipe)** 을 동시에 분석해 점수를 매기고, **GPT 피드백 + TTS 음성** 을 주며, **3D 구강 모델**로 발음 입·혀 움직임을 보여주는 발음 학습 플랫폼.

---

## 0. 아키텍처 (3-tier + 외부)

| 계층 | 스택 | 역할 |
|---|---|---|
| **Frontend** | React + TypeScript + Three.js + MediaPipe | 음성 녹음·얼굴 캡처, 결과·3D 구강 렌더 |
| **Backend** | Spring Boot (Java 17) + MySQL + AWS S3 | 게이트웨이(JWT), 오디오 저장, AI 서버 중계, 점수·이력 저장 |
| **AI Server** | FastAPI (Python) | 발음 분석·점수·피드백 텍스트·TTS 오케스트레이션 |
| **외부** | Azure Speech / OpenAI GPT-4o-mini / Supertone TTS | 발음평가 / 캐릭터 피드백 / 음성합성 |

**큰 흐름:** `FE` → `Backend` → `AI Server /analyze` → (Azure) → 점수 반환 → `Backend(MySQL 저장)` → `AI Server /feedback-wav` → (GPT, Supertone) → `FE` → **3D Shape-Key 재생**

---

## 1. 전체 단계 한눈에 (적용 순서 + 코드 파일)

| # | 단계 | 코드 파일 |
|---|---|---|
| 1 | 음성 녹음 | `FE/src/features/learning/hooks/useAudioRecorderCard.tsx` |
| 2 | 웹캠 스트림 | `FE/src/features/learning/hooks/useWebcamStream.ts` |
| 3 | 얼굴 랜드마크·블렌드셰이프 추출 (MediaPipe) | `FE/src/features/pronunciation/services/faceLandmarkerService.ts` |
| 4 | 프레임 캡처 루프(30fps) | `FE/src/features/pronunciation/hooks/usePronunciationCapture.ts` |
| 5 | 녹음·프레임 묶어 업로드/분석 요청 | `FE/src/pages/learning/LearningPage.tsx` · `FE/src/features/learning/api/quizAPI.tsx` |
| 6 | 오디오 S3 업로드 | `backend/.../upload/controller/AudioUploadController.java` · `global/config/S3Config.java` |
| 7 | 분석 디스패치(presigned URL+frames → AI) | `backend/.../upload/controller/AudioAnalysisController.java` · `service/FastApiUploadService.java` |
| 8 | **/analyze 진입** | `AIserver/app/api/routes.py` · `schemas/request.py` |
| 9 | 오디오 다운로드(S3) | `AIserver/app/services/audio_fetcher.py` |
| 10 | 프레임 → 17 정규화 특징 | `AIserver/app/services/raw_frame_adapter.py` · `visual_viseme_scorer.py` |
| 11 | Azure 발음평가 (+ 음소→viseme, 음성점수) | `AIserver/app/services/azure_pa.py` → `viseme_mapper.py` · `audio_scorer.py` |
| 12 | **viseme 시간정렬(window)** | `AIserver/app/services/frame_aligner.py` |
| 13 | **★ 시각(viseme) 점수** | `AIserver/app/services/visual_viseme_scorer.py` (+ `data/viseme_feature_profile.json`) |
| 14 | 음성·시각 융합 | `AIserver/app/services/fusion_scorer.py` |
| 15 | 점수 0~10·등급·분석텍스트 | `AIserver/app/services/feedback_payload_builder.py` · `analysis_text_builder.py` |
| 16 | (반환) 백엔드 저장 | `backend/.../upload/service/FastApiUploadService.java` (SessionResult·PronunciationScore·AnswerSubmission·FeedbackLog) |
| 17 | /feedback-wav — GPT 피드백 | `AIserver/app/services/llm_feedback.py` |
| 18 | /feedback-wav — TTS 합성 | `AIserver/app/services/tts_supertone.py` |
| 19 | 결과 표시 | `FE/src/pages/result/ResultPage.tsx` |
| 20 | **★ 3D Shape-Key 립싱크** | `FE/src/pages/result/ShapeKeyModelViewer.tsx` (+ `assets/models/3D_Front.glb`·`3D_Side.glb`) |

---

## 2. 단계별 상세

### STEP 1 — 입력 캡처 (Frontend)
- **음성:** `useAudioRecorderCard.tsx` — `MediaRecorder`(webm/opus). 녹음 시작 시각 = `t=0ms` 기준.
- **영상:** `useWebcamStream.ts` 로 웹캠 스트림 → `faceLandmarkerService.ts` 가 MediaPipe **FaceLandmarker**(468 landmarks + 52 blendshapes) 추출 → `usePronunciationCapture.ts` 가 30fps로 프레임 적재.
- **프레임 스키마** (`types/pronunciation.ts`): `{ t_ms, face_landmarks[26], face_blendshapes{jawOpen…} }` — **오디오와 같은 시간축**.
- `LearningPage.tsx` 에서 녹음 종료 시 오디오 Blob + 프레임 배열을 `quizAPI.tsx` 로 전송.

### STEP 2 — 업로드 & 디스패치 (Backend, Spring Boot)
1. `POST /api/media/audio` → `AudioUploadController.java` : WAV 검증 → **S3 업로드**(`S3Config.java`), `UploadFile` 저장, presigned URL 발급.
2. `POST /api/media/audio/{uploadId}/analyze` → `AudioAnalysisController.java` → `FastApiUploadService.java` :
   - presigned URL 생성, 프레임 정규화(필드명 호환·최대 120프레임 샘플링),
   - **FastAPI `/analyze` 호출** `{ word, audio_url, frames }`.
   - JWT 인증·CORS는 `global/config/SecurityConfig.java`, `JwtAuthenticationFilter.java`.

### STEP 3 — `/analyze` 오케스트레이션 (AI Server, FastAPI)
진입점 `routes.py :: _run_analyze()` 가 아래를 **순서대로** 호출:

| 순서 | 함수 | 파일 | 하는 일 |
|---|---|---|---|
| 3-1 | `download_audio_to_temp()` | `audio_fetcher.py` | S3 presigned URL에서 오디오 다운로드(타임아웃·25MB·타입검증) |
| 3-2 | `raw_frames_to_canonical_frames()` | `raw_frame_adapter.py` | MediaPipe raw → **17개 정규화 입모양 특징**(jawOpen·lipSeal·mouthPucker·tongueOut…) |
| 3-3 | `analyze_pronunciation()` | `azure_pa.py` | **Azure 발음평가**. 음소별 `Offset/Duration/AccuracyScore/NBestPhonemes`. 내부에서 `viseme_mapper.map_phoneme_to_viseme()`(음소→viseme), `audio_scorer`(음성점수) 호출 |
| 3-4 | `build_phoneme_windows()` | `frame_aligner.py` | 각 음소 `Offset/Duration(100ns→ms)` 로 **window=[offset−80ms, +dur+80ms]** 잡아 매칭 프레임 수집 |
| 3-5 | `score_word_visual_from_windows()` | `visual_viseme_scorer.py` | **★ viseme별 시각 점수** (기법: pattern/absolute/gaussian/skip, `viseme_feature_profile.json`) |
| 3-6 | `fuse_word_audio_visual()` + `fuse_phoneme_level()` | `fusion_scorer.py` | `fused = 0.75·audio + 0.25·visual(×reliability)` + 음성·시각 일치 검사 |
| 3-7 | `build_feedback_payload()` | `feedback_payload_builder.py` | 0~1 → **0~10·등급(band)**, 그리고 `analysis_text_builder.build_analysis_text()` 로 **2줄 분석 텍스트(규칙 기반)** 생성 |

**응답:** `{ word, scores{overall/audio/visual_0_10, band}, analysis_text }`

### STEP 3.5 — 백엔드 저장
`FastApiUploadService.java` 가 응답을 받아 `SessionResult`(점수), `PronunciationScore`(voice/vision), `AnswerSubmission`(전체 payload), `FeedbackLog`(분석텍스트)를 **MySQL** 저장 후 FE로 반환.

### STEP 4 — `/feedback-wav` (LLM + TTS)
`routes.py :: feedback_wav()`:
1. `generate_feedback()` (`llm_feedback.py`) — **GPT-4o-mini** 가 `analysis_text`를 **mild(다정한 햄스터)/spicy(화난 햄스터)** 두 캐릭터 텍스트로 **병렬** 생성. (시스템 프롬프트 = `SYSTEM_PROMPT_MILD/SPICY`)
2. `tts_synthesize()` (`tts_supertone.py`) — **Supertone**(`sona_speech_1`)로 두 음성 **병렬** 합성 → base64 WAV.

### STEP 5 — 결과 표시 & 3D 출력 (Frontend)
- `ResultPage.tsx` : 점수·피드백 표시, 피드백 WAV 재생.
- `ShapeKeyModelViewer.tsx` : **★ 3D Shape-Key 립싱크** (아래 §4).

---

## 3. ★ 강조 1 — Viseme Scoring (시각 점수)  · `visual_viseme_scorer.py`

> "음성으로 못 잡는 발음 오류를 **입모양**으로 교차 검증" 하는 핵심 기술.

1. **음소 → viseme 매핑** (`viseme_mapper.py` + `data/phoneme_to_viseme_map.json`)
   - p·b·m→`PP`, f·v→`FF`, th·dh→`TH`, 모음→`aa/E/ih/oh/ou`, 안 보이는 음소(t·d·k·g·s·z·n·l·r·sh·ch)→`skip`.
2. **시간 정렬** (`frame_aligner.py`) — Azure `Offset/Duration` → **window [offset−80ms, +dur+80ms]** → 그 구간 프레임만 평가.
3. **특징 추출** (`raw_frame_adapter.py`/`visual_viseme_scorer.py`) — 52 blendshape → 13 입영역 + 4 파생 = **17 정규화 특징**.
4. **viseme별 분석 기법** (`data/viseme_feature_profile.json`):

| 기법 | viseme | 판정 | 신뢰도 |
|---|---|---|---|
| `pattern_detection` | PP /p b m/ | lipSeal peak ≥ 0.55 & jawOpen<0.15 | 0.95 |
| `absolute_detection` | TH /th dh/ | tongueOut ≥ 0.20 | 0.80 |
| `gaussian` | 모음 aa·E·ih·oh·ou / FF | 특징 p90 vs 기준값(정규분포 매칭) | 0.45–0.90 |
| `skip` | DD·kk·CH·SS·nn·RR | 평가 제외(안 보임) | 0.0 |

5. **단어 시각 점수** = `Σ(score × reliability × dur) / Σ(reliability × dur)`
6. **예시:** /p/ 양순음 — 입술폐쇄 기대 0.85 vs 측정 0.42 → Visual ≈ 0.45 (감점).

---

## 4. ★ 강조 2 — 3D Shape-Key Lip-Sync  · `ShapeKeyModelViewer.tsx`

> **자체 제작 Three.js 3D 구강 모델** (외부 라이브러리 X). GLB 2종: `3D_Front.glb`(입술 정면) + `3D_Side.glb`(구강 단면 — 혀·입천장).

- **14개 viseme Shape Key 내장:** `v_MBP, v_FF, v_TH, v_LNTD, v_R_ER, v_KG, v_S_Z, v_W_OO, v_Y_EE, v_AA, v_AE, v_AH, v_EH, v_OW`.
- **동작 방식 (중요):** 오디오 파형 분석 실시간 립싱크가 **아니라**, **시간 기반 viseme timeline 재생** 방식.
  1. `timedPhones`(음소별 `startMs/endMs`) 기반으로 타임라인 구성 (`buildVisemeTimeline` / `extractTimedVisemeTimeline`).
  2. 각 음소 → `phonemeToVisemeWeights()` 로 **shape key 가중치** 변환.
  3. `requestAnimationFrame` 으로 `playbackMs` 갱신 → `sampleVisemeTimeline()` 로 현재 시각의 가중치 샘플링.
  4. **smoothstep envelope** 로 viseme 전환을 부드럽게 연결(coarticulation) → `applyVisemeWeights()` 가 `morphTargetInfluences` 제어.
  5. 상수: `PHONEME_DURATION 0.58s · GAP 0.12s · OVERLAP 0.2s · MORPH_RELEASE 420ms · MORPH_WEIGHT_SCALE 0.72`.
- 정면=입술 모양, 측면=혀·턱 위치를 **동시에** 보여줘 보이지 않는 조음까지 학습.

---

## 5. 데이터 / 외부 서비스

- **데이터 파일:** `AIserver/app/data/phoneme_to_viseme_map.json`(음소→viseme), `viseme_feature_profile.json`(기법·기준·신뢰도), `mediapipe_mouth_feature_catalog.json`(특징 정의).
- **외부 키(.env):** `AZURE_SPEECH_KEY/REGION`, `OPENAI_API_KEY`, `SUPERTONE_API_KEY`, `AWS_*`.
- **엔드포인트:** AI `POST /analyze`, `POST /feedback-wav` (`routes.py`) · Backend `POST /api/media/audio`, `…/analyze`, `…/feedback-wav`.

---

## 6. 2분 30초 발표 구성 제안 (전체 파이프라인 + 두 강조)

| 구간 | 시간 | 내용 | 강조 |
|---|---|---|---|
| ① 도입·문제 | 0:00–0:20 | "발음을 외우지 말고 **보고** 이해" — 음성+입모양 동시 분석 | 한 줄 후킹 |
| ② 전체 파이프라인 | 0:20–0:50 | 입력→분석→융합→피드백→출력 한 장으로 흐름 | 개요(빠르게) |
| ③ 입력·음성분석 | 0:50–1:10 | MediaPipe 캡처 → Azure(Offset/Duration/NBest) → audio score | 보통 |
| ④ **★ Viseme Scoring** | 1:10–1:50 | 음소→viseme, **window 시간정렬**, 기법 4종, /p/ 예시(기대vs측정) | **핵심 1 (40s)** |
| ⑤ 융합·피드백·TTS | 1:50–2:10 | 0.75·A+0.25·V, 규칙 2줄→GPT(mild/spicy)→Supertone | 보통(빠르게) |
| ⑥ **★ 3D Shape-Key** | 2:10–2:30 | 자체 3D 구강 모델, viseme timeline 재생(실시간X), 실제 영상 시연 | **핵심 2 (20s) + 마무리** |

**팁:** ②에서 전체를 "지도"로 깔고, ④·⑥ 두 곳에서만 깊게 들어갔다 나오면 2분 30초에 **전체+강조**가 모두 들어갑니다. ④의 *시간정렬(window)* 과 ⑥의 *"실시간이 아니라 timeline 재생"* 이 차별화 포인트.

---

### 참고 (대응 슬라이드)
PPT 16장 기준: 개요(1) · 입력(2) · 흐름(3) · Azure(4) · Audio(5) · 시각특징(6) · **매핑(7)·정렬(8)·기법(9)·예시(10)** · 융합(11) · 분석텍스트(12)·프롬프트(13) · TTS(14) · **3D Talking(15)·Shape-Key(16)**.
