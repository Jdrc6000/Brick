import logging, requests
from tools.registry import ToolRegistry

log = logging.getLogger("brick.remote_executor")

CLIENT_PORT = 7700
REQUEST_TIMEOUT = 30

# These tools must always run locally on the server — Docker lives here, not on client devices.
LOCAL_ONLY_TOOLS = {
    "sandbox_exec",
    "sandbox_status",
    "sandbox_write_file",
    "sandbox_read_file",
    "sandbox_list_files",
    "sandbox_install_package",
    "sandbox_reset",
}


class RemoteToolExecutor:
    def __init__(self, registry: ToolRegistry, device_ip: str = None):
        self.registry = registry
        self.device_ip = device_ip

    @property
    def _base_url(self) -> str:
        return f"http://{self.device_ip}:{CLIENT_PORT}"

    def is_remote(self) -> bool:
        return bool(self.device_ip)

    def ping(self) -> bool:
        """Check that the device daemon is reachable."""
        try:
            r = requests.get(f"{self._base_url}/health", timeout=5)
            return r.ok
        except requests.RequestException:
            return False

    def execute(self, tool_call: dict) -> str:
        name = tool_call.get("name")
        params = tool_call.get("parameters") or {}

        if not name:
            return "[RemoteToolExecutor] Error: tool call missing 'name' field."

        # Sandbox tools always run locally — Docker is on the server, not the client device.
        if self.is_remote() and name not in LOCAL_ONLY_TOOLS:
            return self._execute_remote(name, params)

        return self._execute_local(name, params)

    def _execute_remote(self, name: str, params: dict) -> str:
        url = f"{self._base_url}/execute"
        payload = {"name": name, "parameters": params}
        log.info("remote execute → %s  %s(%s)", self.device_ip, name, params)
        try:
            response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
            data = response.json()
        except requests.Timeout:
            return f"[RemoteToolExecutor] Timed out waiting for {name!r} on {self.device_ip}"
        except requests.ConnectionError:
            return (
                f"[RemoteToolExecutor] Could not reach device at {self.device_ip}:{CLIENT_PORT}. "
                "Is brick-client.py running on that machine?"
            )
        except Exception as e:
            return f"[RemoteToolExecutor] Unexpected error calling {name!r}: {e}"

        if data.get("error"):
            return f"[RemoteToolExecutor] Remote error: {data['error']}"

        return data.get("result", "")

    def _execute_local(self, name: str, params: dict) -> str:
        log.info("local execute: %s(%s)", name, params)
        try:
            tool = self.registry.get(name)
            result = tool.run(**params)
            return str(result)
        except KeyError as e:
            return f"[RemoteToolExecutor] Error: {e}"
        except TypeError as e:
            return f"[RemoteToolExecutor] Bad parameters for {name!r}: {e}"
        except Exception as e:
            return f"[RemoteToolExecutor] Tool {name!r} raised an error: {e}"