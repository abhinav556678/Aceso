from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]
LOCAL_DB_URL_FILE = REPO_ROOT / ".localdb" / "url.txt"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    supabase_db_url: str = ""

    llm_mode: str = "external"          # external | onprem
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_api_key: str = ""
    llm_model: str = "openai/gpt-oss-120b"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"
    stt_model: str = "whisper-large-v3-turbo"
    handwriting_ocr: str = "auto"       # auto (only with a GPU) | on | off
    handwriting_model: str = "microsoft/trocr-base-handwritten"
    handwriting_below: float = 0.90     # clean print scores above this; a page with many regions below it is handwritten

    web_origin: str = "http://localhost:3000"

    def database_url(self) -> str:
        """Supabase if configured, else the embedded local Postgres (scripts/local_db.py)."""
        if self.supabase_db_url.strip():
            return self.supabase_db_url.strip()
        if LOCAL_DB_URL_FILE.exists():
            return LOCAL_DB_URL_FILE.read_text().strip()
        raise RuntimeError(
            "No database configured. Set SUPABASE_DB_URL in .env, "
            "or run `python scripts/local_db.py` to start the embedded local database."
        )


settings = Settings()
