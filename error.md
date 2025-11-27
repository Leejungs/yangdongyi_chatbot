### 2025-10-14: ModuleNotFoundError 발생

**오류 원인:**
`ai/stt-tts-sample/app.py`가 `ai/rag/app.py`를 임포트할 때, `rag` 디렉토리가 파이썬 패키지로 동작합니다. 하지만 `rag/app.py` 내부의 `import config`, `import qa` 등은 상대 경로가 아닌 절대 경로로 모듈을 찾으려고 시도하여 `ModuleNotFoundError`가 발생했습니다.

**해결 방안:**
`rag/app.py` 내부의 모듈 임포트 구문을 명시적인 상대 경로(`from . import ...`)로 수정하여 패키지 내부에서 모듈을 올바르게 찾도록 합니다.
