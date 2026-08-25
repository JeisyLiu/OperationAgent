from openai import OpenAI

from app.services.settings_service import AiSettingsSecrets


def chat(
    messages: list[dict[str, str]],
    secrets: AiSettingsSecrets,
    *,
    max_tokens: int = 256,
) -> str:
    if not secrets.api_key:
        raise ValueError("API key is not configured")

    client_kwargs: dict = {"api_key": secrets.api_key}
    if secrets.base_url:
        client_kwargs["base_url"] = secrets.base_url

    client = OpenAI(**client_kwargs)
    model = secrets.model or "gpt-4o-mini"
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
    )
    content = response.choices[0].message.content
    return content or ""
