"""LLM provider factory."""

from services.llm.base import LLMClient
from utils.logger import setup_logger

logger = setup_logger(__name__)


def create_llm_client(config) -> LLMClient:
    """Фабрика: создать LLM-клиент на основе config.llm.provider."""
    provider = config.get("llm.provider", "gemini")

    if provider in ("claude", "anthropic"):
        from services.llm.claude import ClaudeLLMClient

        model = config.get("claude.model", "claude-sonnet-4-6")
        max_tokens = config.get("claude.max_tokens", 4096)
        temperature = config.get("claude.temperature", 0.3)

        logger.info("Используем Claude LLM: %s (temp=%.1f)", model, temperature)
        return ClaudeLLMClient(
            api_key=config.anthropic_api_key,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            prompt_loader=config.load_prompt,
        )
    else:
        from services.llm.gemini import GeminiLLMClient

        model = config.get("gemini.model", "gemini-2.0-flash")
        logger.info("Используем Gemini LLM: %s", model)
        return GeminiLLMClient(
            api_key=config.gemini_api_key,
            model_name=model,
            prompt_loader=config.load_prompt,
        )
