import os
from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from devices import DEVICES, DEVICE_BY_IP
from server.sessions import SessionManager

ADMIN_KEY = os.environ.get("BRICK_ADMIN_KEY", "admin")

sessions = SessionManager()

app = FastAPI(title="Brick Hub")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def get_device_for_request(request: Request) -> dict:
    client_ip = request.client.host

    # Support X-Forwarded-For if behind a proxy
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()

    device = DEVICE_BY_IP.get(client_ip)
    if not device:
        raise HTTPException(status_code=403, detail=f"Unknown device IP: {client_ip}")
    return device


def require_admin(x_admin_key: str = Header(...)):
    if x_admin_key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin key")

class ChatRequest(BaseModel):
    message: str
    device_name: str


@app.post("/chat")
async def chat(req: ChatRequest, x_admin_key: str = Header(...)):
    """Web UI chats with a named device. Protected by admin key."""
    require_admin(x_admin_key)

    device = next((d for d in DEVICES if d["name"] == req.device_name), None)
    if not device:
        raise HTTPException(status_code=404, detail=f"Device not found: {req.device_name}")

    agent = sessions.get_or_create(device)
    try:
        reply = agent.chat(req.message)
        return {"reply": reply, "device": device["name"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class ToolRequest(BaseModel):
    tool: str
    params: dict = {}

@app.post("/agent/run")
async def agent_run(req: ToolRequest, request: Request):
    """Called by local agents to run a tool. Auth by IP match."""
    device = get_device_for_request(request)
    agent = sessions.get_or_create(device)
    try:
        result = agent.executor.execute({"name": req.tool, "parameters": req.params})
        return {"result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/status")
async def status():
    return {
        "service": "brick-hub",
        "devices_configured": len(DEVICES),
        "active_sessions": len(sessions.active_sessions()),
    }

@app.get("/admin/devices")
async def list_devices(x_admin_key: str = Header(...)):
    require_admin(x_admin_key)
    # Return devices with online status (whether a session exists)
    active = set(sessions.active_sessions())
    return {
        "devices": [
            {**d, "online": d["name"] in active}
            for d in DEVICES
        ]
    }

@app.get("/admin/sessions")
async def list_sessions(x_admin_key: str = Header(...)):
    require_admin(x_admin_key)
    return {"active_sessions": sessions.active_sessions()}

_web_dir = os.path.join(os.path.dirname(__file__), "..", "web")
if os.path.isdir(_web_dir):
    app.mount("/", StaticFiles(directory=_web_dir, html=True), name="web")