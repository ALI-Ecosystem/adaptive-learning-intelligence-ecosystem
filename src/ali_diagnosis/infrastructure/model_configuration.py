"""External provider/model configuration and composition; no diagnostic policy."""

import os
from typing import Literal

from langchain.chat_models import init_chat_model
from pydantic import Field

from ali_diagnosis.application.orchestration.budget import RunLimits
from ali_diagnosis.application.orchestration.errors import ProviderError
from ali_diagnosis.domain.common import ContractModel, NonEmptyStr
from ali_diagnosis.infrastructure.langgraph_runtime.llm_agent import LangChainStageAgent


class ModelConfiguration(ContractModel):
    provider: Literal["openai", "anthropic", "deepseek", "google_genai", "groq"]
    model: NonEmptyStr
    api_key_env: NonEmptyStr
    base_url: NonEmptyStr | None = None
    request_timeout_seconds: float = Field(default=60, gt=0, allow_inf_nan=False)

    @classmethod
    def from_environment(cls) -> "ModelConfiguration":
        """Read configuration JSON; the key itself remains in its named environment variable."""
        return cls.model_validate_json(os.environ["ALI_DIAGNOSIS_MODEL_CONFIG"])


def create_stage_agent(configuration: ModelConfiguration, limits: RunLimits) -> LangChainStageAgent:
    key = os.environ.get(configuration.api_key_env)
    if not key or not key.strip():
        raise ProviderError("Configured model credential environment variable is missing")
    options = {
        "api_key": key, "max_retries": 0,
        "timeout": min(configuration.request_timeout_seconds, limits.max_seconds),
        "max_tokens": limits.max_output_tokens,
    }
    if configuration.provider == "deepseek":
        # Thinking tool calls require reasoning_content replay, which the tested
        # adapter does not serialize. Use the supported non-thinking tool mode.
        options["extra_body"] = {"thinking": {"type": "disabled"}}
    if configuration.provider == "google_genai":
        # This configuration uses Gemini Developer API keys, not Vertex/ADC.
        # The underlying SDK also reads these flags even with vertexai=False
        # on the LangChain model; reject conflicting backend selection early.
        if any(os.environ.get(name, "").lower() in ("true", "1") for name in (
            "GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_GENAI_USE_ENTERPRISE",
        )):
            raise ProviderError("google_genai requires GOOGLE_GENAI_USE_VERTEXAI and "
                                "GOOGLE_GENAI_USE_ENTERPRISE to be unset or false")
        options["vertexai"] = False
        # Google interprets this as total attempts, unlike the other adapters.
        options["max_retries"] = 1
    if configuration.base_url:
        options["base_url"] = configuration.base_url
    try:
        model = init_chat_model(configuration.model, model_provider=configuration.provider, **options)
    except Exception:
        raise ProviderError("Cannot initialize the configured provider; check configuration and installed extra") from None
    # Explicit negative metadata is useful; absent metadata is not certification.
    if (model.profile or {}).get("tool_calling") is False:
        raise ProviderError("Configured model does not support required tool calling")
    return LangChainStageAgent(
        model, output_token_parameter="max_output_tokens" if configuration.provider == "google_genai" else "max_tokens",
    )
