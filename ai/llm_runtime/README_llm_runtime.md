# llm_runtime

학교 전용 챗봇에서 **LLM 호출을 표준화**하기 위한 경량 런타임 모듈입니다.  
FastAPI 서버(`stt-tts-sample/app.py`)나 RAG 엔진(`ai/rag/*`)에서 **공통으로 import** 하여 사용합니다.

> 기본 모델: **GPT-4o-mini** (OpenAI API 호환)  
> 이 모듈은 `.env`를 통해 키/모델/타임아웃 등을 읽어 동작합니다.

---

## 📁 디렉토리 구조

```
ai/llm_runtime/
├─ .env                 # OpenAI API 키/모델 설정(로컬 전용, Git 업로드 금지)
├─ config.py            # .env 로드, 공용 설정 객체
├─ llm_client.py        # GPT-4o-mini 채팅 래퍼 (프로덕션에서 import)
├─ test_llm.py          # 단독 동작 테스트 스크립트
└─ requirements.txt          # 서버 의존성
```

> ⚠️ `.env`는 **반드시** `ai/llm_runtime/` 폴더에 위치해야 하며, 절대 저장소에 커밋하지 마세요.

---

## 🧩 파일별 역할

### `config.py`
- **역할**: `.env`를 읽어 설정을 제공합니다.
- **주요 항목**
  - `OPENAI_API_KEY` : OpenAI 키 (필수)
  - `OPENAI_MODEL`   : 기본 모델명 (기본값: `gpt-4o-mini`)
  - `OPENAI_BASE_URL`: 기본은 `https://api.openai.com/v1` (프록시/게이트웨이 사용 시 변경)
  - `LLM_TIMEOUT_S`  : LLM 호출 타임아웃(초), 기본 12
- **사용**: `from llm_runtime.config import settings`

### `llm_client.py`
- **역할**: OpenAI Chat Completions API를 간단히 호출하는 **래퍼**를 제공합니다.
- **대표 함수**
  ```python
  chat(messages, model=None, temperature=0.7, max_tokens=512) -> str
  ```
  - `messages`: OpenAI 포맷 리스트 (예: `{"role": "user", "content": "안녕"}`)
  - `model` 미지정 시 `.env`의 `OPENAI_MODEL` 사용
  - 반환값: **첫 번째 후보의 텍스트(str)**
  - 타임아웃은 `.env`의 `LLM_TIMEOUT_S`를 사용

### `test_llm.py`
- **역할**: 단독 실행으로 LLM 호출을 검증합니다.
- **사용**
  ```bash
  cd ai/llm_runtime
  python test_llm.py
  ```
  - 정상이라면 콘솔에 모델 응답이 출력됩니다.
 
---

## ⚙️ `.env` 예시

```ini
OPENAI_API_KEY=sk-실제 키 값
OPENAI_MODEL=gpt-4o-mini
# (옵션) 호출 타임아웃
LLM_TIMEOUT_S=12
# (옵션) 게이트웨이/프록시 사용 시
# OPENAI_BASE_URL=https://api.openai.com/v1
```

> 실제 배포에서는 OS 비밀관리(환경변수, KeyVault 등) 사용을 권장합니다.

---

## ⚙️ 동작 개요/사용 방법(다른 모듈에서)

```python
# 예: FastAPI 핸들러나 RAG 파이프라인 내부
from llm_runtime.llm_client import chat

messages = [
    {"role": "system", "content": "You are a helpful Korean assistant."},
    {"role": "user", "content": "학칙에서 휴학 관련 규정 요약해줘."},
]

answer = chat(messages, temperature=0.3, max_tokens=512)
print(answer)
```

- 별도의 키 세팅 코드 없이, **`ai/llm_runtime/.env`** 를 자동으로 읽습니다.
- 모델/타임아웃 등을 **런타임에서 교체**하고 싶다면 `.env` 수정 또는 인자 지정으로 오버라이드합니다.

---

## 🚀 구동/테스트 절차

1) 가상환경/의존성
```bash
# 프로젝트 루트에서
pip install "openai>=1.0.0" python-dotenv
```

2) `.env` 작성
```ini
# ai/llm_runtime/.env
OPENAI_API_KEY=sk-********************************
OPENAI_MODEL=gpt-4o-mini
```

3) 단독 테스트
```bash
cd ai/llm_runtime
python test_llm.py
```

4) 서비스 코드에서 사용
- 이미 `stt-tts-sample/app.py`에서는
  ```python
  from llm_runtime.llm_client import chat
  ```
  로 교체되어 있으며, **TinyLlama → GPT-4o-mini** 로 전환 완료입니다.

---

## 🧯 트러블슈팅

- **`ModuleNotFoundError: llm_runtime`**
  - 실행 스크립트 기준으로 상위 폴더(`ai/`)가 `PYTHONPATH`에 없을 수 있습니다.
  - 예시 해결: `app.py`에서
    ```python
    import sys, os
    CURRENT_DIR = os.path.dirname(__file__)
    PARENT_AI_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
    if PARENT_AI_DIR not in sys.path:
        sys.path.insert(0, PARENT_AI_DIR)
    ```

- **키가 없는데도 답이 온다?**
  - 로컬 vLLM 등 **다른 경로**로 호출되고 있을 가능성. 본 모듈은 `.env`의 OpenAI 설정만 사용합니다.

- **응답이 느리다**
  - `LLM_TIMEOUT_S`를 늘리되, 프롬프트/컨텍스트를 줄이는 방향 권장.
  - 네트워크/프록시 지연 여부 확인.
  - **warmup에서 `chat() got an unexpected keyword argument 'timeout_s'`**
  - `llm_client.chat()`은 `timeout_s` 파라미터를 받지 않습니다. 호출부에서 해당 인자를 제거하세요.

---

## 변경 이력 (요약)

- vLLM/TinyLlama 직접 호출 → **GPT-4o-mini (OpenAI 호환)** 로 통합
- `.env` 경로 고정(`ai/llm_runtime/.env`)로 **어디서 실행해도 일관 동작**
- 공용 `chat()` 래퍼로 **서버·스크립트 간 중복 로직 제거**
