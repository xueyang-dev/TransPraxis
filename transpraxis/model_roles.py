"""Translator/reviewer role configuration and provider capability helpers."""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional


def normalize_role_config(
    raw: Optional[Dict[str, Any]],
    *,
    fallback_provider: str = "",
    fallback_model: str = "",
    fallback_api_key: str = "",
    fallback_base_url: str = "",
) -> Dict[str, str]:
    """Normalize a role config while keeping credentials in memory only."""
    raw = raw if isinstance(raw, dict) else {}
    return {
        "provider": str(raw.get("provider") or fallback_provider or ""),
        "model": str(raw.get("model") or fallback_model or ""),
        "api_key": str(raw.get("api_key") or fallback_api_key or ""),
        "base_url": str(raw.get("base_url") or fallback_base_url or ""),
    }


def public_role_config(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Return an auditable role config with no API key."""
    config = normalize_role_config(config)
    return {
        "provider": config["provider"],
        "model": config["model"],
        "base_url": config["base_url"],
        "configured": bool(config["provider"] and config["model"]),
    }


def role_metadata(
    translator: Optional[Dict[str, Any]],
    reviewer: Optional[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    return {
        "translator": public_role_config(translator),
        "reviewer": public_role_config(reviewer),
    }


def provider_capabilities(
    providers: Dict[str, Dict[str, Any]], provider: str, model: str = ""
) -> Dict[str, bool]:
    """Return conservative capabilities; unknown endpoints are plain-text only."""
    config = providers.get(provider) or {}
    capabilities = config.get("capabilities")
    if not isinstance(capabilities, dict):
        return {"plain_text_only": True}
    result = {str(key): bool(value) for key, value in capabilities.items()}
    if not any(result.values()):
        result["plain_text_only"] = True
    return result


def make_role_call(
    call_llm: Callable[..., Any], config: Dict[str, Any]
) -> Callable[..., Any]:
    """Bind provider/model/base URL for one role, with old mock compatibility."""
    normalized = normalize_role_config(config)

    def invoke(
        provider: str,
        api_key: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> Any:
        del provider, api_key, model
        kwargs = {"temperature": temperature}
        if response_format is not None:
            kwargs["response_format"] = response_format
        try:
            return call_llm(
                normalized["provider"],
                normalized["api_key"],
                normalized["model"],
                system_prompt,
                user_prompt,
                base_url=normalized["base_url"] or None,
                **kwargs,
            )
        except TypeError:
            # Existing test/dry-run providers expose the legacy six-argument
            # signature and must keep working.
            try:
                return call_llm(
                    normalized["provider"],
                    normalized["api_key"],
                    normalized["model"],
                    system_prompt,
                    user_prompt,
                    **{"temperature": temperature},
                )
            except TypeError:
                return call_llm(
                    normalized["provider"],
                    normalized["api_key"],
                    normalized["model"],
                    system_prompt,
                    user_prompt,
                )

    return invoke
