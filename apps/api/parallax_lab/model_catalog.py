"""Known response-capable models; credentials and operator choices stay server-side."""

import os

LOCAL_MODELS = {
    "momentum": {"id": "momentum", "name": "Momentum", "provider": "Local baseline", "description": "Follows observed price momentum over the strategy window."},
    "mean-reversion": {"id": "mean-reversion", "name": "Mean reversion", "provider": "Local baseline", "description": "Buys observed weakness relative to the trailing mean."},
    "buy-and-hold": {"id": "buy-and-hold", "name": "Buy & hold", "provider": "Local baseline", "description": "Maintains the strategy allocation as a passive control."},
}
OPENAI_MODELS = {
    f"openai:{model}": {"id": f"openai:{model}", "name": name, "provider": "OpenAI", "description": description}
    for model, name, description in (
        ("gpt-6-luna", "GPT-6 Luna", "Efficient structured paper-trading decisions."),
        ("gpt-6.1-sol", "GPT-6.1 Sol", "Structured decisions with balanced reasoning and speed."),
        ("gpt-6-astra", "GPT-6 Astra", "Higher-cost reasoning for structured paper-trading decisions."),
    )
}
MODELS = {**LOCAL_MODELS, **OPENAI_MODELS}
MAX_CLOUD_CALLS = 6
OPENAI_LIMITS = ((60, 6), (86_400, 24))
OPENAI_TIMEOUT = 15
OPENAI_REPLAY_TIMEOUT = 60


def available_openai_models() -> tuple[str, ...]:
    if not os.getenv("OPENAI_API_KEY", "").strip() or os.getenv("PARALLAX_OPENAI_NETWORK", "1") != "1":
        return ()
    allowed = {value.strip() for value in os.getenv("PARALLAX_OPENAI_MODELS", "gpt-6-luna,gpt-6.1-sol,gpt-6-astra").split(",")}
    return tuple(key for key in OPENAI_MODELS if key.removeprefix("openai:") in allowed)


def available_models() -> list[dict]:
    return [*LOCAL_MODELS.values(), *(OPENAI_MODELS[key] for key in available_openai_models())]
