# ai/rag/auto_index.py
# ================================================================
# 목적
# - 질의 전에 벡터 인덱스(Chroma)가 준비됐는지 확인
# - (옵션) PDF/Mongo 변경 감지 후 필요한 경우에만 재인덱싱
# - force=True로 강제 재인덱싱
#
# 환경변수
# - AUTO_INDEX_ON_QUERY=false  → 질의 시 자동 인덱싱 비활성화(권장)
# - MONGO_*_TIMEOUT_MS         → Mongo 접속 타임아웃
# - MONGO_SAMPLE_COLLECTIONS   → 변경 감지 시 확인할 컬렉션 수(0=무제한)
# ================================================================
from __future__ import annotations

import os, json, threading, glob, datetime
from typing import Optional, List, Dict

from .config import (
    DATA_DIR, PDF_GLOBS, CHROMA_DIR,
    MONGO_URI, MONGO_DB, MONGO_COLL, MONGO_UPDATED_FIELD,
)
from .ingest import ingest_all
from .store import get_client, get_collection

from pymongo import MongoClient

# ---- 옵션/타임아웃 ----
AUTO_INDEX_ON_QUERY = os.getenv("AUTO_INDEX_ON_QUERY", "false").lower() == "true"
SAMPLE_LIMIT = int(os.getenv("MONGO_SAMPLE_COLLECTIONS", "0"))  # 0=무제한

MONGO_CONNECT_TIMEOUT_MS = int(os.getenv("MONGO_CONNECT_TIMEOUT_MS", "3000"))
MONGO_SERVER_SELECTION_TIMEOUT_MS = int(os.getenv("MONGO_SERVER_SELECTION_TIMEOUT_MS", "3000"))
MONGO_SOCKET_TIMEOUT_MS = int(os.getenv("MONGO_SOCKET_TIMEOUT_MS", "30000"))

_MANIFEST_PATH = os.path.join(CHROMA_DIR, "manifest.json")
_LOCK = threading.Lock()

# ---------------- 변경 감지 유틸 ----------------
def _pdf_fingerprint() -> List[Dict]:
    """PDF 경로/크기/mtime으로 변경 여부 판단"""
    files: List[str] = []
    for pat in PDF_GLOBS:
        files.extend(glob.glob(os.path.join(DATA_DIR, pat)))
    fps = []
    for f in sorted(set(files)):
        if os.path.exists(f):
            st = os.stat(f)
            fps.append({"path": os.path.abspath(f), "size": st.st_size, "mtime": int(st.st_mtime)})
    return fps

def _mongo_client() -> MongoClient:
    return MongoClient(
        MONGO_URI,
        connectTimeoutMS=MONGO_CONNECT_TIMEOUT_MS,
        serverSelectionTimeoutMS=MONGO_SERVER_SELECTION_TIMEOUT_MS,
        socketTimeoutMS=MONGO_SOCKET_TIMEOUT_MS,
    )

def _collection_names(db) -> List[str]:
    """MONGO_COLL='*' → 모든 컬렉션, 아니면 콤마 구분 목록"""
    coll_env = (MONGO_COLL or "").strip()
    if coll_env in ("", "*"):
        return [c for c in db.list_collection_names() if not c.startswith("system.")]
    return [c.strip() for c in coll_env.split(",") if c.strip()]

def _coerce_ts(v) -> Optional[int]:
    if isinstance(v, datetime.datetime): return int(v.timestamp())
    if isinstance(v, (int, float)):      return int(v)
    return None

def _updated_field_for(_: str) -> str:
    """컬렉션별로 바꾸고 싶으면 여기서 분기"""
    return (MONGO_UPDATED_FIELD or "updated_at")

def _latest_ts_for_collection(coll, uf: str) -> int:
    """해당 컬렉션의 최신 타임스탬프(uf 우선, 없으면 _id 생성시각)"""
    try:
        doc = coll.find().sort([(uf, -1)]).limit(1).next()
        ts = _coerce_ts(doc.get(uf))
        if ts:
            return ts
    except Exception:
        pass
    try:
        doc = coll.find().sort([("_id", -1)]).limit(1).next()
        return int(doc["_id"].generation_time.timestamp())
    except Exception:
        return 0

def _mongo_latest_map(sample_limit: int = 0) -> Dict[str, int]:
    """
    {컬렉션명: 최신타임스탬프} 매핑 생성.
    실패 시 {} 반환(인덱싱 자체를 막지 않음).
    """
    out: Dict[str, int] = {}
    try:
        db = _mongo_client()[MONGO_DB]
        names = _collection_names(db)
        if sample_limit > 0:
            names = names[:sample_limit]
        for cname in names:
            coll = db[cname]
            uf = _updated_field_for(cname)
            out[cname] = _latest_ts_for_collection(coll, uf)
    except Exception:
        return {}
    return out

# ---------------- manifest I/O ----------------
def _read_manifest() -> Optional[dict]:
    try:
        with open(_MANIFEST_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def _write_manifest(state: dict) -> None:
    os.makedirs(CHROMA_DIR, exist_ok=True)
    with open(_MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

# ---------------- 인덱스 유무 ----------------
def _collection_has_data() -> bool:
    try:
        client = get_client(CHROMA_DIR)
        col = get_collection(client)  # 활성 컬렉션
        return (col.count() or 0) > 0
    except Exception:
        return False

# ---------------- 퍼블릭 API ----------------
def ensure_index_ready(force: bool = False) -> dict:
    """
    force=True  → 강제 재인덱싱
    force=False → (옵션) 변경 감지 후 필요 시 재인덱싱
    AUTO_INDEX_ON_QUERY=false이면 질의 시점 자동 인덱싱은 하지 않음
    """
    if not AUTO_INDEX_ON_QUERY and not force:
        return {"indexed": False, "reason": "disabled_on_query"}

    with _LOCK:
        pdf_fp = _pdf_fingerprint()
        mongo_map = _mongo_latest_map(0 if force else SAMPLE_LIMIT)
        manifest = _read_manifest()
        populated = _collection_has_data()

        current = {"pdf": pdf_fp, "mongo_latest": mongo_map}
        fresh = populated and (manifest == current)

        if force or not fresh:
            res = ingest_all()
            _write_manifest(current)
            return {
                "indexed": True,
                "reason": "forced" if force else "stale_or_missing",
                "result": res,
            }
        else:
            return {"indexed": False, "reason": "up_to_date"}
