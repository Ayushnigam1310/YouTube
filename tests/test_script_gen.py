import pytest
import json
from unittest.mock import MagicMock
from youtube_factory.tasks.script_gen import generate_script

# Mock object structure for OpenAI response
class MockMessage:
    def __init__(self, content):
        self.content = content

class MockChoice:
    def __init__(self, content):
        self.message = MockMessage(content)

class MockResponse:
    def __init__(self, content):
        self.choices = [MockChoice(content)]

@pytest.fixture
def mock_llm_client():
    client = MagicMock()
    return client

def test_generate_script_success(mock_llm_client):
    # Prepare valid JSON response
    valid_response = {
        "title": "How to Code",
        "hook": "Learn coding in 10 seconds.",
        "sections": [
            {"heading": "Intro", "body": "Just start typing. Example: print('hello')", "b_roll": "typing"}
        ],
        "cta": "Subscribe",
        "tags": ["coding", "python"],
        "shorts": ["clip1", "clip2"]
    }
    
    mock_llm_client.chat.completions.create.return_value = MockResponse(json.dumps(valid_response))
    
    result = generate_script("coding", llm_client=mock_llm_client)
    
    assert result["title"] == "How to Code"
    assert len(result["sections"]) == 1
    assert result["tags"] == ["coding", "python"]

def test_generate_script_content_not_allowed(mock_llm_client):
    # Prepare disallowed content response
    error_response = {
        "error": "content_not_allowed",
        "reason": "Harmful content"
    }
    
    mock_llm_client.chat.completions.create.return_value = MockResponse(json.dumps(error_response))
    
    with pytest.raises(ValueError) as excinfo:
        generate_script("bomb making", llm_client=mock_llm_client)
    
    assert "content_not_allowed" in str(excinfo.value)

def test_generate_script_invalid_json(mock_llm_client):
    # Prepare malformed JSON
    mock_llm_client.chat.completions.create.return_value = MockResponse("{not valid json")
    
    with pytest.raises(ValueError) as excinfo:
        generate_script("coding", llm_client=mock_llm_client)
        
    assert "invalid_response" in str(excinfo.value)

def test_generate_script_missing_keys(mock_llm_client):
    # Prepare JSON missing keys
    incomplete_response = {
        "title": "Incomplete"
        # missing sections, etc.
    }
    
    mock_llm_client.chat.completions.create.return_value = MockResponse(json.dumps(incomplete_response))
    
    with pytest.raises(ValueError) as excinfo:
        generate_script("coding", llm_client=mock_llm_client)
        
    assert "invalid_response" in str(excinfo.value)
