from fastapi import FastAPI

app = FastAPI(title="YouTube Factory API")

@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "ok"}
