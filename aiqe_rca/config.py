"""AIQE RCA Engine configuration via pydantic-settings."""

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Paths
    base_dir: Path = Path(__file__).resolve().parent.parent
    rules_dir: Path = Path(__file__).resolve().parent / "rules"
    report_templates_dir: Path = Path(__file__).resolve().parent / "report" / "templates"
    models_dir: Path = Path(__file__).resolve().parent.parent / "models"

    # Embedding model
    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_device: str = "cpu"

    # Evidence association thresholds
    keyword_weight: float = 0.4
    embedding_weight: float = 0.6
    association_threshold: float = 0.18

    # Hypothesis constraints
    min_hypotheses: int = 2
    max_hypotheses: int = 4

    # LLM synthesis (phrasing only)
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.0
    llm_enabled: bool = False  # Off by default; engine works without LLM

    # Report storage
    reports_dir: Path = Path(__file__).resolve().parent.parent / "reports"

    model_config = {"env_prefix": "AIQE_", "env_file": ".env"}


settings = Settings()
