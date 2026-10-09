
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Miloš Team 3.0 TEST")

class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None

@app.get("/health")
async def health():
    return {
        "ok": True,
        "version": "3.0-test",
        "mode": "isolated"
    }

@app.get("/")
async def root():
    return {
        "service": "Miloš Team 3.0",
        "status": "Testserver bereit"
    }

@app.post("/api/chat")
async def chat(req: ChatRequest):
    return {
        "status": "TEST_READY",
        "message": "Testserver läuft. Agenten noch nicht aktiviert.",
        "session_id": req.session_id
    }
