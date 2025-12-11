# tests/test_script_gen.py
import json
import pytest
from youtube_factory.tasks import script_gen

class DummyLLM:
    def __init__(self, response_text: str):
        self.response_text = response_text
    def __call__(self, prompt: str):
        return self.response_text

def test_generate_script_success(tmp_path, monkeypatch):
    # Prepare a valid JSON response
    resp = {
        "title": "How to Save Money Fast",
        "hook": "In 10 seconds I'll show you 3 quick ways to save today",
        "sections": [
            {"heading": "Cut subscriptions", "body": "Cancel unused subs, e.g., audit your bank statement", "b_roll": "screenshot of bank app"},
            {"heading": "Meal prep", "body": "Save by cooking at home; example: plan 5 lunches", "b_roll":"cooking time-lapse"}
        ],
        "cta": "Like, subscribe, get the free checklist",
        "tags": ["finance","saving","money"],
        "shorts": ["Tip 1: cut subscriptions", "Tip 2: meal prep"]
    }
    dummy = DummyLLM(json.dumps(resp))
    out = script_gen.generate_script("save money", llm_client=dummy)
    assert out["title"] == resp["title"]
    assert isinstance(out["sections"], list)
    assert len(out["sections"]) == 2

def test_generate_script_content_not_allowed():
    dummy = DummyLLM(json.dumps({"error":"content_not_allowed","reason":"illegal content"}))
    with pytest.raises(ValueError) as excinfo:
        script_gen.generate_script("some illegal topic", llm_client=dummy)
    assert "content_not_allowed" in str(excinfo.value)

def test_generate_script_malformed_json():
    # return not a JSON
    dummy = DummyLLM("I am not JSON")
    with pytest.raises(ValueError):
        script_gen.generate_script("topic", llm_client=dummy)