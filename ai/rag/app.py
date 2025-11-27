# app.py
from fastapi import FastAPI, HTTPException
from datetime import datetime, timedelta
from pymongo import MongoClient
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_openai import ChatOpenAI
import os
from dotenv import load_dotenv
from typing import Optional, List, Dict
from pydantic import BaseModel
import time
import traceback

from . import config  # 설정 파일 임포트
from . import qa      # qa 모듈 임포트
from .store import get_client, get_collection

# .env 파일 로드
load_dotenv()

app = FastAPI(title="RAG Backend", version="1.1")

# ------------------------------
# 1️⃣ 전역 설정 및 초기화 (앱 실행 시 1회)
# ------------------------------
try:
    # MongoDB 클라이언트
    client = MongoClient(config.MONGO_URI)
    db = client[config.MONGO_DB]
    collection = db[config.MONGO_COLL]

    # LangChain 구성요소
    embedding = HuggingFaceEmbeddings(model_name=config.EMBEDDING_MODEL_NAME)
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.CHUNK_SIZE,
        chunk_overlap=config.CHUNK_OVERLAP
    )
    vectorstore = Chroma(
        persist_directory=config.CHROMA_DIR,
        embedding_function=embedding
    )
    llm = ChatOpenAI(model="gpt-4-turbo")

except Exception as e:
    # 초기화 실패 시, 앱이 시작되지 않도록 처리하거나 로깅
    raise RuntimeError(f"초기화 실패: {e}")

# ------------------------------
# 2️⃣ Pydantic 모델 (stt-tts-sample/app.py에서 가져옴)
# ------------------------------
class RagChatReq(BaseModel):
    query: str
    top_k: int = 6
    filters: Optional[Dict[str, List[str]]] = None

# ------------------------------
# 3️⃣ JSON 평탄화 함수
# ------------------------------
def flatten_json(data, prefix=""):
    texts = []
    if isinstance(data, dict):
        for k, v in data.items():
            texts.extend(flatten_json(v, f"{prefix}{k}: "))
    elif isinstance(data, list):
        for i, item in enumerate(data):
            texts.extend(flatten_json(item, f"{prefix}[{i}] "))
    else:
        if data not in [None, ""]:
            texts.append(f"{prefix}{data}")
    return texts

# ------------------------------
# 4️⃣ FastAPI Endpoints
# ------------------------------

@app.post("/ingest")
def update_vector_db(days: int = 1, force_reingest: bool = False):
    """
    MongoDB 문서를 벡터DB에 업데이트합니다.
    - force_reingest=True: 모든 문서를 강제로 다시 인덱싱합니다.
    - force_reingest=False: 최근 N일 이내 변경된 문서만 증분 인덱싱합니다.
    """
    since = datetime.utcnow() - timedelta(days=days)
    query = {} if force_reingest else {config.MONGO_UPDATED_FIELD: {"$gte": since}}

    # 모든 컬렉션을 순회하며 문서를 찾음
    all_docs = []
    for coll_name in db.list_collection_names():
        if coll_name.startswith('system.'):
            continue
        collection = db[coll_name]
        docs = list(collection.find(query))
        all_docs.extend(docs)

    if not all_docs:
        return {"message": "No documents to update based on the given criteria."}

    new_docs = []
    ids_to_delete = []
    for doc in all_docs:
        doc_id = str(doc["_id"])
        ids_to_delete.append(doc_id)
        
        flat_text = "\n".join(flatten_json(doc))
        for chunk in splitter.split_text(flat_text):
            new_docs.append(
                Document(page_content=chunk, metadata={"_id": doc_id})
            )

    if ids_to_delete:
        vectorstore.delete(ids=ids_to_delete)

    if new_docs:
        vectorstore.add_documents(documents=new_docs)
        vectorstore.persist()

    return {"message": f"{len(new_docs)} chunks updated from {len(all_docs)} documents"}

@app.post("/chat")
def rag_chat(req: RagChatReq):
    """
    RAG 질의 → qa.py를 통해 답변 생성 (기존 /ask 개선)
    """
    q = (req.query or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="Empty query")

    t0 = time.perf_counter()
    try:
        k = max(1, min(8, req.top_k or 6))
        retriever = vectorstore.as_retriever(
            search_kwargs={"k": k, "filter": req.filters}
        )
        
        result = qa.answer(
            query=q,
            retriever=retriever,
            llm=llm
        )
        
        latency_ms = int((time.perf_counter() - t0) * 1000)
        result["latency_ms"] = latency_ms
        return result

    except TimeoutError:
        raise HTTPException(status_code=504, detail="LLM timeout")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"RAG failed: {e}")

@app.post("/preview")
def rag_preview(req: RagChatReq):
    """
    RAG 검색 결과 미리보기 (stt-tts-sample/app.py에서 가져옴)
    """
    try:
        k = max(1, min(20, req.top_k or 6))
        retriever = vectorstore.as_retriever(
            search_kwargs={"k": k, "filter": req.filters}
        )
        chunks = retriever.get_relevant_documents(req.query)
        
        return {"chunks": [
            {"page": c.metadata.get("page"),
             "source_type": c.metadata.get("source_type"),
             "title": c.metadata.get("title"),
             "dataset": c.metadata.get("dataset"),
             "score": c.metadata.get("score", 0), # Langchain Document는 score를 직접 제공하지 않음
             "text": c.page_content[:500]}
        for c in chunks]}
    except Exception as e:
        raise HTTPException(500, f"Preview failed: {e}")

# ------------------------------
# 5️⃣ Health & Debug Endpoints
# ------------------------------

@app.get("/health")
def health():
    """
    시스템 상태 확인 (기존 /health 개선)
    """
    try:
        client.admin.command('ping')
        mongo_status = "ok"
    except Exception:
        mongo_status = "error"

    return {
        "status": "ok",
        "mongo_status": mongo_status,
        "chroma_dir_exists": os.path.exists(config.CHROMA_DIR),
    }

@app.get("/debug/mongo")
def rag_debug_mongo():
    """
    MongoDB 디버그 정보 (stt-tts-sample/app.py에서 가져옴)
    """
    out = {"ok": False, "uri": config.MONGO_URI, "db": config.MONGO_DB, "coll": config.MONGO_COLL, "updated_field": config.MONGO_UPDATED_FIELD}
    try:
        cli = MongoClient(config.MONGO_URI)
        db  = cli[config.MONGO_DB]
        colls = [c for c in db.list_collection_names() if not c.startswith("system.")]
        out["collections"] = colls
        samples = {}
        for name in colls[:5]:
            doc = db[name].find_one()
            samples[name] = {k: doc.get(k) for k in ["title","subject","content","body","summary","text","updated_at"]} if doc else None
        out["samples"] = samples
        out["ok"] = True
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        out["trace"] = traceback.format_exc(limit=3)
    return out

@app.get("/debug/count")
def rag_debug_count():
    """
    ChromaDB 문서 수 확인 (stt-tts-sample/app.py에서 가져옴)
    """
    try:
        cli = get_client(config.CHROMA_DIR)
        col = get_collection(cli, name=config.COLLECTION_NAME)
        return {"chroma_dir": config.CHROMA_DIR, "collection": config.COLLECTION_NAME, "count": col.count()}
    except Exception as e:
        return {"error": str(e)}
