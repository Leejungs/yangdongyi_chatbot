# AI Monorepo (STT · TTS · RAG · LLM Runtime)

이 디렉토리는 **학교 전용 챗봇**을 구성하는 모든 AI 컴포넌트를 담고 있습니다.
- **LLM Runtime**: OpenAI 호환 LLM 호출을 표준화 (`GPT-4o-mini` 기본)
- **RAG**: PDF + MongoDB 데이터를 임베딩/검색하여 근거 기반 답변 생성
- **STT/TTS Sample Server**: FastAPI로 STT, TTS, Voice Chat, RAG를 빠르게 시험

> 운영을 염두에 둔 **A/B 분리 전략**을 지원합니다.  
> - **A(업데이트)**: 크롤링·인덱싱 배치/스케줄 작업  
> - **B(서빙)**: 인덱스 스냅샷만 읽어 빠른 질문 응답

---

## 📦 디렉토리 구조

```
ai/
├─ llm_runtime/           # OpenAI 호환 LLM 호출 모듈(.env: API 키/모델)
├─ rag/                   # RAG 파이프라인(인덱싱/검색/QA, Chroma DB)
├─ stt-tts-sample/        # FastAPI 서버(STT/TTS/VoiceChat/RAG + Warmup)
├─ data/
│  └─ docs/               # PDF 원문(학칙 등) 배치 폴더
└─ (기타)                 # 유틸/스크립트 추가 예정
```

- 각 서브 폴더에는 별도의 `README_*.md`가 있습니다:
  - `README_llm_runtime.md`
  - `README_rag.md`
  - `README_stt_tts_sample.md`

---

## 🔧 필수 준비물

- Python 3.10+
- (Windows) **FFmpeg** 권장: `winget install Gyan.FFmpeg`
- 인터넷 접속(Hugging Face 임베더 모델, OpenAI API)
- (옵션) MongoDB Atlas/Cluster (Compass URI 사용)

---

## 🔑 환경변수 파일 위치

- **LLM 키/모델**: `ai/llm_runtime/.env`
  ```ini
  OPENAI_API_KEY=실제 키 값
  OPENAI_MODEL=gpt-4o-mini
  # OPENAI_BASE_URL=https://api.openai.com/v1  # 프록시/게이트웨이 사용 시
  LLM_TIMEOUT_S=12
  ```

- **RAG/서버 설정**: `ai/stt-tts-sample/.env`
  ```ini
  # === RAG / Data ===
  DATA_DIR=C:\path\to\ai\data\docs
  PDF_GLOBS=*.pdf

  # === Mongo ===
  MONGO_URI=실제 URI 값
  MONGO_DB=depatement_db
  MONGO_COLL=*                    # '*' 또는 콤마로 나열
  MONGO_UPDATED_FIELD=updated_at

  # === 인덱싱/웜업 ===
  WARMUP_ON_STARTUP=false         # 대규모 데이터면 false 권장
  AUTO_INDEX_ON_QUERY=false       # 운영: false 권장 (A/B 분리)

  # === 임베딩/검색/LLM 한도 ===
  EMBEDDER_MODEL=intfloat/multilingual-e5-small
  EMBED_BATCH=64
  RAG_MAX_CHUNKS=4
  RAG_MAX_CHARS_PER_CHUNK=900
  RAG_MAX_CONTEXT_CHARS=9000
  LLM_TIMEOUT_S=12

  # === HF 캐시(Windows) ===
  HF_HOME=C:\hf_cache
  TRANSFORMERS_CACHE=C:\hf_cache
  HF_HUB_DISABLE_SYMLINKS_WARNING=1
  ```

> ⚠️ `.env` 파일은 **Git에 커밋 금지**. 실제 배포 시에는 OS 비밀 변수/KeyVault 권장.

---

## 🚀 빠른 시작 (개발자 로컬)

1) 가상환경 & 설치
```powershell
cd ai\stt-tts-sample
python -m venv .venv
. .venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

2) `.env` 구성
- `ai/llm_runtime/.env` : OpenAI 키/모델
- `ai/stt-tts-sample/.env` : RAG/서버 설정

3) 서버 실행
```powershell
uvicorn app:app --reload --port 9000
```
브라우저에서 `http://127.0.0.1:9000` → 테스트 UI 열기.

4) (최초 1회) 인덱싱
```powershell
curl.exe -X POST "http://127.0.0.1:9000/rag/ingest" -H "Content-Type: application/json" -d "{}"
```
인덱스 문서 수 확인:
```powershell
curl.exe "http://127.0.0.1:9000/rag/debug/count"
```

5) 질문/미리보기
```powershell
# Preview
$body = @{ query = "휴학은 최대 몇 학기?"; top_k = 6 } | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:9000/rag/preview -Method POST -ContentType application/json -Body $body

# Chat
$body = @{ query = "결혼 시 필요한 증빙서류는?"; top_k = 6 } | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:9000/rag/chat -Method POST -ContentType application/json -Body $body
```

---

## 🧭 운영 모드(A/B 분리) 가이드

- **A(업데이트 서버)**  
  - 크롤링 → `/rag/ingest` 호출(또는 모듈 직접 실행)로 **Chroma 스냅샷 갱신**  
  - 스케줄(예: 매일 03:00)로 자동화
- **B(서빙 서버)**  
  - `/rag/chat`은 인덱스를 **읽기 전용**으로 사용 → **첫 질문도 즉답**  
  - `AUTO_INDEX_ON_QUERY=false`, 필요 시 `/warmup/start`로 사전 준비

> 두 서버가 **같은 `ai/rag/chroma_db/`**를 참조하도록 마운트/동기화(NAS, 배포 아티팩트, S3 동기화 등)하면 안정적입니다.

---

## 🧪 구성 요소별 요약

### 1) llm_runtime
- 공통 LLM 호출 레이어.  
- `.env` 한 곳에서 키/모델/타임아웃 관리.  
- `chat(messages, ...) -> str` 인터페이스로 간단하게 사용.

### 2) rag
- PDF + Mongo **다중 소스** 인덱싱, **증분 인덱싱**(워터마크) 지원.  
- `auto_index.py`의 `ensure_index_ready(force=...)`로 강제/변경 감지 인덱싱.  
- `retriever.py`(유사도 검색), `qa.py`(LLM 프롬프트 조합).

### 3) stt-tts-sample
- FastAPI 서버 + 테스트용 프론트(`static/index.html`).  
- STT(faster-whisper), TTS(edge-tts), Voice Chat, RAG API 제공.  
- `/warmup/status|start`로 임베더/인덱스/LLM을 미리 올려 **첫 질문 지연 최소화**.

---

## 🧯 트러블슈팅

- **`/rag/chat` 첫 호출이 느림**  
  - 서버 시작 직후 모델/임베더 캐시 로딩 때문. 운영에서는 A/B 분리 또는 `/warmup/start` 사용.

- **`Non-empty lists are required for 'ids' in add.`**  
  - Mongo 문서에서 텍스트 후보가 비어 청크가 생성되지 않았을 때.  
  - `ingest.py`의 텍스트 수집 필드 후보와 `_sanitize_meta()` 로직 확인.

- **`Method Not Allowed` (GET → POST)**  
  - `/rag/chat`, `/rag/preview`는 **POST 전용**입니다.

- **Windows에서 HF symlink 경고**  
  - `.env`에 `HF_HUB_DISABLE_SYMLINKS_WARNING=1` 지정 또는 Windows 개발자 모드.

---

## 🗺️ 로드맵(예시)

- 멀티테넌트(학과별 파라미터) 필터링 강화
- 응답 템플릿화/포맷팅(표/리스트)
- 관리자 대시보드(인덱스 상태, 크롤링 성공률, 비용 모니터링)

---

## 라이선스 / 보안 메모

- 데이터/모델/키는 각 공급자 약관을 준수하세요.
- `.env`/비밀값은 **절대 커밋 금지**. 운영 환경에서는 Secret Manager 사용을 권장합니다.
