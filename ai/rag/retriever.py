# ai/rag/retriever.py
# ================================================================
# 🔎 역할: 질문 임베딩 → Chroma에서 top-k 검색
#   - Chroma v0.5+ 에서는 include에 "ids"를 넣으면 에러가 납니다.
#   - 그래서 include=["documents","metadatas","distances"]만 요청하고,
#     반환값에 ids가 있으면 사용, 없으면 메타데이터로 대체 ID 생성합니다.
# ================================================================

# rag/retriever.py
import os
from typing import List, Dict, Optional
from .store import get_client, get_collection
from .config import CHROMA_DIR, COLLECTION_NAME, TOP_K
from sentence_transformers import SentenceTransformer
import numpy as np
from .ingest import embedder

# 단일 임베더 재사용 (ingest.py와 같은 모델명이어야 함)
_EMBEDDER = None
def _embedder():
    global _EMBEDDER
    if _EMBEDDER is None:
        import os
        model_name = os.getenv("EMBEDDER_MODEL", "intfloat/multilingual-e5-small")
        _EMBEDDER = SentenceTransformer(model_name)
    return _EMBEDDER

def _encode_query(q: str) -> np.ndarray:
    # 💡 e5는 query/passsage 프리픽스를 반드시 맞춰야 함
    emb = _embedder().encode([f"query: {q.strip()}"],
                             convert_to_numpy=True, normalize_embeddings=True)
    return emb[0]

def retrieve(query: str, k: int = 6, filters=None):
    model = embedder()
    qvec = model.encode([f"query: {query}"], convert_to_numpy=True, normalize_embeddings=True)[0]

    client = get_client(CHROMA_DIR)
    col = get_collection(client, name=COLLECTION_NAME)

    res = col.query(
        query_embeddings=[qvec.tolist()],
        n_results=k,
        include=["documents", "metadatas", "distances"],  # 'ids'는 include 대상 아님
        where=filters or None,
    )

    docs  = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]
    ids   = (res.get("ids") or [[]])[0] if res.get("ids") is not None else [None] * len(docs)

    chunks = []
    for i, doc in enumerate(docs):
        meta = metas[i] if i < len(metas) else {}
        dist = dists[i] if i < len(dists) else None
        cid  = ids[i]   if i < len(ids)   else None

        # 점수는 거리 → 유사도로 단순 변환(가까울수록 높게)
        score = None
        try:
            if dist is not None:
                score = 1.0 - float(dist)
        except Exception:
            pass

        chunks.append({
            "id": cid,
            "text": doc,
            "meta": meta or {},
            "score": score,
        })

    return chunks
