import os
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from devices import DEVICES, DEVICE_BY_IP
from server.sessions import SessionManager

sessions = SessionManager()

app = FastAPI(title="Brick Hub")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host

def get_device(request: Request) -> dict:
    device = DEVICE_BY_IP.get(_get_client_ip(request))
    if not device:
        raise HTTPException(status_code=403, detail=f"Unknown device: {_get_client_ip(request)}")
    return device

def get_admin_device(request: Request) -> dict:
    device = get_device(request)
    if not device.get("admin"):
        raise HTTPException(status_code=403, detail="Not an admin device")
    return device

@app.get("/whoami")
async def whoami(request: Request):
    ip = _get_client_ip(request)
    device = DEVICE_BY_IP.get(ip)
    if not device:
        return {"known": False, "ip": ip}
    return {
        "known": True,
        "ip": ip,
        "name": device["name"],
        "description": device.get("description", ""),
        "tags": device.get("tags", []),
        "admin": device.get("admin", False),
    }

class ChatRequest(BaseModel):
    message: str
    device_name: str

@app.post("/chat")
async def chat(req: ChatRequest, request: Request):
    requester = get_device(request)  # must be a known device

    # Admin can chat to any device; non-admin can only chat as themselves
    if not requester.get("admin") and requester["name"] != req.device_name:
        raise HTTPException(status_code=403, detail="Non-admin devices can only chat as themselves")

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
    device = get_device(request)
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
async def list_devices(request: Request):
    get_admin_device(request)  # 403 if not admin IP
    active = set(sessions.active_sessions())
    return {
        "devices": [
            {**d, "online": d["name"] in active}
            for d in DEVICES
        ]
    }

@app.get("/admin/sessions")
async def list_sessions(request: Request):
    get_admin_device(request)
    return {"active_sessions": sessions.active_sessions()}

_web_dir = os.path.join(os.path.dirname(__file__), "..", "web")
if os.path.isdir(_web_dir):
    app.mount("/", StaticFiles(directory=_web_dir, html=True), name="web")