"""Claude access layer.

Routes (picked from config):
  * openrouter - Anthropic SDK pointed at OpenRouter's Anthropic-compatible
                 endpoint, with an ordered model fallback chain (PRD: "accessed
                 via OpenRouter API gateway for fallback routing").
  * anthropic  - the Claude API directly, with server-side refusal fallbacks.
  * offline    - no key configured; callers get None and use heuristics.

Every agent treats a None result as "decide deterministically", so an LLM
outage degrades plan quality instead of breaking the app.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import anthropic

from .config import Settings, get_settings

log = logging.getLogger(__name__)

_RETRY_NEXT_MODEL = (
    anthropic.RateLimitError,
    anthropic.InternalServerError,
    anthropic.NotFoundError,
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
    anthropic.PermissionDeniedError,
)


class LLM:
    def __init__(self, settings: Settings):
        self.mode = settings.llm_mode
        self._structured_ok = True
        self.client: anthropic.AsyncAnthropic | None = None
        self.models: list[str] = []

        if self.mode == "openrouter":
            self.client = anthropic.AsyncAnthropic(
                base_url=settings.openrouter_base_url,
                auth_token=settings.openrouter_api_key,
                timeout=120.0,
                max_retries=1,
            )
            fallbacks = [m.strip() for m in settings.openrouter_fallback_models.split(",") if m.strip()]
            self.models = [settings.openrouter_model, *fallbacks]
        elif self.mode == "anthropic":
            self.client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, timeout=120.0)
            self.models = [settings.anthropic_model]

    @property
    def available(self) -> bool:
        return self.client is not None

    @property
    def label(self) -> str:
        return f"{self.mode}:{self.models[0]}" if self.models else "offline"

    async def _create(self, model: str, system: str, prompt: str, schema: dict | None, effort: str, max_tokens: int):
        assert self.client is not None
        output_config: dict[str, Any] = {"effort": effort}
        if schema is not None and self._structured_ok:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        messages = [{"role": "user", "content": prompt}]

        if self.mode == "anthropic":
            # Direct Claude API: let the server re-route policy refusals.
            return await self.client.beta.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
                output_config=output_config,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        return await self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            output_config=output_config,
        )

    async def json(
        self,
        *,
        system: str,
        prompt: str,
        schema: dict,
        effort: str = "low",
        max_tokens: int = 16000,
    ) -> dict | None:
        """Ask Claude for a JSON object matching `schema`. Returns None on failure."""
        if not self.available:
            return None

        for model in self.models:
            for _attempt in range(2):
                try:
                    full_prompt = prompt
                    if not self._structured_ok:
                        full_prompt += (
                            "\n\nRespond with ONLY a JSON object (no prose, no code fences) matching this JSON Schema:\n"
                            + json.dumps(schema)
                        )
                    resp = await self._create(model, system, full_prompt, schema, effort, max_tokens)
                except anthropic.BadRequestError as exc:
                    if self._structured_ok:
                        # Gateway may not support structured outputs; retry in prompt-JSON mode.
                        log.warning("structured output rejected by %s (%s); using prompt-JSON mode", model, exc.message)
                        self._structured_ok = False
                        continue
                    log.error("LLM bad request on %s: %s", model, exc.message)
                    return None
                except anthropic.AuthenticationError:
                    log.error("LLM authentication failed - check your API key")
                    return None
                except _RETRY_NEXT_MODEL as exc:
                    log.warning("LLM model %s unavailable (%s); trying next", model, type(exc).__name__)
                    break
                except anthropic.APIStatusError as exc:
                    log.warning("LLM error on %s: %s %s", model, exc.status_code, exc.message)
                    break

                if resp.stop_reason == "refusal":
                    log.warning("LLM %s declined the request", model)
                    break
                text = "".join(b.text for b in resp.content if b.type == "text")
                data = _parse_json(text)
                if data is not None:
                    return data
                log.warning("LLM %s returned unparseable JSON", model)
                break
        return None


def _parse_json(text: str) -> dict | None:
    text = text.strip()
    if not text:
        return None
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None
    return None


_llm: LLM | None = None


def get_llm() -> LLM:
    global _llm
    if _llm is None:
        _llm = LLM(get_settings())
    return _llm


# --- schema helpers -----------------------------------------------------------


def obj(properties: dict[str, dict], required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required if required is not None else list(properties),
        "additionalProperties": False,
    }


STR = {"type": "string"}
NUM = {"type": "number"}
INT = {"type": "integer"}
BOOL = {"type": "boolean"}


def arr(items: dict) -> dict:
    return {"type": "array", "items": items}


def nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}
