# RAG (Retrieval-Augmented Generation)

학교 전용 챗봇의 **지식 검색·응답(RAG)** 모듈입니다.  
여러 **PDF**와 **MongoDB** 데이터에서 텍스트를 추출·임베딩하여 **Chroma** 벡터DB에 인덱싱하고,
사용자 질문시 연관 청크를 검색해 **LLM(GPT-4o-mini)** 으로 답변을 생성합니다.

> 인덱싱(업데이트)과 질문 응답을 **분리**할 수 있도록 설계되었습니다.  
> 운영 모드에서는 인덱싱(A)을 백그라운드/스케줄링하고, 서비스(B)는 최신 스냅샷만 사용합니다.

---

## 📁 디렉토리 구조

```
ai/rag/
├─ __init__.py               # 패키지 초기화(비워둬도 OK)
├─ config.py                 # RAG 설정(경로/DB/청크/검색 파라미터)
├─ store.py                  # Chroma 클라이언트/컬렉션 생성 유틸
├─ ingest.py                 # PDF/Mongo → 임베딩 → Chroma upsert
├─ auto_index.py             # 변경 감지/강제 인덱싱 제어 (manifest)
├─ retriever.py              # 쿼리 임베딩/유사도 검색/필터 빌드
├─ qa.py                     # 검색 결과를 LLM 프롬프트로 조합/최종 답변
├─ chroma_db/                # 로컬 Chroma 데이터 디렉토리(.gitignore 권장)
└─ requirements.txt          # 서버 의존성
```

---

## 🧩 파일별 역할

### `config.py`
- 데이터 경로(`DATA_DIR`, `PDF_GLOBS`), Mongo 설정(`MONGO_*`), Chroma 경로, 청크/검색 파라미터를 정의합니다.
- `.env`에 동일 키가 있으면 **환경변수로 오버라이드**됩니다.

### `store.py`
- `get_client(base_path)`, `get_collection(client, name=...)`
- Chroma Persistent client를 생성하고 기본 컬렉션을 반환합니다.

### `ingest.py`
- **PDF 인덱싱**: PyMuPDF/`pdfplumber`로 본문·표 추출 → 청크 → 임베딩 → `col.add()`  
- **Mongo 인덱싱**: 다수 컬렉션 순회, 다양한 필드(`title`, `content`, `내용`, `content_list` …)를 평탄화,  
  **증분 인덱싱**(워터마크 기반) 지원 → 청크 → 임베딩 → upsert  
- 배치 임베딩(`EMBED_BATCH`)으로 대량 처리 최적화.

### `auto_index.py`
- **변경 감지/강제 인덱싱** 진입점.  
- PDF 파일 fingerprint + Mongo 컬렉션별 최신 타임스탬프 맵을 **manifest.json**에 저장/비교.  
- `ensure_index_ready(force: bool)`로 호출(질의 시 자동 인덱싱은 환경변수로 ON/OFF).

### `retriever.py`
- 쿼리 임베딩(e5 시리즈) → 벡터 검색(`top_k`) → (선택) 필터(`dataset` 등) 적용.  
- 응답에는 스코어/메타(`title`, `page`, `dataset`, `uri`, `source_type`)가 포함됩니다.

### `qa.py`
- 검색된 청크를 컨텍스트로 **GPT-4o-mini**에 전달해 최종 답변 생성.  
- 과도한 컨텍스트 방지를 위한 **문자수 제한**(`RAG_MAX_*`)과 LLM **타임아웃**을 적용.

---

## ⚙️ 환경변수(.env) 키 (요약)

> 위치: **`stt-tts-sample/.env`** (프로젝트 전체 공용)  
> rag/config.py는 `os.getenv()`로 값을 읽습니다.

```ini
# === RAG / Data ===
DATA_DIR=C:\...\ai\data\docs
PDF_GLOBS=*.pdf

# === Mongo ===
MONGO_URI=실제 URI 값      # Compass URI 그대로
MONGO_DB=depatement_db
MONGO_COLL=*
MONGO_UPDATED_FIELD=updated_at

# 접속/쿼리 타임아웃
MONGO_CONNECT_TIMEOUT_MS=3000
MONGO_SERVER_SELECTION_TIMEOUT_MS=3000
MONGO_SOCKET_TIMEOUT_MS=30000

# === 임베딩/검색/LLM ===
EMBEDDER_MODEL=intfloat/multilingual-e5-small
EMBED_BATCH=64
CHUNK_SIZE=1200
CHUNK_OVERLAP=200
TOP_K=6

# 컨텍스트/시간 제한
RAG_MAX_CHUNKS=4
RAG_MAX_CHARS_PER_CHUNK=900
RAG_MAX_CONTEXT_CHARS=9000
LLM_TIMEOUT_S=12

# === 인덱싱 제어 ===
WARMUP_ON_STARTUP=false          # 서버 스타트업 시 웜업 비활성(대규모 데이터 권장)
AUTO_INDEX_ON_QUERY=false        # 질의 시 자동 인덱싱 비활성(운영 권장)
MONGO_INCREMENTAL=true           # Mongo 증분 인덱싱(워터마크: ai/rag/chroma_db/mongo_watermarks.json)
MONGO_SAMPLE_COLLECTIONS=0       # 변경감지 샘플링(0=전체)
HF_HOME=C:\hf_cache
TRANSFORMERS_CACHE=C:\hf_cache
HF_HUB_DISABLE_SYMLINKS_WARNING=1
```

> 풀 재인덱싱이 필요하면 `MONGO_INCREMENTAL=false`로 실행하거나
> `ai/rag/chroma_db/mongo_watermarks.json`을 삭제 후 `/rag/ingest`를 호출하세요.

---

## 🛠️ FastAPI 엔드포인트(서버: `stt-tts-sample/app.py`)

### 1) 인덱싱(강제)
```bash
# PowerShell
curl.exe -s -X POST "http://127.0.0.1:9000/rag/ingest" `
  -H "Content-Type: application/json" `
  -d "{}" | ConvertFrom-Json | ConvertTo-Json -Depth 8
```

### 2) 미리보기(검색 결과 상위 청크, POST 전용)
```bash
curl.exe -s -X POST "http://127.0.0.1:9000/rag/preview" `
  -H "Content-Type: application/json" `
  -d '{"query":"휴학 신청 기간","top_k":6}'
```

### 3) 질의(최종 답변 + 출처, POST 전용)
```bash
curl.exe -s -X POST "http://127.0.0.1:9000/rag/chat" `
  -H "Content-Type: application/json" `
  -d '{"query":"재학연기 조건 알려줘","top_k":6}'
```

### 4) Mongo 상태 확인(디버그)
```bash
curl.exe -s "http://127.0.0.1:9000/rag/debug/mongo"
```

### 5) 웜업
```bash
curl.exe -s -X POST "http://127.0.0.1:9000/warmup/start"
curl.exe -s "http://127.0.0.1:9000/warmup/status"
```

### 6) 인덱스 문서 수 확인
```bash
curl.exe -s "http://127.0.0.1:9000/rag/debug/count"
```

> 브라우저 UI(`static/index.html`)의 **RAG 탭**에서도 동일 호출이 가능합니다.

---

## 🚀 실행 순서 (로컬 개발)

1. 가상환경 & 의존성 설치
   ```bash
   pip install -r ai/stt-tts-sample/requirements.txt
   ```
2. `.env` 세팅(위 키 참고)
3. 서버 실행
   ```bash
   cd ai/stt-tts-sample
   uvicorn app:app --reload --port 9000
   ```
4. 인덱싱 1회 실행 → 이후 질문
   ```bash
   # 강제 인덱싱
   curl.exe -s -X POST "http://127.0.0.1:9000/rag/ingest" -H "Content-Type: application/json" -d "{}"
   # 또는 브라우저 RAG 탭에서 "인덱싱 시작" 버튼
   ```

---

## ⚙️ 운영 모드 가이드 (A/B 분리)

- **A(업데이트)**: `/rag/ingest`를 배치/스케줄러에서 주기 호출.
  최신 스냅샷이 `ai/rag/chroma_db/`에 반영됩니다.
- **B(서빙)**: `/rag/chat`은 기존 스냅샷만 사용(환경변수 `AUTO_INDEX_ON_QUERY=false`일 때).
  첫 질문 지연 없이 즉답이 가능합니다.  
- 재시작 시 웜업은 **비활성화**(대규모 데이터 기준). 필요하면 `/warmup/start` 수동 호출.

---

## 🧯 트러블 슈팅

- **Non-empty lists are required for 'ids' in add.**
  - `ingest.py`의 `ids` 리스트가 비어있을 때 발생. 텍스트가 비어 추가되지 않는 경우.  
    → Mongo 문서의 텍스트 필드 후보를 확장/보정했는지 확인.

- **metadatas 타입 에러(None 변환 실패)**  
  - Chroma 메타는 `None`을 허용하지 않습니다. `_sanitize_meta()`로 보정합니다.

- **Mongo 타임아웃/연결 실패**
  - `MONGO_*_TIMEOUT_MS`를 조정, Compass URI/Firewall 확인.

- **초기 질문만 느림**
  - 인덱싱/모델 캐시/쿼리 임베딩이 **첫 1회**만 지연 가능.  
    운영에서는 A/B 분리 또는 서버 시작 후 `/warmup/start`로 선행 준비.

- **HF symlink 경고(Windows)**
  - `HF_HUB_DISABLE_SYMLINKS_WARNING=1` 설정 또는 Windows 개발자 모드 활성.

- **502 Bad Gateway (RAG failed…)**
  - `/rag/debug/count` 값이 0이면 스냅샷이 비어있습니다 → `/rag/ingest`로 먼저 인덱싱.
  - `/rag/preview`가 동작하는지 확인(POST 전용).

---

## 성능 팁

- 대량 데이터: `EMBEDDER_MODEL=intfloat/multilingual-e5-small`(속도↑) + `EMBED_BATCH` 확대.  
- 검색 품질: `CHUNK_SIZE/OVERLAP` 조정, `TOP_K`=6~8 권장.  
- LLM 비용/속도: `RAG_MAX_*`로 컨텍스트 절제, `LLM_TIMEOUT_S` 8~12초.

---

## 변경 이력(요약)

- **다중 PDF + Mongo 전체 컬렉션** 인덱싱 지원
- **증분 인덱싱**(워터마크) 추가 → 재인덱싱 비용 절감
- **A/B 분리 운영 가이드** 도입 → 사용자 첫 응답 지연 제거
- Windows/PowerShell 친화 CLI 예시 제공
