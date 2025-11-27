# ================================================================
# llm_client.py
# ------------------------------------------------
# 🧠 역할:
# - GPT-4o-mini (또는 지정된 모델)과의 대화 기능 제공
# - 모든 LLM 관련 호출을 이 파일로 통합
# - 다른 프로젝트(예: STT/TTS, RAG 등)에서 import 하여 사용
# ================================================================

from openai import OpenAI
from typing import List, Dict, Any
from .config import settings

# ------------------------------------------------
# 🔗 OpenAI 클라이언트 초기화
# ------------------------------------------------
_client = OpenAI(
    api_key=settings.openai_api_key,
    base_url=settings.openai_base_url
)

# ------------------------------------------------
# 💬 Chat 함수 (LLM 대화용)
# ------------------------------------------------
def chat(messages: List[Dict[str, str]],
         model: str | None = None,
         temperature: float = 0.7,
         max_tokens: int = 256) -> str:
    """
    GPT-4o-mini 모델에 채팅 요청을 보내고, 텍스트 응답을 반환합니다.

    Args:
        messages: OpenAI chat 형식의 메시지 리스트
                  예: [{"role": "user", "content": "안녕"}]
        model: 사용할 모델명 (기본값은 .env에 설정된 모델)
        temperature: 창의성 정도 (0=보수적, 1=창의적)
        max_tokens: 최대 생성 토큰 수

    Returns:
        str: LLM이 생성한 답변 텍스트
    """
    model = model or settings.openai_model
    resp = _client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens
    )
    return resp.choices[0].message.content.strip()
