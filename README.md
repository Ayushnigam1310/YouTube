# YouTube Factory

Automated YouTube video generation pipeline.

## Features
- Topic to Script (LLM)
- Script to Voice (TTS)
- Assets (Pexels/Slides)
- Video Composition (MoviePy)
- Thumbnail (DALL-E/Pillow)
- Upload to YouTube

## Quickstart

1.  **Prerequisites**: Docker, Make.
2.  **Environment**: Copy `.env.example` to `.env` and fill in API keys.
    ```bash
    cp .env.example .env
    ```
    Required keys for full function: `OPENAI_API_KEY`, `ELEVENLABS_API_KEY`.
    Optional: `PEXELS_API_KEY`, `YOUTUBE_...` (for upload).

3.  **Run with Docker**:
    ```bash
    make build
    make up
    ```
    Access dashboard at http://localhost:8000.

4.  **Enqueue a Job**:
    In a new terminal:
    ```bash
    # Ensure you are in the project root
    export PYTHONPATH=$PWD
    python -m youtube_factory.worker enqueue --topic "How to wake up early" --niche "Self Improvement"
    ```
    Or if running outside docker is tricky, use the make target (requires python env):
    ```bash
    make enqueue TOPIC="My Video Topic"
    ```

## Development

- **Tests**: `make test`
- **Local Worker**: `python -m youtube_factory.worker work`

## Safety
- Review generated scripts before enabling `AUTO_PUBLISH`.
- Ensure Pexels/Assets usage complies with licenses.