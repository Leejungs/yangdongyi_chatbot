# ai/rag/ingest.py
# ================================================================
# 역할
# - 여러 PDF + MongoDB 문서를 단일 Chroma 컬렉션에 인덱싱
# - PDF: 본문+표 추출 → 청크 → 임베딩(배치) → upsert
# - Mongo: (옵션) 증분 인덱싱(컬렉션별 워터마크) → 청크 → 임베딩(배치) → upsert
#
# 환경변수
# - EMBEDDER_MODEL=intfloat/multilingual-e5-small | ...   (기본: small)
# - EMBED_BATCH=64                                       (임베딩 배치 크기)
# - MONGO_INCREMENTAL=true|false                         (증분 인덱싱 on/off)
# ================================================================
from __future__ import annotations

from typing import List, Dict, Optional
import os, re, glob, datetime, json

# --- PDF 추출 도구 (PyMuPDF 우선) ---
try:
    import fitz  # PyMuPDF
    USE_FITZ = True
except ImportError:
    from pypdf import PdfReader
    USE_FITZ = False

import pdfplumber
from sentence_transformers import SentenceTransformer
from pymongo import MongoClient

from .config import (
    DATA_DIR, PDF_GLOBS, CHROMA_DIR, COLLECTION_NAME,
    CHUNK_SIZE, CHUNK_OVERLAP,
    MONGO_URI, MONGO_DB, MONGO_COLL, MONGO_UPDATED_FIELD,
)
from .store import get_client, get_collection

# ---------------- 설정 ----------------
EMBEDDER_MODEL = os.getenv("EMBEDDER_MODEL", "intfloat/multilingual-e5-small")
EMBED_BATCH    = int(os.getenv("EMBED_BATCH", "64"))
MONGO_INCREMENTAL = os.getenv("MONGO_INCREMENTAL", "true").lower() == "true"
_WATERMARK = os.path.join(CHROMA_DIR, "mongo_watermarks.json")

# ================================================================
# 공통 유틸 (전처리/청크/임베딩/메타 보정)
# ================================================================
def clean(text: str) -> str:
    text = text.replace("\r", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def split_paragraphs(text: str) -> List[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    return paras if paras else [text]

def to_chunks(paras: List[str], size=CHUNK_SIZE, overlap=CHUNK_OVERLAP) -> List[str]:
    buf, chunks = "", []
    for p in paras:
        if len(buf) + len(p) + 1 <= size:
            buf = (buf + "\n" + p).strip()
        else:
            if buf: chunks.append(buf)
            buf = p
    if buf: chunks.append(buf)
    if overlap > 0 and len(chunks) > 1:
        with_overlap = []
        for i, c in enumerate(chunks):
            prefix = chunks[i - 1][-overlap:] if i > 0 else ""
            with_overlap.append((prefix + "\n" + c).strip() if prefix else c)
        chunks = with_overlap
    return chunks

def _sanitize_meta(meta: Dict) -> Dict:
    """Chroma 메타 타입 보정: None 제거/기본값 강제."""
    fixed = {}
    for k, v in meta.items():
        if v is None:
            if k == "page":
                fixed[k] = 0
            # updated_at/기타 None은 제외
            continue
        fixed[k] = v
    return fixed

def _encode_in_batches(model: SentenceTransformer, docs: List[str]) -> List[List[float]]:
    """대량 문서를 배치로 임베딩(list[float])."""
    vecs: List[List[float]] = []
    for i in range(0, len(docs), EMBED_BATCH):
        batch = docs[i:i + EMBED_BATCH]
        emb = model.encode(
            [f"passage: {d}" for d in batch],
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        vecs.extend(emb.tolist())
    return vecs

# 전역 싱글톤 임베더
_model = None
def embedder() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBEDDER_MODEL)
    return _model

# ================================================================
# PDF 인덱싱
# ================================================================
def extract_text_pages(path: str) -> List[str]:
    pages = []
    if USE_FITZ:
        with fitz.open(path) as doc:
            for p in doc:
                pages.append(clean(p.get_text("text")))
    else:
        from pypdf import PdfReader  # 안전: USE_FITZ가 False일 때만 사용
        reader = PdfReader(path)
        for p in reader.pages:
            pages.append(clean(p.extract_text() or ""))
    return pages

def extract_tables_as_lines(path: str) -> List[str]:
    out = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            rows, tables = [], (page.extract_tables() or [])
            for tbl in tables:
                header = None
                if tbl and any(tbl[0]):
                    header = [(c or "").strip() for c in tbl[0]]
                for i, row in enumerate(tbl):
                    if i == 0:
                        continue
                    cells = [(c or "").strip() for c in row]
                    if not any(cells):
                        continue
                    if header and len(header) == len(cells):
                        kv = [f"{header[j]}: {cells[j]}" for j in range(len(cells))]
                        rows.append(" | ".join(kv))
                    else:
                        rows.append(" | ".join(cells))
            out.append("\n".join(rows))
    return out

def _ingest_one_pdf(path: str) -> Dict:
    text_pages  = extract_text_pages(path)
    table_pages = extract_tables_as_lines(path)
    n = max(len(text_pages), len(table_pages))

    docs, metas, ids = [], [], []
    basename = os.path.basename(path)
    mtime = int(os.stat(path).st_mtime)
    abspath = os.path.abspath(path)

    for idx_page in range(n):
        t_text  = text_pages[idx_page]  if idx_page < len(text_pages)  else ""
        t_table = table_pages[idx_page] if idx_page < len(table_pages) else ""
        merged = "\n\n".join([t_text, t_table]).strip()
        if not merged:
            continue
        for idx, chunk in enumerate(to_chunks(split_paragraphs(merged))):
            docs.append(chunk)
            metas.append({
                "source_type": "pdf",
                "source_id": abspath,
                "title": basename,
                "page": idx_page + 1,
                "uri": abspath,
                "updated_at": mtime,
                "dataset": "규정집",
            })
            ids.append(f"pdf::{abspath}::{idx_page+1}-{idx}")

    if not ids:
        return {"path": path, "pages": n, "chunks": 0}

    model  = embedder()
    embeds = _encode_in_batches(model, docs)

    client = get_client(CHROMA_DIR)
    col    = get_collection(client, name=COLLECTION_NAME)
    try:
        col.delete(ids=ids)
    except Exception:
        pass
    col.add(documents=docs, embeddings=embeds, metadatas=metas, ids=ids)
    return {"path": path, "pages": n, "chunks": len(docs)}

def ingest_pdfs(paths: Optional[List[str]] = None) -> Dict:
    if not paths:
        paths = []
        for pat in PDF_GLOBS:
            paths.extend(glob.glob(os.path.join(DATA_DIR, pat)))
    paths = sorted(set(paths))
    results = []
    for p in paths:
        if os.path.exists(p):
            results.append(_ingest_one_pdf(p))
    return {"pdf_count": len(paths), "pdf_results": results}

# ================================================================
# Mongo 인덱싱 (여러 컬렉션 / 증분 지원)
# ================================================================
def _connect_db():
    return MongoClient(MONGO_URI)[MONGO_DB]

def _collection_names(db) -> List[str]:
    coll_env = (MONGO_COLL or "").strip()
    if coll_env in ("", "*"):
        return [c for c in db.list_collection_names() if not c.startswith("system.")]
    return [c.strip() for c in coll_env.split(",") if c.strip()]

def _coerce_ts(v) -> Optional[int]:
    if isinstance(v, datetime.datetime): return int(v.timestamp())
    if isinstance(v, (int, float)):      return int(v)
    if isinstance(v, str):
        s = v.strip()
        if re.fullmatch(r"\d{10,13}", s):
            return int(s[:10])
        try:
            s2 = s.replace("Z", "").replace("T", " ")
            return int(datetime.datetime.fromisoformat(s2).timestamp())
        except Exception:
            return None
    return None

def _flatten_texts(obj, max_len=30000) -> str:
    out = []
    def walk(x):
        if isinstance(x, str):
            t = x.strip()
            if t: out.append(t)
        elif isinstance(x, dict):
            for v in x.values(): walk(v)
        elif isinstance(x, (list, tuple)):
            for v in x: walk(v)
    walk(obj)
    return "\n\n".join(out)[:max_len]

def _updated_field_for(_: str) -> str:
    return (MONGO_UPDATED_FIELD or "updated_at")

def _latest_ts(coll, uf: str) -> int:
    try:
        doc = coll.find().sort([(uf, -1)]).limit(1).next()
        ts  = _coerce_ts(doc.get(uf))
        if ts: return ts
    except Exception:
        pass
    try:
        doc = coll.find().sort([("_id", -1)]).limit(1).next()
        return int(doc["_id"].generation_time.timestamp())
    except Exception:
        return 0

def _load_watermarks() -> Dict[str, int]:
    try:
        with open(_WATERMARK, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_watermarks(wm: Dict[str, int]) -> None:
    os.makedirs(CHROMA_DIR, exist_ok=True)
    with open(_WATERMARK, "w", encoding="utf-8") as f:
        json.dump(wm, f, ensure_ascii=False, indent=2)

def ingest_mongo_all(query: Optional[Dict] = None, limit: Optional[int] = None) -> Dict:
    """
    - DB 내 여러(또는 모든) 컬렉션 순회 → 본문 구성 → 청크 → 임베딩(배치) → upsert
    - MONGO_INCREMENTAL=true면 컬렉션별 워터마크 기반 증분 인덱싱
    - 컬렉션 단위로 한 번만 col.add() 호출
    """
    db = _connect_db()
    results, total_docs = [], 0
    wm = _load_watermarks() if MONGO_INCREMENTAL else {}

    TEXT_FIELD_CANDIDATES = (
        "title","subject","content","body","summary","text","desc","description",
        "content_html","html","markdown",
        "내용","본문","요약","설명","비고","세부내용","공지내용",
        "content_list","details",
    )

    for cname in _collection_names(db):
        coll = db[cname]
        uf   = _updated_field_for(cname)

        # 증분 쿼리 결합
        q = dict(query or {})
        since = wm.get(cname, 0)
        if MONGO_INCREMENTAL and since:
            q[uf] = {"$gt": datetime.datetime.fromtimestamp(since)}

        cur = coll.find(q)
        try:
            cur = cur.sort([(uf, -1)])
        except Exception:
            cur = cur.sort([("_id", -1)])
        if limit:
            cur = cur.limit(limit)

        docs, metas, ids = [], [], []

        for rec in cur:
            # --- 본문 구성 ---
            parts = []

            ttl = rec.get("title") or rec.get("subject")
            if isinstance(ttl, str) and ttl.strip():
                parts.append(f"제목: {ttl.strip()}")

            if isinstance(rec.get("content_list"), list) and rec["content_list"]:
                parts.append(_flatten_texts(rec["content_list"]))
            if isinstance(rec.get("details"), dict) and rec["details"]:
                parts.append(_flatten_texts(rec["details"]))

            for k in TEXT_FIELD_CANDIDATES:
                if k in ("content_list", "details"):
                    continue
                v = rec.get(k)
                if isinstance(v, str) and v.strip():
                    parts.append(v.strip())
                elif isinstance(v, (list, dict)):
                    s = _flatten_texts(v)
                    if s:
                        parts.append(s)

            if not any(parts):
                continue

            full_text = "\n\n".join(parts)

            # --- 타임스탬프/URI ---
            ts = _coerce_ts(rec.get(uf))
            if ts is None:
                ts = _coerce_ts(rec.get("작성일"))
            if ts is None:
                ts = int(rec["_id"].generation_time.timestamp())
            uri = rec.get("url") or rec.get("link") or ""

            # --- 청크 & 메타/ID ---
            for idx, chunk in enumerate(to_chunks(split_paragraphs(full_text))):
                docs.append(chunk)
                metas.append(_sanitize_meta({
                    "source_type": "mongo",
                    "source_id": str(rec.get("_id")),
                    "title": (ttl or cname) or "",
                    "page": 0,
                    "uri": uri or "",
                    "updated_at": int(ts),
                    "dataset": cname or "",
                }))
                ids.append(f"mongo::{cname}::{str(rec.get('_id'))}::{idx}")

        # --- 컬렉션 단위 upsert ---
        n_docs, n_ids, n_meta = len(docs), len(ids), len(metas)
        if n_docs == 0 or n_ids == 0 or n_meta == 0:
            results.append({"collection": cname, "ingested": 0, "latest_ts": _latest_ts(coll, uf)})
            # 증분 모드면 워터마크 최신화(신규 없음 케이스)
            if MONGO_INCREMENTAL:
                latest = _latest_ts(coll, uf)
                if latest:
                    wm[cname] = max(wm.get(cname, 0), latest)
            continue

        if not (n_docs == n_ids == n_meta):
            min_n = min(n_docs, n_ids, n_meta)
            docs, ids, metas = docs[:min_n], ids[:min_n], metas[:min_n]

        model  = embedder()
        embeds = _encode_in_batches(model, docs)

        client = get_client(CHROMA_DIR)
        col    = get_collection(client, name=COLLECTION_NAME)
        try:
            col.delete(ids=ids)
        except Exception:
            pass
        col.add(documents=docs, embeddings=embeds, metadatas=metas, ids=ids)

        ing_cnt = len(docs)
        total_docs += ing_cnt
        results.append({"collection": cname, "ingested": ing_cnt, "latest_ts": _latest_ts(coll, uf)})

        # 워터마크 갱신
        if MONGO_INCREMENTAL:
            latest = _latest_ts(coll, uf)
            if latest:
                wm[cname] = max(wm.get(cname, 0), latest)

        print(f"[ingest][{cname}] docs={len(docs)} ids={len(ids)} metas={len(metas)}")

    if MONGO_INCREMENTAL:
        _save_watermarks(wm)

    return {"mongo_collections": results, "mongo_total": total_docs}

# ================================================================
# 통합 인덱싱 (PDF + Mongo)
# ================================================================
def ingest_all(pdf_paths: Optional[List[str]] = None, mongo_query: Optional[Dict] = None) -> Dict:
    res_pdf = ingest_pdfs(pdf_paths)
    try:
        res_mongo = ingest_mongo_all(mongo_query)
    except Exception as e:
        res_mongo = {"mongo_error": str(e)}
    return {"pdf": res_pdf, "mongo": res_mongo}
