"""Configuration and JSON requests shared by skill classification and translation."""

import json
import os
import re
from urllib.parse import urlsplit

import httpx

from .config import config_dir
from .library import read_json, write_json

SETTINGS = "ai.json"


class NotConfigured(Exception):
    pass


def configuration() -> dict:
    data = read_json(config_dir() / SETTINGS, {})
    env_url = os.environ.get("SKILLDESK_AI_BASE_URL", "")
    saved_url = data.get("baseUrl", "")
    base_url = env_url or saved_url
    # A key belongs to the service it was configured with.
    saved_key = data.get("apiKey", "") if base_url.rstrip("/") == saved_url.rstrip("/") else ""
    env_key = os.environ.get("SKILLDESK_AI_API_KEY", "") if env_url else ""
    return {
        "baseUrl": base_url,
        "model": os.environ.get("SKILLDESK_AI_MODEL") or data.get("model", ""),
        "apiKey": env_key or saved_key,
    }


def public_settings() -> dict:
    data = configuration()
    return {
        "baseUrl": data["baseUrl"],
        "model": data["model"],
        "hasKey": bool(data["apiKey"]),
        "enabled": bool(data["baseUrl"] and data["model"]),
        "baseFromEnv": bool(os.environ.get("SKILLDESK_AI_BASE_URL")),
        "modelFromEnv": bool(os.environ.get("SKILLDESK_AI_MODEL")),
        "keyFromEnv": bool(
            os.environ.get("SKILLDESK_AI_BASE_URL") and os.environ.get("SKILLDESK_AI_API_KEY")
        ),
    }


def configure(base_url: str, model: str, api_key: str | None) -> dict:
    if base_url:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme not in {"https", "http"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("请输入完整的 HTTP(S) 服务地址，例如 http://localhost:11434/v1")
    settings = read_json(config_dir() / SETTINGS, {})
    if settings.get("baseUrl", "").rstrip("/") != base_url.rstrip("/"):
        settings.pop("apiKey", None)
    settings.update(baseUrl=base_url.rstrip("/"), model=model.strip())
    if api_key is not None:
        settings["apiKey"] = api_key
    write_json(config_dir() / SETTINGS, settings)
    return public_settings()


def chat_json(client: httpx.Client, settings: dict, instruction: str, inputs: list):
    response = client.post(
        settings["baseUrl"].rstrip("/") + "/chat/completions",
        headers={"Authorization": "Bearer " + settings["apiKey"]} if settings["apiKey"] else {},
        json={
            "model": settings["model"],
            "messages": [
                {"role": "system", "content": instruction},
                {"role": "user", "content": json.dumps(inputs, ensure_ascii=False)},
            ],
        },
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    if not isinstance(content, str):
        raise TypeError("AI 服务没有返回文本")
    answer = content.strip()
    if answer.startswith("\x60\x60\x60"):
        answer = re.sub(r"^\x60{3}(?:json)?\s*|\s*\x60{3}$", "", answer)
    return json.loads(answer)
