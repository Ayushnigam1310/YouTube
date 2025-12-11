# Deliverables & Verification

## Checklist

- [x] Codebase scaffolded and modules implemented.
- [x] Unit tests for all tasks passing (`pytest`).
- [x] Dockerfile and docker-compose.yml created.
- [x] CI workflow created.
- [x] Smoke test implemented.

## Verification Steps

1.  **Run Tests**: `pytest` should pass all tests.
2.  **Start Services**: `docker compose up --build` should start web, worker, redis, postgres.
3.  **Health Check**: `curl http://localhost:8000/health` should return `{"status":"ok"}`.
4.  **Enqueue Job**: `make enqueue TOPIC="Test Video"` should queue a job.
5.  **Check Output**: Check `./media` folder for generated artifacts (script, voice, video, thumbnail).
