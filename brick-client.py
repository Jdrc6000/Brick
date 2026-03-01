import os, json, logging
from flask import Flask, request, jsonify, abort

PORT = 7700
BRICK_SERVER_IP = "192.168.0.67"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("brick-client")

try:
    from tools.builtins import (
        GetCpuUsage, GetMemoryUsage, GetDiskUsage,
        GetSystemInfo, GetTemperatures, GetInodeUsage,
        ListProcesses, SearchProcess, KillProcess, SetProcessPriority,
        GetConnections, PingHost, GetNetworkIO,
        TailLog, FindLargeFiles, ListDirectory,
        ListServices, GetServiceStatus, GetLoginHistory, GetCronJobs,
        SandboxExec, SandboxStatus, SandboxWriteFile, SandboxReadFile, SandboxInstallPackage, SandboxListFiles, SandboxReset,
        WebSearch
    )
    from tools.registry import ToolRegistry
except ImportError as e:
    raise SystemExit(
        f"Could not import tool modules: {e}\n"
        "Make sure the 'tools/' directory is in the same folder as brick-client.py"
    )

registry = ToolRegistry()
for tool_cls in [
    GetCpuUsage, GetMemoryUsage, GetDiskUsage,
    GetSystemInfo, GetTemperatures, GetInodeUsage,
    ListProcesses, SearchProcess, KillProcess, SetProcessPriority,
    GetConnections, PingHost, GetNetworkIO,
    TailLog, FindLargeFiles, ListDirectory,
    ListServices, GetServiceStatus, GetLoginHistory, GetCronJobs,
    SandboxExec, SandboxStatus, SandboxWriteFile, SandboxReadFile, SandboxInstallPackage, SandboxListFiles, SandboxReset,
    WebSearch
]:
    registry.register(tool_cls())

app = Flask(__name__)

def get_client_ip() -> str:
    if request.headers.get("X-Forwarded-For"):
        return request.headers["X-Forwarded-For"].split(",")[0].strip()
    return request.remote_addr

def require_pi(f):
    """Only accept requests from the configured Brick server IP."""
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        ip = get_client_ip()
        if BRICK_SERVER_IP and ip != BRICK_SERVER_IP:
            log.warning("REJECTED request from %s (expected %s)", ip, BRICK_SERVER_IP)
            abort(403)
        return f(*args, **kwargs)
    return decorated

@app.route("/health", methods=["GET"])
def health():
    """Pi uses this to verify the daemon is reachable before sending tool calls."""
    return jsonify({"ok": True, "tools": registry.names()})

@app.route("/execute", methods=["POST"])
@require_pi
def execute():
    body = request.get_json(silent=True) or {}
    name = body.get("name", "").strip()
    params = body.get("parameters") or {}

    if not name:
        return jsonify({"result": None, "error": "Missing 'name' field"}), 400

    log.info("execute: %s(%s)", name, params)

    try:
        tool = registry.get(name)
        result = tool.run(**params)
        return jsonify({"result": str(result), "error": None})
    except KeyError as e:
        msg = f"Unknown tool: {name!r}. Available: {registry.names()}"
        log.error(msg)
        return jsonify({"result": None, "error": msg}), 404
    except TypeError as e:
        msg = f"Bad parameters for {name!r}: {e}"
        log.error(msg)
        return jsonify({"result": None, "error": msg}), 422
    except Exception as e:
        msg = f"Tool {name!r} raised an error: {e}"
        log.exception(msg)
        return jsonify({"result": None, "error": msg}), 500

@app.route("/schemas", methods=["GET"])
@require_pi
def schemas():
    """Return all tool schemas (useful for debugging)."""
    return jsonify({"schemas": registry.all_schemas()})

if __name__ == "__main__":
    log.info("Brick client daemon starting on port %d", PORT)
    log.info("Accepting requests from: %s", BRICK_SERVER_IP or "ANY")
    log.info("Registered tools: %s", registry.names())
    app.run(host="0.0.0.0", port=PORT, debug=False)