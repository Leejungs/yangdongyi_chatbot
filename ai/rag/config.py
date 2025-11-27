# ai/rag/config.py
# ------------------------------------------------
# 역할: RAG 설정을 환경변수에서 읽어오고, 안전하게 파싱/기본값 보정
# ------------------------------------------------
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]  # ai/

def _getenv_list(key: str, default_list):
    """쉼표(,) 또는 세미콜론(;) 구분 리스트 파싱"""
    raw = os.getenv(key, "")
    if not raw.strip():
        return default_list
    parts = [p.strip() for p in raw.replace(";", ",").split(",")]
    return [p for p in parts if p]

# --- PDF 데이터 ---
DATA_DIR = os.getenv("DATA_DIR", str(BASE_DIR / "data" / "docs"))
PDF_GLOBS = _getenv_list("PDF_GLOBS", ["*.pdf"])  # 예: "*.pdf,rules/*.pdf"

# --- Mongo ---
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "schoolbot")
MONGO_COLL = os.getenv("MONGO_COLL", "notices")      # "*"이면 모든 컬렉션
MONGO_UPDATED_FIELD = os.getenv("MONGO_UPDATED_FIELD", "updated_at")

# --- Chroma 벡터DB ---
CHROMA_DIR = os.getenv("CHROMA_DIR", str(BASE_DIR / "rag" / "chroma_db"))
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "school_corpus")
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "jhgan/ko-sroberta-multitask")

# --- 청크/검색 파라미터 ---
def _getint(k, d): 
    try: return int(os.getenv(k, d))
    except: return d

CHUNK_SIZE = _getint("CHUNK_SIZE", 1200)
CHUNK_OVERLAP = _getint("CHUNK_OVERLAP", 200)
TOP_K = _getint("TOP_K", 6)
FINAL_K = _getint("FINAL_K", 3)

# 활성 컬렉션 이름이 들어있는 “포인터 파일”
ACTIVE_NAME_FILE = os.getenv("ACTIVE_NAME_FILE", str(BASE_DIR / "rag" / "ACTIVE_COLLECTION.txt"))
# 기본 prefix (A/B 뒤에 붙일 공통 접두)
COLLECTION_PREFIX = os.getenv("COLLECTION_PREFIX", "school_corpus")