import json, socket, logging, requests
from functools import wraps
from flask import Flask, request, jsonify, render_template, abort, Response, stream_with_context
from devices import get_device
from tools.builtins import (
    GetCpuUsage, GetMemoryUsage, GetDiskUsage,
    GetSystemInfo, GetTemperatures, GetInodeUsage,
    ListProcesses, SearchProcess, KillProcess, SetProcessPriority,
    GetConnections, PingHost, GetNetworkIO,
    TailLog, FindLargeFiles, ListDirectory,
    ListServices, GetServiceStatus, GetLoginHistory, GetCronJobs,
    SandboxExec, SandboxInstallPackage, SandboxListFiles, SandboxReadFile, SandboxReset, SandboxStatus, SandboxWriteFile,
    WebSearch
)
from agent import Agent
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("brick")
app = Flask(__name__)
_agents: dict[str, Agent] = {}

# Local tools instantiated once for /api/tool/local (server-side stats)
_LOCAL_TOOLS = {
    "get_cpu_usage": GetCpuUsage(),
    "get_memory_usage": GetMemoryUsage(),
    "get_disk_usage": GetDiskUsage(),
    "get_system_info": GetSystemInfo(),
    "get_temperatures": GetTemperatures(),
    "get_inode_usage": GetInodeUsage(),
    "list_processes": ListProcesses(),
    "search_process": SearchProcess(),
    "get_connections": GetConnections(),
    "ping_host": PingHost(),
    "get_network_io": GetNetworkIO(),
    "web_search": WebSearch()
}

TOOLS = [
    GetCpuUsage(), GetMemoryUsage(), GetDiskUsage(),
    GetSystemInfo(), GetTemperatures(), GetInodeUsage(),
    ListProcesses(), SearchProcess(), KillProcess(), SetProcessPriority(),
    GetConnections(), PingHost(), GetNetworkIO(),
    TailLog(), FindLargeFiles(), ListDirectory(),
    ListServices(), GetServiceStatus(), GetLoginHistory(), GetCronJobs(),
    SandboxExec(), SandboxInstallPackage(), SandboxListFiles(), SandboxReadFile(), SandboxReset(), SandboxStatus(), SandboxWriteFile(),
    WebSearch()
]

def get_agent(device: dict) -> "Agent":
    session_id = f"device-{device["name"]}"
    if session_id not in _agents:
        log.info(
            "Creating new agent session for device: %s (remote ip: %s)",
            device["name"], device["ip"],
        )
        agent = Agent(
            session_id=session_id,
            resume=True,
            device_ip=device["ip"],
        )
        agent.register_tools(*TOOLS)
        _agents[session_id] = agent
    return _agents[session_id]

def get_client_ip() -> str:
    if request.headers.get("X-Forwarded-For"):
        return request.headers["X-Forwarded-For"].split(",")[0].strip()
    return request.remote_addr

def resolve_hostname(ip: str) -> str | None:
    try:
        return socket.gethostbyaddr(ip)[0]
    except (socket.herror, socket.gaierror):
        return None

def require_registered_device(f):
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

@app.route("/")
@require_registered_device
def index(device: dict):
    return render_template("index.html", device=device)

@app.route("/api/chat", methods=["POST"])
@require_registered_device
def chat(device: dict):
    """Non-streaming fallback — kept for compatibility."""
    body = request.get_json(silent=True) or {}
    message = (body.get("message") or "").strip()
    if not message:
        return jsonify({"error": "Empty message"}), 400
    agent = get_agent(device)
    try:
        reply, tool_calls = agent.chat_with_tools(message)
    except Exception as e:
        log.exception("Agent error for device %s", device["name"])
        reply = f"[Error] Something broke: {e}"
        tool_calls = []
    slim_tools = [
        {"name": tc["name"], "parameters": tc["parameters"]}
        for tc in tool_calls
    ]
    return jsonify({
        "reply": reply,
        "device": device["name"],
        "tool_calls": slim_tools,
    })

@app.route("/api/chat/stream", methods=["POST"])
@require_registered_device
def chat_stream(device: dict):
    """
    SSE streaming endpoint. Yields newline-delimited JSON events:
      {"type": "tool_start",  "name": str, "parameters": dict}
      {"type": "tool_result", "name": str, "result": str}
      {"type": "token",       "text": str}
      {"type": "error",       "message": str}
      {"type": "done"}
    """
    body = request.get_json(silent=True) or {}
    message = (body.get("message") or "").strip()
    if not message:
        return jsonify({"error": "Empty message"}), 400
    agent = get_agent(device)
    def generate():
        try:
            for event in agent.stream(message):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            log.exception("Stream error for device %s", device["name"])
            yield f"data: {json.dumps({"type": "error", "message": str(e)})}\n\n"
        finally:
            yield f"data: {json.dumps({"type": "done"})}\n\n"
    return Response(
        stream_with_context(generate()),
        content_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )

@app.route("/api/tool", methods=["POST"])
@require_registered_device
def tool_exec(device: dict):
    """
    Direct tool execution — routed through RemoteToolExecutor to the connected device (Mac).
    Used by the Device Stats page for the client machine's data.
    Does NOT touch agent memory or conversation history.
    """
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    params = body.get("parameters") or {}
    if not name:
        return jsonify({"result": None, "error": "Missing 'name' field"}), 400
    agent = get_agent(device)
    try:
        raw = agent.executor.execute({"name": name, "parameters": params})
        try:
            import ast
            result = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            try:
                result = ast.literal_eval(raw)
            except Exception:
                result = raw
        return jsonify({"result": result, "error": None})
    except Exception as e:
        log.exception("tool_exec error for tool=%s device=%s", name, device["name"])
        return jsonify({"result": None, "error": str(e)}), 500

@app.route("/api/tool/local", methods=["POST"])
@require_registered_device
def tool_exec_local(device: dict):
    """
    Direct tool execution on the Pi server itself — always local, never proxied.
    Used by the Server Metrics page to show the Pi's own stats.
    Does NOT touch agent memory or conversation history.
    """
    body = request.get_json(silent=True) or {}
    name   = (body.get("name") or "").strip()
    params = body.get("parameters") or {}
    if not name:
        return jsonify({"result": None, "error": "Missing 'name' field"}), 400
    tool = _LOCAL_TOOLS.get(name)
    if not tool:
        return jsonify({"result": None, "error": f"Tool {name!r} not available for local execution"}), 404
    try:
        result = tool.run(**params)
        # result is already a dict/list from builtins — return directly
        return jsonify({"result": result, "error": None})
    except Exception as e:
        log.exception("tool_exec_local error for tool=%s", name)
        return jsonify({"result": None, "error": str(e)}), 500

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
    session_id = f"device-{device["name"]}"
    _agents.pop(session_id, None)
    return jsonify({"ok": True, "device": device["name"]})

@app.route("/api/whoami", methods=["GET"])
@require_registered_device
def whoami(device: dict):
    ip = get_client_ip()
    return jsonify({"device": device, "ip": ip})

@app.route("/api/ollama", methods=["POST"])
def ollama_proxy():
    """
    Thin proxy to Ollama. Streams the response back to the client.
    No device auth required — only used by error pages.
    """
    body = request.get_json(silent=True) or {}
    def generate():
        try:
            with requests.post(
                "http://localhost:11434/api/generate",
                json=body,
                stream=True,
                timeout=60,
            ) as r:
                for chunk in r.iter_content(chunk_size=None):
                    if chunk:
                        yield chunk
        except requests.ConnectionError:
            yield json.dumps({"error": "Ollama not reachable"}).encode()
        except Exception as e:
            yield json.dumps({"error": str(e)}).encode()
    return Response(
        stream_with_context(generate()),
        content_type="application/x-ndjson",
    )

@app.route("/internal", methods=["GET"])
def internal():
    raise RuntimeError("HELP!")

@app.errorhandler(403)
def forbidden(e):
    ip = get_client_ip()
    hostname = resolve_hostname(ip)
    return render_template("forbidden.html", ip=ip, hostname=hostname), 403

@app.errorhandler(404)
def not_found(e):
    path = request.path
    return render_template("not_found.html", path=path), 404

@app.errorhandler(500)
def internal_error(e):
    return render_template("internal_error.html"), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)