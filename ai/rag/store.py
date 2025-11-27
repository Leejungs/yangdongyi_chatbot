# ================================================================
# store.py
# ------------------------------------------------
# 💾 역할:
#   - Chroma 벡터DB 초기화 및 Collection 관리
#   - 문서 삽입/검색용 기본 인터페이스 제공
# ================================================================

import os
import chromadb
from .config import CHROMA_DIR, ACTIVE_NAME_FILE, COLLECTION_PREFIX

def _read_active_name():
    try:
        with open(ACTIVE_NAME_FILE, "r", encoding="utf-8") as f:
            name = f.read().strip()
            if name: return name
    except Exception:
        pass
    # 초기값 없으면 A로
    return f"{COLLECTION_PREFIX}_A"

def get_client(persist_dir: str = CHROMA_DIR):
    return chromadb.Client(chromadb.config.Settings(
        is_persistent=True, persist_directory=persist_dir
    ))

def get_collection(client, name: str | None = None):
    name = name or _read_active_name()
    try:
        return client.get_collection(name=name)
    except Exception:
        return client.create_collection(name=name)