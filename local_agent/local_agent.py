import json
import os
import sys

_this_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.environ.get(
    "BRICK_PROJECT_ROOT",
    os.path.dirname(_this_dir),
)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from http.server import HTTPServer, BaseHTTPRequestHandler
from tools.builtins import (
    GetCpuUsage, GetMemoryUsage, GetDiskUsage,
    GetSystemInfo, GetTemperatures, GetInodeUsage,
    ListProcesses, SearchProcess, KillProcess, SetProcessPriority,
    GetConnections, PingHost, GetNetworkIO,
    TailLog, FindLargeFiles, ListDirectory,
    ListServices, GetServiceStatus, GetLoginHistory, GetCronJobs,
)

PORT = 8765

_TOOLS = {t.name: t for t in [
    GetCpuUsage(), GetMemoryUsage(), GetDiskUsage(),
    GetSystemInfo(), GetTemperatures(), GetInodeUsage(),
    ListProcesses(), SearchProcess(), KillProcess(), SetProcessPriority(),
    GetConnections(), PingHost(), GetNetworkIO(),
    TailLog(), FindLargeFiles(), ListDirectory(),
    ListServices(), GetServiceStatus(), GetLoginHistory(), GetCronJobs(),
]}
_TOOL_SCHEMAS = [t.ollama_schema() for t in _TOOLS.values()]

def _json_response(handler, code: int, data: dict):
    body = json.dumps(data).encode()
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)

class AgentHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # quiet

    def do_GET(self):
        if self.path == "/tools":
            _json_response(self, 200, {"tools": _TOOL_SCHEMAS})
        elif self.path == "/health":
            _json_response(self, 200, {"status": "ok", "tools": len(_TOOLS)})
        else:
            _json_response(self, 404, {"error": "Not found"})

    def do_POST(self):
        if self.path != "/run":
            _json_response(self, 404, {"error": "Not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            tool_name = body.get("tool")
            params = body.get("params", {})
            if not tool_name or tool_name not in _TOOLS:
                _json_response(self, 400, {"error": f"Unknown tool: {tool_name!r}"})
                return
            result = _TOOLS[tool_name].run(**params)
            _json_response(self, 200, {"result": result})
        except Exception as e:
            _json_response(self, 500, {"error": str(e)})

if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), AgentHandler)
    print(f"[LocalAgent] Listening on :{PORT} — no auth, hub identifies by IP")
    print(f"[LocalAgent] {len(_TOOLS)} tools registered")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[LocalAgent] Shutting down.")