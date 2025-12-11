import json
import logging
from typing import Dict, List, Optional, Any

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(Exception),
    reraise=True
)
def _call_llm_with_retry(client, model: str, messages: List[Dict[str, str]]) -> str:
    """Helper to call LLM with retries."""
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            response_format={"type": "json_object"}
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        raise e

def generate_script(
    topic: str,
    language: str = "en",
    length_target_seconds: int = 480,
    llm_client: Any = None
) -> Dict[str, Any]:
    """
    Generates a YouTube script for a given topic using an LLM.

    Args:
        topic: The topic of the video.
        language: Target language (default "en").
        length_target_seconds: Target length in seconds (default 480).
        llm_client: An OpenAI-compatible client instance. Required.

    Returns:
        A dictionary containing the script components:
        - title: str
        - hook: str
        - sections: List[Dict[str, str]]
        - cta: str
        - tags: List[str]
        - shorts: List[str]

    Raises:
        ValueError: If content is not allowed or response is invalid/malformed.
    """
    if llm_client is None:
        raise ValueError("llm_client is required")

    prompt_template = """You are a concise expert content writer for YouTube. Output valid JSON only.

Input:
	•	topic: {topic}
	•	target_language: {language}
	•	length_seconds: {length_target_seconds}

Produce a JSON object:
{{
“title”: “<clickable title under 80 chars>”,
“hook”: “<10-15s hook that promises a result>”,
“sections”: [
{{“heading”: “<heading 1>”, “body”: “<paragraph 1 - 40-90 words>”, “b_roll”:””}},
…
],
“cta”: “”,
“tags”:[“tag1”,“tag2”,”…”],
“shorts”:[ “short clip script 1”, “short clip script 2” ]
}}
Rules:
	•	Keep JSON strict, no extra commentary.
	•	Each “body” must be actionable and include one explicit example.
	•	Do not produce disallowed content (hate, illegal, sexual, violent). If topic seems disallowed, return:
{{“error”:“content_not_allowed”,“reason”:””}}"""

    formatted_prompt = prompt_template.format(
        topic=topic,
        language=language,
        length_target_seconds=length_target_seconds
    )

    messages = [
        {"role": "system", "content": "You are a helpful assistant that outputs JSON."},
        {"role": "user", "content": formatted_prompt}
    ]

    try:
        content = _call_llm_with_retry(llm_client, "gpt-3.5-turbo", messages)
    except Exception as e:
        raise ValueError(f"Failed to get response from LLM: {e}")

    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError("invalid_response") from e

    if "error" in data and data["error"] == "content_not_allowed":
        reason = data.get("reason", "Unknown reason")
        raise ValueError("content_not_allowed", reason)

    required_keys = ["title", "hook", "sections", "cta", "tags", "shorts"]
    missing_keys = [k for k in required_keys if k not in data]
    
    if missing_keys:
        raise ValueError("invalid_response")

    if not isinstance(data.get("sections"), list):
        raise ValueError("invalid_response")

    return data
