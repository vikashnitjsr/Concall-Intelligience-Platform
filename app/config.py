"""Application configuration, loaded from environment / .env."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./concall.db"

    # LLM
    llm_provider: str = "stub"  # "stub" | "openai" | "azure_openai"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-2024-08-06"
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_deployment: str = "gpt-4o"
    azure_openai_api_version: str = "2024-08-01-preview"

    # Extraction
    extraction_provider: str = "pymupdf"  # "stub" | "pymupdf" | "pdfplumber" | "azure_docintel"
    azure_docintel_endpoint: str = ""
    azure_docintel_api_key: str = ""

    blob_dir: str = "./data/blobs"


settings = Settings()
