"""External configuration and inward dependency boundaries."""

import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ali_diagnosis.application.orchestration.budget import RunLimits
from ali_diagnosis.application.orchestration.errors import ProviderError
from ali_diagnosis.infrastructure.model_configuration import ModelConfiguration, create_stage_agent
from ali_diagnosis.infrastructure.langgraph_runtime.llm_agent import LangChainStageAgent


PROVIDERS = ["openai", "anthropic", "deepseek", "google_genai", "groq"]


@pytest.fixture(autouse=True)
def developer_api_backend(monkeypatch):
    monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)
    monkeypatch.delenv("GOOGLE_GENAI_USE_ENTERPRISE", raising=False)


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_credential_fails_without_provider_call(monkeypatch, provider, value):
    def unexpected_call(*args, **kwargs):
        pytest.fail("Missing credentials must fail before provider initialization")

    monkeypatch.setattr("ali_diagnosis.infrastructure.model_configuration.init_chat_model", unexpected_call)
    monkeypatch.delenv("SYNTHETIC_MISSING_KEY", raising=False)
    if value is not None:
        monkeypatch.setenv("SYNTHETIC_MISSING_KEY", value)
    with pytest.raises(ProviderError, match="credential"):
        create_stage_agent(ModelConfiguration(provider=provider, model="test", api_key_env="SYNTHETIC_MISSING_KEY"),
                           RunLimits(input_usd_per_million=1, output_usd_per_million=2))


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("base_url", [None, "https://provider.invalid/custom"])
@pytest.mark.parametrize("timeout", [7.5, 90])
def test_configuration_composes_provider_without_business_logic_changes(monkeypatch, provider, base_url, timeout):
    import ali_diagnosis.infrastructure.model_configuration as module
    captured = {}

    def factory(model, **kwargs):
        captured.update(model=model, **kwargs)
        return SimpleNamespace(profile=None)

    monkeypatch.setenv("SYNTHETIC_KEY", "test-only")
    monkeypatch.setattr(module, "init_chat_model", factory)
    config = ModelConfiguration(provider=provider, model="externally-selected-model", api_key_env="SYNTHETIC_KEY",
                                base_url=base_url, request_timeout_seconds=timeout)
    monkeypatch.setenv("ALI_DIAGNOSIS_MODEL_CONFIG", config.model_dump_json())
    assert ModelConfiguration.from_environment() == config
    limits = RunLimits(input_usd_per_million=1, output_usd_per_million=2, max_seconds=30)
    assert isinstance(create_stage_agent(config, limits), LangChainStageAgent)
    assert captured["model_provider"] == provider
    assert captured["model"] == config.model
    assert captured["api_key"] == "test-only"
    assert "test-only" not in config.model_dump_json()
    assert captured["max_retries"] == (1 if provider == "google_genai" else 0)
    assert captured["max_tokens"] == limits.max_output_tokens
    assert captured["timeout"] == min(timeout, 30)
    assert captured.get("base_url") == base_url
    assert ("base_url" in captured) == (base_url is not None)
    if provider == "google_genai":
        assert captured["vertexai"] is False
    else:
        assert "vertexai" not in captured
    if provider == "deepseek":
        assert captured["extra_body"] == {"thinking": {"type": "disabled"}}
    else:
        assert "extra_body" not in captured


@pytest.mark.parametrize("provider", PROVIDERS)
def test_initialization_errors_are_sanitized(monkeypatch, provider):
    def broken_factory(*args, **kwargs):
        raise ValueError("SECRET credential in provider error")

    monkeypatch.setenv("SYNTHETIC_KEY", "SECRET")
    monkeypatch.setattr("ali_diagnosis.infrastructure.model_configuration.init_chat_model", broken_factory)
    with pytest.raises(ProviderError, match="installed extra") as error:
        create_stage_agent(ModelConfiguration(provider=provider, model="test", api_key_env="SYNTHETIC_KEY"),
                           RunLimits(input_usd_per_million=1, output_usd_per_million=2))
    assert "SECRET" not in str(error.value)
    assert error.value.__suppress_context__


@pytest.mark.parametrize("flag", ["GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_GENAI_USE_ENTERPRISE"])
def test_gemini_rejects_conflicting_backend_before_sdk_initialization(monkeypatch, flag):
    def unexpected_call(*args, **kwargs):
        pytest.fail("Conflicting Google backend must fail before SDK initialization")

    monkeypatch.setattr("ali_diagnosis.infrastructure.model_configuration.init_chat_model", unexpected_call)
    monkeypatch.setenv("SYNTHETIC_KEY", "test-only")
    monkeypatch.setenv(flag, "true")
    with pytest.raises(ProviderError, match="unset or false"):
        create_stage_agent(ModelConfiguration(provider="google_genai", model="test", api_key_env="SYNTHETIC_KEY"),
                           RunLimits(input_usd_per_million=1, output_usd_per_million=2))


def test_known_non_tool_model_is_rejected(monkeypatch):
    monkeypatch.setenv("SYNTHETIC_KEY", "test-only")
    monkeypatch.setattr("ali_diagnosis.infrastructure.model_configuration.init_chat_model",
                        lambda *a, **kw: SimpleNamespace(profile={"tool_calling": False}))
    with pytest.raises(ProviderError, match="required tool calling"):
        create_stage_agent(ModelConfiguration(provider="groq", model="non-tool-model", api_key_env="SYNTHETIC_KEY"),
                           RunLimits(input_usd_per_million=1, output_usd_per_million=2))


@pytest.mark.parametrize("provider,key_field", [
    ("openai", "openai_api_key"), ("anthropic", "anthropic_api_key"),
    ("deepseek", "api_key"), ("google_genai", "google_api_key"), ("groq", "groq_api_key"),
])
def test_real_adapter_initialization_and_stage_schema_binding(monkeypatch, provider, key_field):
    pytest.importorskip(f"langchain_{provider}")
    from ali_diagnosis.application.orchestration.contracts import OUTPUT_TYPES

    # Explicit credentials must override defaults and never fall back to another key.
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "GOOGLE_API_KEY", "GROQ_API_KEY"):
        monkeypatch.setenv(name, "unused-ambient-key")
    monkeypatch.setenv("SYNTHETIC_KEY", "test-only")
    config = ModelConfiguration(provider=provider, model="test-model", api_key_env="SYNTHETIC_KEY",
                                base_url="https://provider.invalid", request_timeout_seconds=7.5)
    limits = RunLimits(input_usd_per_million=1, output_usd_per_million=2, max_output_tokens=1024)
    agent = create_stage_agent(config, limits)
    model = agent.model
    assert getattr(model, key_field).get_secret_value() == "test-only"
    timeout_field = ("default_request_timeout" if provider == "anthropic" else
                     "timeout" if provider == "google_genai" else "request_timeout")
    assert getattr(model, timeout_field) == 7.5
    assert getattr(model, "max_output_tokens", getattr(model, "max_tokens", None)) == 1024
    for schema in OUTPUT_TYPES.values():
        bound = model.bind_tools([schema], tool_choice="any")
        assert schema.__name__ in json.dumps(bound.kwargs)
    if provider == "google_genai":
        assert not model.client.vertexai
        model.client.close()


def test_domain_and_application_do_not_import_runtime_or_provider_types():
    root = Path(__file__).resolve().parents[1] / "src" / "ali_diagnosis"
    for folder in ("domain", "application"):
        for source in (root / folder).rglob("*.py"):
            for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
                names = ([node.module or ""] if isinstance(node, ast.ImportFrom) else
                         [alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
                assert not any(name.startswith(("langgraph", "langchain", "openai", "anthropic", "groq", "google.genai",
                                                "ali_diagnosis.infrastructure")) for name in names), source
