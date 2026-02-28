import json
import urllib.request
import urllib.error
from tools.base import BaseTool

class RemoteTool(BaseTool):
    def __init__(self, tool_schema: dict, agent_url: str, api_key: str, device_name: str):
        fn = tool_schema.get("function", tool_schema)
        self.name = f"{fn['name']}"
        self.description = f"[{device_name}] {fn.get('description', '')}"
        self._params = fn.get("parameters", {"type": "object", "properties": {}, "required": []})
        self._agent_url = agent_url.rstrip("/")
        self._api_key = api_key
        self._device_name = device_name
        self._tool_name = fn["name"]

    def parameters(self) -> dict:
        return self._params

    def run(self, **kwargs) -> str:
        payload = json.dumps({
            "tool": self._tool_name,
            "params": kwargs,
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{self._agent_url}/run",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-API-Key": self._api_key,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode())
                return str(body.get("result", body))
        except urllib.error.HTTPError as e:
            return f"[RemoteTool] HTTP {e.code} from {self._device_name}: {e.read().decode()}"
        except urllib.error.URLError as e:
            return f"[RemoteTool] Cannot reach {self._device_name} at {self._agent_url}: {e.reason}"
        except Exception as e:
            return f"[RemoteTool] Error: {e}"

def fetch_remote_tools(agent_url: str, api_key: str, device_name: str) -> list[RemoteTool]:
    url = agent_url.rstrip("/") + "/tools"
    req = urllib.request.Request(
        url,
        headers={"X-API-Key": api_key},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            schemas = data.get("tools", [])
            tools = []
            for schema in schemas:
                try:
                    tools.append(RemoteTool(schema, agent_url, api_key, device_name))
                except Exception as e:
                    print(f"[RemoteTool] Failed to wrap tool: {e}")
            return tools
    except Exception as e:
        print(f"[RemoteTool] Failed to fetch tools from {device_name}: {e}")
        return []