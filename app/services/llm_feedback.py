"""
LLM 캐릭터 피드백 생성 모듈.

`/feedback-wav` 가 호출. analysis_text 한 줄만 입력으로 받아
mild(다정한 햄스터) + spicy(화난·빈정대는 햄스터) 두 캐릭터 텍스트를
OpenAI GPT-4o-mini 로 병렬 생성한다.

⚠️ 캐릭터 톤·말투·금칙어 등 디테일은 추후 사용자가 따로 지정해 채울 placeholder.
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from fastapi import HTTPException
from openai import AsyncOpenAI

load_dotenv()


# ── 모델 설정 ────────────────────────────────────────────────────────────
_MODEL = "gpt-4o-mini"
# TTS 합성 시간 약 15초 (한국어 Supertone speed=1.0 기준 ≈ 5~6 자/초)
# 1~2 문장 × 60~80 자 가이드라인을 안전하게 담을 토큰량.
_MAX_TOKENS = 150

_PARAMS: Dict[str, Dict[str, Any]] = {
    "mild":  {"temperature": 0.7},
    "spicy": {"temperature": 0.9},
}


# ── 시스템 프롬프트 (햄스터 캐릭터 placeholder) ───────────────────────────
# TODO: 사용자가 캐릭터 디테일(말끝 습관, 호칭, 금칙어, 이모지 정책 등)
#       확정하면 아래 두 상수만 교체.

SYSTEM_PROMPT_MILD = """\
당신은 영어 발음 학습 앱의 캐릭터 '다정한 햄스터' 입니다.
사용자에게 보여진 2줄 분석 텍스트를 햄스터 캐릭터 말투로 재포장한
따뜻하고 격려하는 한국어 피드백을 작성합니다.

## 입력 (user 메시지, JSON)
- analysis_text : 화면에 이미 떠 있는 2줄 텍스트 ("음성: ...\\n입모양: ...")

## 작성 규칙
1. 한국어로만 작성, 1~2문장, 60~80자 (공백 포함, TTS 약 15초 이내)
2. analysis_text 의 음성/입모양 지적 내용을 자연스럽게 풀어 격려
3. 음소는 /p/, /æ/ 처럼 슬래시로 감싸기
4. analysis_text 에 없는 문제는 절대 만들어내지 말 것
5. 마지막은 짧은 응원 한 마디로 마무리
6. 욕설/비속어/이모지 금지

## 출력 형식 (JSON 만)
{"text": "여기에 한국어 피드백 60~80자"}
"""

SYSTEM_PROMPT_SPICY = """\
당신은 영어 발음 학습 앱의 캐릭터 '화가 난 / 빈정대는 햄스터' 입니다.
까칠하고 직설적이지만 유머러스합니다. 진짜 욕설은 쓰지 않습니다.

## 입력 (user 메시지, JSON)
- analysis_text : 화면에 이미 떠 있는 2줄 텍스트 ("음성: ...\\n입모양: ...")

## 작성 규칙
1. 한국어로만 작성, 1~2문장, 60~80자 (공백 포함, TTS 약 15초 이내)
2. analysis_text 의 음성/입모양 지적 내용을 빈정대듯 짧게 풀어쓰기
3. 음소는 /p/, /æ/ 처럼 슬래시로 감싸기
4. analysis_text 에 없는 문제는 절대 만들어내지 말 것
5. 진짜 욕설 금지, 인격 모독 금지
6. 마지막은 짧은 도발/잔소리 한 마디로 마무리

## 출력 형식 (JSON 만)
{"text": "여기에 한국어 피드백 60~80자"}
"""


_client: Optional[AsyncOpenAI] = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise HTTPException(
                status_code=500,
                detail="OPENAI_API_KEY 가 .env 에 설정되지 않았습니다.",
            )
        _client = AsyncOpenAI(api_key=api_key)
    return _client


async def _call_one(system: str, analysis_text: str, temperature: float) -> str:
    """1회 LLM 호출. JSON {"text":"..."} 만 받아 text 추출."""
    client = _get_client()
    user_payload = {"analysis_text": analysis_text}

    try:
        response = await client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            temperature=temperature,
            max_tokens=_MAX_TOKENS,
            response_format={"type": "json_object"},
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM 호출 실패: {e}")

    content = response.choices[0].message.content
    if not content:
        return "피드백 생성에 실패했습니다."

    try:
        parsed = json.loads(content)
        text = parsed.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
    except json.JSONDecodeError:
        pass
    return content.strip()


async def generate_feedback(analysis_text: str) -> Dict[str, str]:
    """
    mild + spicy 캐릭터 텍스트 병렬 생성.
    Returns: {"mild": str, "spicy": str}
    """
    mild, spicy = await asyncio.gather(
        _call_one(SYSTEM_PROMPT_MILD,  analysis_text, _PARAMS["mild"]["temperature"]),
        _call_one(SYSTEM_PROMPT_SPICY, analysis_text, _PARAMS["spicy"]["temperature"]),
    )
    return {"mild": mild, "spicy": spicy}
