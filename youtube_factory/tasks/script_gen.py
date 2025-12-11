# youtube_factory/tasks/script_gen.py
from __future__ import annotations
import json
import logging
import time
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from pathlib import Path

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class LLMError(Exception):
    pass


def _default_llm_call(prompt: str, llm_client=None, max_tokens: int = 800) -> str:
    """
    Wrapper to call an OpenAI-compatible client. The llm_client param is
    dependency injected for easier testing. If llm_client is None, try to import openai
    and call openai.ChatCompletion.create with gpt-3.5-turbo style.
    """
    if llm_client is None:
        try:
            import openai
        except Exception as exc:
            raise LLMError("No LLM client provided and openai is not installed") from exc
        resp = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=0.2,
        )
        # Best-effort extraction
        return resp["choices"][0]["message"]["content"]
    else:
        # Expect llm_client to have a .generate or .chat method returning text
        if hasattr(llm_client, "chat"):
            return llm_client.chat(prompt)
        elif hasattr(llm_client, "generate"):
            return llm_client.generate(prompt)
        elif callable(llm_client):
            return llm_client(prompt)
        else:
            raise LLMError("Unsupported llm_client interface")


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10),
       retry=retry_if_exception_type(LLMError))
def _call_llm_with_retry(prompt: str, llm_client=None) -> str:
    try:
        return _default_llm_call(prompt, llm_client=llm_client)
    except Exception as exc:
        logger.exception("LLM call failed, will retry")
        raise LLMError(str(exc)) from exc


def _build_prompt(topic: str, language: str, length_seconds: int) -> str:
    template = """
You are a concise expert content writer for YouTube. Output valid JSON only.

Input:
- topic: {topic}
- target_language: {language}
- length_seconds: {length_seconds}

Produce a JSON object:
{{
  "title": "<clickable title under 80 chars>",
  "hook": "<10-15s hook that promises a result>",
  "sections": [
    {{"heading": "<heading 1>", "body": "<paragraph 1 - 40-90 words>", "b_roll":"<short b-roll description>"}},
    ...
  ],
  "cta": "<short call to action and affiliate mention if any>",
  "tags":["tag1","tag2","..."],
  "shorts":[ "short clip script 1", "short clip script 2" ]
}}
Rules:
- Keep JSON strict, no extra commentary.
- Each "body" must be actionable and include one explicit example.
- Do not produce disallowed content (hate, illegal, sexual, violent). If topic seems disallowed, return:
{{"error":"content_not_allowed","reason":"<explain briefly>"}}
"""
    return template.format(topic=topic, language=language, length_seconds=length_seconds)


def _validate_script_obj(obj: Dict[str, Any]) -> None:
    """
    Validate the structure of script object. Raises ValueError on invalid or disallowed.
    """
    if not isinstance(obj, dict):
        raise ValueError("invalid_response")
    if "error" in obj:
        raise ValueError(f"content_not_allowed: {obj.get('reason', '')}")
    required_top = {"title", "hook", "sections", "cta", "tags", "shorts"}
    if not required_top.issubset(set(obj.keys())):
        raise ValueError("invalid_response")
    if not isinstance(obj["title"], str) or not obj["title"]:
        raise ValueError("invalid_response")
    if not isinstance(obj["sections"], list) or len(obj["sections"]) == 0:
        raise ValueError("invalid_response")
    for sec in obj["sections"]:
        if not all(k in sec for k in ("heading", "body", "b_roll")):
            raise ValueError("invalid_response")
    # Additional checks can be added here


def generate_script(topic: str, language: str = "en", length_target_seconds: int = 480, llm_client=None) -> Dict[str, Any]:
    """
    Generate a structured script for a YouTube video using an LLM.
    Returns a dict with keys: title, hook, sections (list), cta, tags, shorts.

    Raises ValueError for disallowed or invalid responses, or LLMError for upstream failures.
    """
    prompt = _build_prompt(topic, language, length_target_seconds)
    logger.info("Calling LLM for topic: %s", topic)
    raw = _call_llm_with_retry(prompt, llm_client=llm_client)
    # Attempt to decode JSON. Some LLMs may wrap in ``` or stray text.
    text = raw.strip()
    # Remove triple backticks if present.
    if text.startswith("```"):
        # assume ```json ... ```
        parts = text.split("```")
        # find the part that looks like JSON
        for p in parts:
            if p.strip().startswith("{"):
                text = p.strip()
                break
    # Attempt parse
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        # Try to salvage by finding first "{" and last "}" and parsing substring
        try:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1:
                obj = json.loads(text[start:end+1])
            else:
                raise
        except Exception:
            logger.exception("Failed to parse LLM response as JSON")
            raise ValueError("invalid_response")
    # Validate
    _validate_script_obj(obj)
    logger.info("Script generation successful for topic: %s", topic)
    return obj