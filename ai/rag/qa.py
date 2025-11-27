# qa.py
from typing import Dict
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate
from langchain_core.language_models import BaseChatModel
from langchain_core.vectorstores import VectorStoreRetriever

# ------------------------------
# 1️⃣ 프롬프트 템플릿 정의
# ------------------------------
SYSTEM_PROMPT = (
    "You are a strict assistant for Dongyang Mirae University rules.\n"
    "Answer ONLY from the provided CONTEXT in Korean.\n"
    "If the answer is missing, say you cannot find it and DO NOT guess.\n"
    "Always append citations like [p.페이지번호]. Keep the answer concise."
)

PROMPT_TEMPLATE = f"""{{system_prompt}}\n\n---\n\nCONTEXT:\n{{context}}\n\n---\n\nQUESTION: {{question}}\n\nANSWER:"""

QA_PROMPT = PromptTemplate.from_template(PROMPT_TEMPLATE)

# ------------------------------
# 2️⃣ 답변 생성 함수 (개선)
# ------------------------------
def answer(query: str, retriever: VectorStoreRetriever, llm: BaseChatModel) -> Dict:
    """
    질문(query)과 Retriever, LLM을 받아 RAG 답변과 소스를 반환
    """
    # RetrievalQA 체인 설정
    chain = RetrievalQA.from_chain_type(
        llm=llm,
        retriever=retriever,
        return_source_documents=True,
        chain_type_kwargs={"prompt": QA_PROMPT.partial(system_prompt=SYSTEM_PROMPT)}
    )

    # 체인 실행
    result = chain.invoke({"query": query})

    # 소스 문서 포맷팅
    sources = []
    if result.get("source_documents"):
        for doc in result["source_documents"]:
            # 메타데이터를 안전하게 추출
            meta = doc.metadata or {}
            sources.append({
                "_id": meta.get("_id"),
                "page_content": doc.page_content, # 청크 내용
                # 필요 시 다른 메타데이터 필드 추가
                # "page": meta.get("page"),
                # "title": meta.get("title"),
            })

    return {
        "answer": result.get("result", "답변을 생성할 수 없습니다."),
        "sources": sources
    }