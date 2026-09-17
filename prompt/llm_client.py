"""Shared language-model client configuration."""

import os
from functools import lru_cache

from openai import AsyncOpenAI


client = AsyncOpenAI(
    api_key=os.getenv("FAAH_API_KEY"),
    base_url="https://api.deepseek.com",
)


@lru_cache(maxsize=1)
def get_alibaba_client() -> AsyncOpenAI:
    """Return the OpenAI-compatible Alibaba Model Studio client."""

    api_key = os.getenv("FAAH_ALIBABA_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "FAAH_ALIBABA_API_KEY is required for financial analysis"
        )

    base_url = os.getenv("FAAH_ALIBABA_BASE_URL", "").strip().rstrip("/")
    workspace_id = os.getenv("FAAH_ALIBABA_WORKSPACE_ID", "").strip()

    if not base_url and workspace_id:
        base_url = (
            f"https://{workspace_id}.eu-central-1.maas.aliyuncs.com/"
            "compatible-mode/v1"
        )

    if not base_url:
        raise RuntimeError(
            "Set FAAH_ALIBABA_BASE_URL to the OpenAI-compatible API Host "
            "shown by the Frankfurt Model Studio workspace, or set "
            "FAAH_ALIBABA_WORKSPACE_ID"
        )

    return AsyncOpenAI(api_key=api_key, base_url=base_url)


"""
SOURCES :   https://platform.openai.com/docs/guides/asyncio --DOCUMENTATION OPENAI
            https://api-docs.deepseek.com/ -- DOCUMENTATION DEEPSEEK
"""
