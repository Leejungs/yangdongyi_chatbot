# ================================================================
# config.py
# ------------------------------------------------
# 🧩 역할:
#   GPT-4o-mini 관련 환경변수(키, 모델명, URL)를 로드하고 관리
#   다른 모든 모듈이 공통적으로 import 해서 사용
# ================================================================

from pydantic import BaseModel
from dotenv import load_dotenv
import os

# 현재 폴더의 .env를 명시적으로 로드
THIS_DIR = os.path.dirname(__file__)
ENV_PATH = os.path.join(THIS_DIR, ".env")
load_dotenv(ENV_PATH)

class Settings(BaseModel):
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

settings = Settings()
