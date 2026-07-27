import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path('.') / '.env')


class Settings:
    APP_NAME: str = "LTM Analyzer"
    APP_VERSION: str = "2.0.0"

    HOST: str = "localhost"
    PORT: int = 8000

    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

    MODEL_MAX_TOKENS: int = 8192
    MODEL_MAX_CONTEXT_SIZE: int = 150_000

    UPLOAD_DIR: Path = Path("uploads")
    MAX_FILE_SIZE: int = 50 * 1024 * 1024

    ENABLE_CACHE: bool = True
    CACHE_DIR: Path = Path("cache")
    CACHE_EXPIRY: int = 7 * 24 * 60 * 60

    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    def __init__(self):
        if not self.ANTHROPIC_API_KEY:
            import logging
            logging.getLogger("settings").warning(
                "ANTHROPIC_API_KEY no configurada — el análisis no funcionará"
            )
        os.makedirs(self.UPLOAD_DIR, exist_ok=True)
        if self.ENABLE_CACHE:
            os.makedirs(self.CACHE_DIR, exist_ok=True)


settings = Settings()
