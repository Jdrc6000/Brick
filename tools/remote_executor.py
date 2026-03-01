"""
RemoteToolExecutor — routes tool calls to a registered device's brick-client daemon,
or runs them locally if no device_ip is configured or the tool is local-only.
"""
import logging
import requests
from tools.registry import ToolRegistry

log = logging.getLogger("brick.remote_executor")

CLIENT_PORT = 7700

# HTTP timeout for most tool calls.
_DEFAULT_TIMEOUT = 35 # seconds

# The sandbox_exec tool can legitimately run up to 120 s; give HTTP a small buffer.
_SANDBOX_EXEC_TIMEOUT = 130 # seconds

# Tools that always run on the server (Pi), never proxied to the client device.
LOCAL_ONLY_TOOLS: frozenset[str] = frozenset({
    "sandbox_exec",
    "sandbox_status",
    "sandbox_write_file",
    "sandbox_read_file",
    "sandbox_list_files",
    "sandbox_install_package",
    "sandbox_reset",
})

# Per-tool timeout overrides (seconds). Falls back to _DEFAULT_TIMEOUT.
_TOOL_TIMEOUTS: dict[str, int] = {
    "sandbox_exec": _SANDBOX_EXEC_TIMEOUT,
    "sandbox_install_package": _SANDBOX_EXEC_TIMEOUT,
    "sandbox_reset": 90,
    "find_large_files": 60,
    "tail_log": 15,
}

class RemoteToolExecutor:
    def __init__(self, registry: ToolRegistry, device_ip: str | None = None):
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

        if self.is_remote() and name not in LOCAL_ONLY_TOOLS:
            return self._execute_remote(name, params)
        return self._execute_local(name, params)

    def _timeout_for(self, name: str) -> int:
        return _TOOL_TIMEOUTS.get(name, _DEFAULT_TIMEOUT)

    def _execute_remote(self, name: str, params: dict) -> str:
        url = f"{self._base_url}/execute"
        payload = {"name": name, "parameters": params}
        timeout = self._timeout_for(name)
        log.info("remote execute → %s  %s(%s)", self.device_ip, name, params)

        try:
            response = requests.post(url, json=payload, timeout=timeout)
        except requests.Timeout:
            return (
                f"[RemoteToolExecutor] Timed out waiting for {name!r} "
                f"on {self.device_ip} after {timeout}s."
            )
        except requests.ConnectionError:
            return (
                f"[RemoteToolExecutor] Could not reach device at "
                f"{self.device_ip}:{CLIENT_PORT}. "
                "Is brick-client.py running on that machine?"
            )
        except requests.RequestException as e:
            return f"[RemoteToolExecutor] Request error calling {name!r}: {e}"

        # Parse JSON only after confirming we got a response at all.
        try:
            data = response.json()
        except ValueError:
            # Non-JSON body (e.g. nginx 502, HTML error page).
            return (
                f"[RemoteToolExecutor] Non-JSON response from device "
                f"(HTTP {response.status_code}) calling {name!r}. "
                f"Body preview: {response.text[:200]!r}"
            )

        if not response.ok:
            err = data.get("error") or f"HTTP {response.status_code}"
            return f"[RemoteToolExecutor] Remote error calling {name!r}: {err}"

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
            log.exception("Local tool %r raised", name)
            return f"[RemoteToolExecutor] Tool {name!r} raised an error: {e}"