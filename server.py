"""
Brick — Systems Administration Assistant
Flask web server for Raspberry Pi deployment.
Access is restricted to registered devices (by IP/hostname).
Each device gets its own persistent conversation session.
"""

import socket
import logging
from functools import wraps
from flask import Flask, request, jsonify, render_template, abort

from devices import get_device
from tools.builtins import (
    GetCpuUsage, GetMemoryUsage, GetDiskUsage,
    GetSystemInfo, GetTemperatures, GetInodeUsage,
    ListProcesses, SearchProcess, KillProcess, SetProcessPriority,
    GetConnections, PingHost, GetNetworkIO,
    TailLog, FindLargeFiles, ListDirectory,
    ListServices, GetServiceStatus, GetLoginHistory, GetCronJobs,
)
from agent import Agent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("brick")

app = Flask(__name__)

# --- Agent pool: one Agent per device session (keyed by device name) ---
_agents: dict[str, Agent] = {}

TOOLS = [
    GetCpuUsage(), GetMemoryUsage(), GetDiskUsage(),
    GetSystemInfo(), GetTemperatures(), GetInodeUsage(),
    ListProcesses(), SearchProcess(), KillProcess(), SetProcessPriority(),
    GetConnections(), PingHost(), GetNetworkIO(),
    TailLog(), FindLargeFiles(), ListDirectory(),
    ListServices(), GetServiceStatus(), GetLoginHistory(), GetCronJobs(),
]


def get_agent(device: dict) -> Agent:
    """Get or create an Agent for this device."""
    session_id = f"device-{device['name']}"
    if session_id not in _agents:
        log.info("Creating new agent session for device: %s", device["name"])
        agent = Agent(session_id=session_id, resume=True)
        agent.register_tools(*TOOLS)
        _agents[session_id] = agent
    return _agents[session_id]


def get_client_ip() -> str:
    """Extract the real client IP, respecting X-Forwarded-For if behind a proxy."""
    if request.headers.get("X-Forwarded-For"):
        return request.headers["X-Forwarded-For"].split(",")[0].strip()
    return request.remote_addr


def resolve_hostname(ip: str) -> str | None:
    """Attempt reverse DNS lookup."""
    try:
        return socket.gethostbyaddr(ip)[0]
    except (socket.herror, socket.gaierror):
        return None


def require_registered_device(f):
    """Decorator: reject requests from unregistered IPs."""
    @wraps(f)
    def decorated(*args, **kwargs):
        ip = get_client_ip()
        hostname = resolve_hostname(ip)
        device = get_device(ip, hostname)
        if not device:
            log.warning("REJECTED: ip=%s hostname=%s", ip, hostname)
            abort(403)
        log.info("ACCESS: device=%s ip=%s", device["name"], ip)
        return f(*args, device=device, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
@require_registered_device
def index(device: dict):
    return render_template("index.html", device=device)


@app.route("/api/chat", methods=["POST"])
@require_registered_device
def chat(device: dict):
    body = request.get_json(silent=True) or {}
    message = (body.get("message") or "").strip()
    if not message:
        return jsonify({"error": "Empty message"}), 400

    agent = get_agent(device)
    try:
        reply = agent.chat(message)
    except Exception as e:
        log.exception("Agent error for device %s", device["name"])
        reply = f"[Error] Something broke: {e}"

    return jsonify({"reply": reply, "device": device["name"]})


@app.route("/api/history", methods=["GET"])
@require_registered_device
def history(device: dict):
    agent = get_agent(device)
    messages = agent.history.as_chat_messages()
    return jsonify({"history": messages, "device": device["name"]})


@app.route("/api/reset", methods=["POST"])
@require_registered_device
def reset(device: dict):
    agent = get_agent(device)
    agent.reset()
    session_id = f"device-{device['name']}"
    _agents.pop(session_id, None)
    return jsonify({"ok": True, "device": device["name"]})


@app.route("/api/whoami", methods=["GET"])
@require_registered_device
def whoami(device: dict):
    ip = get_client_ip()
    return jsonify({"device": device, "ip": ip})


@app.errorhandler(403)
def forbidden(e):
    ip = get_client_ip()
    hostname = resolve_hostname(ip)
    return render_template("forbidden.html", ip=ip, hostname=hostname), 403


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)