"""
Application configuration - reads from environment variables and .env file.
All path handling uses pathlib (ADR-004).
"""
from pathlib import Path
from platformdirs import user_data_dir
from dotenv import load_dotenv
import os

load_dotenv()


class Settings:
    app_name: str = os.getenv("APP_NAME", "My Retirement Life")
    app_host: str = os.getenv("APP_HOST", "127.0.0.1")
    app_port: int = int(os.getenv("APP_PORT", "8000"))
    debug: bool = os.getenv("DEBUG", "true").lower() == "true"

    @property
    def data_dir(self) -> Path:
        """
        Returns the platform-appropriate user data directory.
        Can be overridden by setting DATA_DIR in .env
        """
        custom = os.getenv("DATA_DIR", "").strip()
        if custom:
            return Path(custom)
        return Path(user_data_dir("MyRetirementLife"))

    @property
    def store_path(self) -> Path:
        """Path to the Oxigraph triple store."""
        path = self.data_dir / "store"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def templates_dir(self) -> Path:
        return Path(__file__).parent / "templates"

    @property
    def static_dir(self) -> Path:
        path = Path(__file__).parent / "static"
        path.mkdir(parents=True, exist_ok=True)
        return path


settings = Settings()