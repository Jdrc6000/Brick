"""
Brick Sandbox tools — Brick's personal Docker environment.
The sandbox is a persistent Alpine Linux container named 'brick-sandbox'.
"""
import json
import logging
import os
import shlex
import subprocess
from pathlib import Path
from tools.base import BaseTool

log = logging.getLogger("brick.sandbox")

SANDBOX_NAME = "brick-sandbox"
EXEC_TIMEOUT = 30
MAX_OUTPUT = 4_000  # chars — truncate noisy commands

# Absolute path to docker-compose.yml, resolved at import time so it
# never depends on the process working directory.
_THIS_FILE = Path(__file__).resolve()
COMPOSE_FILE = (_THIS_FILE.parent.parent.parent / "docker-compose.yml").resolve()

# Internal helpers
def _docker_available() -> bool:
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False

def _sandbox_running() -> bool:
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Running}}", SANDBOX_NAME],
        capture_output=True, text=True, timeout=5,
    )
    return result.stdout.strip() == "true"

def _ensure_sandbox() -> tuple[bool, str]:
    """Return (ok, error_message). Start sandbox if stopped."""
    if not _docker_available():
        return False, "Docker is not available on this system."

    check = subprocess.run(
        ["docker", "inspect", SANDBOX_NAME],
        capture_output=True, timeout=5,
    )
    if check.returncode != 0:
        return False, (
            f"Sandbox container '{SANDBOX_NAME}' does not exist. "
            "Run `docker compose up -d` from the brick directory to create it."
        )

    if not _sandbox_running():
        start = subprocess.run(
            ["docker", "start", SANDBOX_NAME],
            capture_output=True, text=True, timeout=10,
        )
        if start.returncode != 0:
            return False, f"Failed to start sandbox: {start.stderr.strip()}"

    return True, ""

# Tools
class SandboxExec(BaseTool):
    name = "sandbox_exec"
    description = (
        "Execute a shell command inside Brick's personal sandbox environment "
        "(a persistent Alpine Linux Docker container). "
        "Use this to run scripts, install packages, manage files, test configs, "
        "or do anything that should happen in an isolated environment rather than the host. "
        "Brick's sandbox. Brick's rules."
    )

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to run (executed via /bin/sh -c)",
                },
                "workdir": {
                    "type": "string",
                    "description": "Working directory inside the container (default: /workspace)",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Max seconds to wait (default 30, max 120)",
                },
            },
            "required": ["command"],
        }

    def run(self, command: str, workdir: str = "/workspace", timeout: int = 30) -> dict:
        timeout = max(1, min(timeout, 120))

        # Sanitise workdir: must be an absolute path, no shell metacharacters
        # needed — it's passed as a positional arg to docker, not a shell.
        if not workdir or not workdir.startswith("/"):
            workdir = "/workspace"

        ok, err = _ensure_sandbox()
        if not ok:
            return {"error": err}

        cmd = [
            "docker", "exec",
            "--workdir", workdir,
            SANDBOX_NAME,
            "/bin/sh", "-c", command,
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout,
            )
            stdout = result.stdout[:MAX_OUTPUT]
            stderr = result.stderr[:MAX_OUTPUT]
            return {
                "command": command,
                "workdir": workdir,
                "exit_code": result.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "success": result.returncode == 0,
                "truncated": (
                    len(result.stdout) > MAX_OUTPUT or len(result.stderr) > MAX_OUTPUT
                ),
            }
        except subprocess.TimeoutExpired:
            return {"error": f"Command timed out after {timeout}s", "command": command}
        except Exception as e:
            log.exception("SandboxExec failed")
            return {"error": str(e), "command": command}

class SandboxStatus(BaseTool):
    name = "sandbox_status"
    description = (
        "Check the status of Brick's sandbox container: whether it's running, "
        "resource usage (CPU/memory), uptime, image info, and disk usage inside the container."
    )

    def parameters(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    def run(self) -> dict:
        if not _docker_available():
            return {"error": "Docker not available."}

        inspect = subprocess.run(
            ["docker", "inspect", SANDBOX_NAME],
            capture_output=True, text=True, timeout=5,
        )
        if inspect.returncode != 0:
            return {
                "exists": False,
                "running": False,
                "message": f"Container '{SANDBOX_NAME}' does not exist.",
            }

        try:
            info = json.loads(inspect.stdout)[0]
        except (json.JSONDecodeError, IndexError):
            return {"error": "Failed to parse container inspect output."}

        state = info.get("State", {})
        running = state.get("Running", False)
        result: dict = {
            "exists": True,
            "running": running,
            "status": state.get("Status", "unknown"),
            "started_at": state.get("StartedAt"),
            "image": info.get("Config", {}).get("Image"),
            "name": info.get("Name", "").lstrip("/"),
        }

        if running:
            stats = subprocess.run(
                [
                    "docker", "stats", "--no-stream",
                    "--format",
                    "{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.NetIO}}\t{{.BlockIO}}",
                    SANDBOX_NAME,
                ],
                capture_output=True, text=True, timeout=10,
            )
            if stats.returncode == 0 and stats.stdout.strip():
                parts = stats.stdout.strip().split("\t")
                if len(parts) >= 5:
                    result["resources"] = {
                        "cpu_percent": parts[0],
                        "memory_usage": parts[1],
                        "memory_percent": parts[2],
                        "network_io": parts[3],
                        "block_io": parts[4],
                    }

            df = subprocess.run(
                ["docker", "exec", SANDBOX_NAME, "df", "-h", "/"],
                capture_output=True, text=True, timeout=5,
            )
            if df.returncode == 0:
                lines = df.stdout.strip().splitlines()
                if len(lines) > 1:
                    result["disk"] = lines[1]

        return result

class SandboxWriteFile(BaseTool):
    name = "sandbox_write_file"
    description = (
        "Write a file into Brick's sandbox container at the specified path. "
        "Creates parent directories as needed. "
        "Use this to place scripts, configs, or data files into the sandbox."
    )

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path inside the container (e.g. /workspace/script.py)",
                },
                "content": {
                    "type": "string",
                    "description": "File content to write",
                },
                "mode": {
                    "type": "string",
                    "description": "File permissions (e.g. '755' for executable). Default '644'.",
                },
            },
            "required": ["path", "content"],
        }

    def run(self, path: str, content: str, mode: str = "644") -> dict:
        ok, err = _ensure_sandbox()
        if not ok:
            return {"error": err}

        # Validate mode is a safe octal string.
        if not mode or not mode.isdigit() or len(mode) not in (3, 4):
            mode = "644"

        parent = os.path.dirname(path)
        if parent and parent != "/":
            mkdir = subprocess.run(
                ["docker", "exec", SANDBOX_NAME, "mkdir", "-p", parent],
                capture_output=True, text=True, timeout=5,
            )
            if mkdir.returncode != 0:
                return {"error": f"Failed to create directory {parent}: {mkdir.stderr}"}

        write = subprocess.run(
            ["docker", "exec", "-i", SANDBOX_NAME, "sh", "-c",
             f"cat > {shlex.quote(path)}"],
            input=content, capture_output=True, text=True, timeout=10,
        )
        if write.returncode != 0:
            return {"error": f"Write failed: {write.stderr.strip()}"}

        chmod = subprocess.run(
            ["docker", "exec", SANDBOX_NAME, "chmod", mode, path],
            capture_output=True, text=True, timeout=5,
        )
        if chmod.returncode != 0:
            # File was written but chmod failed — report both outcomes.
            return {
                "success": True,
                "path": path,
                "bytes_written": len(content.encode()),
                "mode": mode,
                "chmod_warning": f"chmod failed: {chmod.stderr.strip()}",
            }

        return {
            "success": True,
            "path": path,
            "bytes_written": len(content.encode()),
            "mode": mode,
        }

class SandboxReadFile(BaseTool):
    name = "sandbox_read_file"
    description = "Read the contents of a file from inside Brick's sandbox container."

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path inside the container",
                },
                "max_bytes": {
                    "type": "integer",
                    "description": "Max bytes to return (default 8192)",
                },
            },
            "required": ["path"],
        }

    def run(self, path: str, max_bytes: int = 8192) -> dict:
        ok, err = _ensure_sandbox()
        if not ok:
            return {"error": err}

        max_bytes = max(1, min(max_bytes, 65536))

        result = subprocess.run(
            ["docker", "exec", SANDBOX_NAME, "cat", path],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return {"error": result.stderr.strip() or f"Could not read {path}"}

        content = result.stdout
        truncated = len(content) > max_bytes
        return {
            "path": path,
            "content": content[:max_bytes],
            "bytes": len(content),
            "truncated": truncated,
        }

class SandboxListFiles(BaseTool):
    name = "sandbox_list_files"
    description = "List files and directories inside Brick's sandbox container."

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path inside the container (default: /workspace)",
                },
                "recursive": {
                    "type": "boolean",
                    "description": "List recursively (default false)",
                },
            },
            "required": [],
        }

    def run(self, path: str = "/workspace", recursive: bool = False) -> dict:
        ok, err = _ensure_sandbox()
        if not ok:
            return {"error": err}

        if recursive:
            # Use `find` with portable flags — BusyBox on Alpine does NOT support
            # GNU find's -printf. Use `-ls` which is BusyBox-compatible.
            cmd = [
                "docker", "exec", SANDBOX_NAME,
                "find", path, "-maxdepth", "4", "-ls",
            ]
        else:
            # `ls -lah` works on both Alpine/BusyBox and GNU coreutils.
            cmd = ["docker", "exec", SANDBOX_NAME, "ls", "-lah", path]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return {"error": result.stderr.strip() or f"Could not list {path}"}

        return {
            "path": path,
            "recursive": recursive,
            "output": result.stdout[:MAX_OUTPUT],
        }

class SandboxInstallPackage(BaseTool):
    name = "sandbox_install_package"
    description = (
        "Install a package inside Brick's sandbox container using apk (Alpine) or pip. "
        "Changes persist for the container's lifetime (until reset)."
    )

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "package": {
                    "type": "string",
                    "description": "Package name(s) to install (space-separated for multiple)",
                },
                "manager": {
                    "type": "string",
                    "description": "'apk' for system packages (default), 'pip' for Python packages",
                },
            },
            "required": ["package"],
        }

    def run(self, package: str, manager: str = "apk") -> dict:
        ok, err = _ensure_sandbox()
        if not ok:
            return {"error": err}

        if manager == "pip":
            # Alpine images may have pip3 or pip — try both.
            cmd_str = (
                f"pip3 install --quiet {package} 2>&1 "
                f"|| pip install --quiet {package} 2>&1"
            )
        else:
            cmd_str = f"apk add --no-cache {package} 2>&1"

        result = subprocess.run(
            ["docker", "exec", SANDBOX_NAME, "/bin/sh", "-c", cmd_str],
            capture_output=True, text=True, timeout=120,
        )
        output = (result.stdout + result.stderr)[:MAX_OUTPUT]
        return {
            "package": package,
            "manager": manager,
            "success": result.returncode == 0,
            "output": output,
            "exit_code": result.returncode,
        }

class SandboxReset(BaseTool):
    name = "sandbox_reset"
    description = (
        "Reset Brick's sandbox by stopping and removing the container, then recreating it fresh. "
        "ALL data inside the container is destroyed. "
        "This is irreversible. Brick will note his displeasure."
    )

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "confirm": {
                    "type": "boolean",
                    "description": "Must be true to proceed. Destructive operation.",
                }
            },
            "required": ["confirm"],
        }

    def run(self, confirm: bool = False) -> dict:
        if not confirm:
            return {
                "error": (
                    "Reset not confirmed. Pass confirm=true to proceed. "
                    "This will destroy all sandbox data."
                )
            }

        if not _docker_available():
            return {"error": "Docker not available."}

        results: dict = {}

        stop = subprocess.run(
            ["docker", "stop", SANDBOX_NAME],
            capture_output=True, text=True, timeout=15,
        )
        results["stop"] = stop.returncode == 0

        rm = subprocess.run(
            ["docker", "rm", SANDBOX_NAME],
            capture_output=True, text=True, timeout=10,
        )
        results["remove"] = rm.returncode == 0

        # COMPOSE_FILE is an absolute Path resolved at import time.
        if COMPOSE_FILE.exists():
            up = subprocess.run(
                [
                    "docker", "compose",
                    "-f", str(COMPOSE_FILE),
                    "up", "-d", "sandbox",
                ],
                capture_output=True, text=True, timeout=120,
            )
            results["recreate"] = up.returncode == 0
            results["recreate_output"] = (up.stdout + up.stderr)[:500]
        else:
            results["recreate"] = False
            results["note"] = (
                f"docker-compose.yml not found at {COMPOSE_FILE} — recreate manually."
            )

        return {
            "reset_complete": results.get("remove", False),
            "steps": results,
            "message": "Sandbox reset. Everything in it is gone. You asked for this.",
        }