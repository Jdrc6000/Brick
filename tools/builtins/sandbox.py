"""
Brick Sandbox tools — Brick's personal Docker environment.

The sandbox is a persistent Alpine Linux container named 'brick-sandbox'.
Brick treats it as his own turf: clean, controlled, personal.
"""

import subprocess
import shlex
import os
from tools.base import BaseTool

SANDBOX_NAME = "brick-sandbox"
EXEC_TIMEOUT = 30
MAX_OUTPUT = 4000  # chars — truncate noisy commands

def _docker_available() -> bool:
    try:
        subprocess.run(["docker", "info"], capture_output=True, timeout=5)
        return True
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

    # Check if container exists at all
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
        # Try to start it
        start = subprocess.run(
            ["docker", "start", SANDBOX_NAME],
            capture_output=True, text=True, timeout=10,
        )
        if start.returncode != 0:
            return False, f"Failed to start sandbox: {start.stderr.strip()}"

    return True, ""

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
        timeout = min(timeout, 120)
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
                cmd, capture_output=True, text=True, timeout=timeout
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
                "truncated": len(result.stdout) > MAX_OUTPUT or len(result.stderr) > MAX_OUTPUT,
            }
        except subprocess.TimeoutExpired:
            return {"error": f"Command timed out after {timeout}s", "command": command}
        except Exception as e:
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

        import json
        try:
            info = json.loads(inspect.stdout)[0]
        except (json.JSONDecodeError, IndexError):
            return {"error": "Failed to parse container info."}

        state = info.get("State", {})
        running = state.get("Running", False)

        result = {
            "exists": True,
            "running": running,
            "status": state.get("Status", "unknown"),
            "started_at": state.get("StartedAt"),
            "image": info.get("Config", {}).get("Image"),
            "name": info.get("Name", "").lstrip("/"),
        }

        if running:
            # Resource usage via docker stats (single snapshot, no-stream)
            stats = subprocess.run(
                ["docker", "stats", "--no-stream", "--format",
                 "{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.NetIO}}\t{{.BlockIO}}",
                 SANDBOX_NAME],
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

            # Disk usage inside container
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

        # Ensure parent dir exists
        parent = os.path.dirname(path)
        if parent and parent != "/":
            mkdir = subprocess.run(
                ["docker", "exec", SANDBOX_NAME, "mkdir", "-p", parent],
                capture_output=True, text=True, timeout=5,
            )
            if mkdir.returncode != 0:
                return {"error": f"Failed to create directory {parent}: {mkdir.stderr}"}

        # Write via stdin using docker exec
        write = subprocess.run(
            ["docker", "exec", "-i", SANDBOX_NAME, "sh", "-c", f"cat > {shlex.quote(path)}"],
            input=content, capture_output=True, text=True, timeout=10,
        )
        if write.returncode != 0:
            return {"error": f"Write failed: {write.stderr.strip()}"}

        # Set permissions
        chmod = subprocess.run(
            ["docker", "exec", SANDBOX_NAME, "chmod", mode, path],
            capture_output=True, text=True, timeout=5,
        )

        return {
            "success": True,
            "path": path,
            "bytes_written": len(content.encode()),
            "mode": mode,
        }

class SandboxReadFile(BaseTool):
    name = "sandbox_read_file"
    description = (
        "Read the contents of a file from inside Brick's sandbox container."
    )

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
    description = (
        "List files and directories inside Brick's sandbox container."
    )

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
            cmd = ["docker", "exec", SANDBOX_NAME, "find", path, "-maxdepth", "4",
                   "-printf", "%M %u %s %p\n"]
        else:
            cmd = ["docker", "exec", SANDBOX_NAME, "ls", "-lah", path]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return {"error": result.stderr.strip()}

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
            cmd_str = f"pip3 install --quiet {package} 2>&1 | tail -5"
        else:
            cmd_str = f"apk add --no-cache {package} 2>&1 | tail -10"

        result = subprocess.run(
            ["docker", "exec", SANDBOX_NAME, "/bin/sh", "-c", cmd_str],
            capture_output=True, text=True, timeout=60,
        )

        return {
            "package": package,
            "manager": manager,
            "success": result.returncode == 0,
            "output": (result.stdout + result.stderr)[:MAX_OUTPUT],
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
                "error": "Reset not confirmed. Pass confirm=true to proceed. "
                         "This will destroy all sandbox data."
            }

        if not _docker_available():
            return {"error": "Docker not available."}

        results = {}

        # Stop
        stop = subprocess.run(
            ["docker", "stop", SANDBOX_NAME],
            capture_output=True, text=True, timeout=15,
        )
        results["stop"] = stop.returncode == 0

        # Remove
        rm = subprocess.run(
            ["docker", "rm", SANDBOX_NAME],
            capture_output=True, text=True, timeout=10,
        )
        results["remove"] = rm.returncode == 0

        # Recreate via docker compose
        compose_file = os.path.join(os.path.dirname(__file__), "..", "..", "..", "docker-compose.yml")
        if os.path.exists(compose_file):
            up = subprocess.run(
                ["docker", "compose", "-f", compose_file, "up", "-d", "sandbox"],
                capture_output=True, text=True, timeout=60,
            )
            results["recreate"] = up.returncode == 0
            results["recreate_output"] = (up.stdout + up.stderr)[:500]
        else:
            results["recreate"] = False
            results["note"] = "docker-compose.yml not found — recreate manually."

        return {
            "reset_complete": results.get("remove", False),
            "steps": results,
            "message": "Sandbox reset. Everything in it is gone. You asked for this.",
        }