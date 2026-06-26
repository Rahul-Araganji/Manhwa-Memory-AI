import os
import yaml
from pathlib import Path
from typing import Any, Dict

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DEFAULT_CONFIG = {
    "database": {
        "db_path": "data/manga_memory.db"
    },
    "downloader": {
        "base_dir": "data",
        "rate_limit_delay": 1.5,
        "max_retries": 3,
        "headless": True,
        "timeout_ms": 30000
    },
    "cleaner": {
        "remove_duplicates": True,
        "duplicate_threshold": 4,
        "remove_credits": True,
        "blacklisted_hashes": []
    },
    "ocr": {
        "languages": ["en"],
        "use_gpu": False
    },
    "gemini": {
        "api_key": "",
        "model": "gemini-2.5-flash"
    }
}

class Config:
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = Path(config_path)
        self.data = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        config = DEFAULT_CONFIG.copy()
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    user_config = yaml.safe_load(f)
                    if user_config:
                        # Deep merge dictionaries
                        for key, val in user_config.items():
                            if isinstance(val, dict) and key in config:
                                config[key].update(val)
                            else:
                                config[key] = val
            except Exception as e:
                print(f"Warning: Failed to load config.yaml ({e}). Using defaults.")
        
        # Override Gemini API key from environment if set
        env_key = os.environ.get("GEMINI_API_KEY")
        if env_key:
            config["gemini"]["api_key"] = env_key

        return config

    @property
    def db_path(self) -> str:
        return self.data["database"]["db_path"]

    @property
    def downloader(self) -> Dict[str, Any]:
        return self.data["downloader"]

    @property
    def cleaner(self) -> Dict[str, Any]:
        return self.data["cleaner"]

    @property
    def ocr(self) -> Dict[str, Any]:
        return self.data["ocr"]

    @property
    def gemini(self) -> Dict[str, Any]:
        return self.data["gemini"]
