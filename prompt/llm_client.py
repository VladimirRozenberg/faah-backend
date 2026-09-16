"""Shared language-model client configuration."""

import os

from openai import AsyncOpenAI


client = AsyncOpenAI(
    api_key=os.getenv("FAAH_API_KEY"),
    base_url="https://api.deepseek.com",
)

"""
SOURCES :   https://platform.openai.com/docs/guides/asyncio --DOCUMENTATION OPENAI
            https://api-docs.deepseek.com/ -- DOCUMENTATION DEEPSEEK
"""
