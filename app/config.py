from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # "<provider>:<model>", parsed by LangChain's init_chat_model.
    # Switching providers only takes changing this string and supplying the matching API key.
    llm_model: str = "anthropic:claude-sonnet-5-5"

    # Small Chinese model (~90 MB, 512-token input limit); indexes the corpus in tens of seconds on CPU.
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    qdrant_url: str = "http://localhost:6333"
    collection: str = "cpbl_rules"

    # Holds the PDFs and the embedding model cache (git-ignored).
    data_dir: Path = Path("data")

    # In characters. Chinese is roughly one token per character, and the citation
    # header prepended to each chunk needs headroom within the model's input limit.
    chunk_size: int = 450
    chunk_overlap: int = 50


settings = Settings()
