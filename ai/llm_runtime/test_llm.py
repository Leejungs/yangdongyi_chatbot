# ================================================================
# test_llm.py
# ------------------------------------------------
# 🧪 역할:
# - LLM 클라이언트가 정상 작동하는지 단독으로 테스트
# - .env 설정(OPENAI_API_KEY, MODEL) 확인
# 실행:
#   cd T_project/ai/llm_runtime
#   python test_llm.py
# ================================================================

from llm_client import chat

if __name__ == "__main__":
    # 테스트용 메시지 정의
    user_input = "너는 어떤 모델이야?"
    messages = [
        {"role": "system", "content": "You are a friendly assistant."},
        {"role": "user", "content": user_input}
    ]

    print("User:", user_input)
    print("Assistant:", chat(messages))
