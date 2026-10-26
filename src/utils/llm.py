"""Google Gemini LLM client wrapper.

Provides a unified async interface for all agents to call Gemini with retry and fallback models.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Optional

from google import genai
from google.genai import types
from google.genai.errors import ServerError, APIError

from src.config import settings

logger = logging.getLogger(__name__)

FALLBACK_MODELS = [
    "gemini-flash-latest",
    "gemini-2.5-flash-lite",
    "gemini-3.5-flash-lite",
    "gemini-3.5-flash",
]


def extract_json(text: str) -> Any:
    """Robustly extract and parse JSON from an LLM response string."""
    if not text:
        raise ValueError("Empty response text")
    clean = text.strip()
    try:
        return json.loads(clean)
    except Exception:
        pass

    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except Exception:
            pass

    first_bracket = min([i for i in [clean.find("["), clean.find("{")] if i != -1], default=-1)
    last_bracket = max([clean.rfind("]"), clean.rfind("}")])
    if first_bracket != -1 and last_bracket != -1 and last_bracket > first_bracket:
        try:
            return json.loads(clean[first_bracket:last_bracket + 1])
        except Exception:
            pass

    raise ValueError(f"Could not parse valid JSON from LLM response: {clean[:200]}...")


class GeminiClient:
    """Async wrapper around the Google Gemini API with fallback and grounding support."""

    def __init__(self, model: Optional[str] = None, api_key: Optional[str] = None):
        self.model = model or settings.gemini_model
        self._client = genai.Client(api_key=api_key or settings.gemini_api_key)

    async def generate(
        self,
        prompt: str,
        system_instruction: str = "",
        temperature: float = 0.7,
        max_output_tokens: int = 8192,
        response_mime_type: Optional[str] = None,
        tools: Optional[list] = None,
    ) -> str:
        """Generate a text response from Gemini with fallback models on 503."""
        config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            system_instruction=system_instruction or None,
            response_mime_type=response_mime_type,
            tools=tools,
        )

        models_to_try = [self.model] + [m for m in FALLBACK_MODELS if m != self.model]
        last_error = None

        for m in models_to_try:
            for attempt in range(2):
                try:
                    response = await self._client.aio.models.generate_content(
                        model=m,
                        contents=prompt,
                        config=config,
                    )
                    return response.text
                except (ServerError, APIError) as e:
                    last_error = e
                    if "503" in str(e) or "high demand" in str(e).lower():
                        await asyncio.sleep(1.0)
                        continue
                    else:
                        break
                except Exception as e:
                    last_error = e
                    break

        if last_error:
            raise last_error
        raise RuntimeError("Failed to generate content with all fallback models.")

    async def generate_json(
        self,
        prompt: str,
        system_instruction: str = "",
        temperature: float = 0.3,
    ) -> str:
        """Generate a JSON response from Gemini."""
        return await self.generate(
            prompt=prompt,
            system_instruction=system_instruction,
            temperature=temperature,
            response_mime_type="application/json",
        )

    async def generate_grounded(
        self,
        prompt: str,
        system_instruction: str = "",
        temperature: float = 0.3,
    ) -> str:
        """Generate content with Google Search Grounding for verified, real-world academic data."""
        return await self.generate(
            prompt=prompt,
            system_instruction=system_instruction,
            temperature=temperature,
            tools=[{"google_search": {}}],
        )
