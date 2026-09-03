from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Sport Risk Analyst Pro", version="0.1.0")

class Health(BaseModel):
    status: str
    service: str

@app.get("/", response_model=Health)
async def root():
    return Health(status="ok", service="sport-ai-pro")

@app.get("/health", response_model=Health)
async def health():
    return Health(status="ok", service="sport-ai-pro")
