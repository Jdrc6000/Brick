import subprocess
import sys
import argparse
import json
import logging

log = logging.getLogger("brick.sandbox")

SANDBOX_NAME = "brick-sandbox"
COMPOSE_FILE = "docker-compose.yml"

def _run(cmd: list, timeout: int = 30, capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        capture_output=capture,
        text=True,
        timeout=timeout,
    )

def is_docker_available() -> bool:
    try:
        r = _run(["docker", "info"], timeout=5)
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False

def get_sandbox_state() -> dict:
    """Return full container state dict, or {'exists': False}."""
    r = _run(["docker", "inspect", SANDBOX_NAME], timeout=5)
    if r.returncode != 0:
        return {"exists": False}
    try:
        info = json.loads(r.stdout)[0]
        state = info.get("State", {})
        return {
            "exists": True,
            "running": state.get("Running", False),
            "status": state.get("Status", "unknown"),
            "started_at": state.get("StartedAt"),
            "image": info.get("Config", {}).get("Image"),
        }
    except (json.JSONDecodeError, IndexError):
        return {"exists": True, "running": False, "status": "unknown"}

def ensure_running() -> tuple[bool, str]:
    """
    Make sure the sandbox is running. Start it if stopped. 
    Returns (success, message).
    """
    if not is_docker_available():
        return False, "Docker not available."

    state = get_sandbox_state()

    if not state["exists"]:
        log.info("Sandbox does not exist — building and starting via compose...")
        r = _run(["docker", "compose", "-f", COMPOSE_FILE, "up", "-d", "--build", "sandbox"], timeout=120)
        if r.returncode != 0:
            return False, f"Failed to create sandbox:\n{r.stderr}"
        log.info("Sandbox created.")
        return True, "Sandbox created and started."

    if not state["running"]:
        log.info("Sandbox stopped — starting...")
        r = _run(["docker", "start", SANDBOX_NAME], timeout=15)
        if r.returncode != 0:
            return False, f"Failed to start sandbox: {r.stderr}"
        log.info("Sandbox started.")
        return True, "Sandbox started."

    return True, "Sandbox already running."

def stop() -> tuple[bool, str]:
    r = _run(["docker", "stop", SANDBOX_NAME], timeout=15)
    if r.returncode != 0:
        return False, r.stderr.strip()
    return True, "Sandbox stopped."

def reset(rebuild: bool = False) -> tuple[bool, str]:
    """Nuke and recreate. Brick's data is gone. He knows."""
    _run(["docker", "stop", SANDBOX_NAME], timeout=15)
    _run(["docker", "rm", SANDBOX_NAME], timeout=10)

    flags = ["--build"] if rebuild else []
    r = _run(
        ["docker", "compose", "-f", COMPOSE_FILE, "up", "-d"] + flags + ["sandbox"],
        timeout=120,
    )
    if r.returncode != 0:
        return False, f"Failed to recreate sandbox:\n{r.stderr}"
    return True, "Sandbox reset. Clean slate."

def print_status() -> None:
    if not is_docker_available():
        print("✗  Docker not available.")
        return

    state = get_sandbox_state()
    if not state["exists"]:
        print(f"✗  Container '{SANDBOX_NAME}' does not exist.")
        print("   Run: docker compose up -d --build sandbox")
        return

    icon = "●" if state["running"] else "○"
    print(f"{icon}  {SANDBOX_NAME}  [{state['status']}]")
    print(f"   image   : {state.get('image', 'unknown')}")
    print(f"   started : {state.get('started_at', 'n/a')}")

    if state["running"]:
        # Resource snapshot
        stats = _run(
            ["docker", "stats", "--no-stream", "--format",
             "CPU: {{.CPUPerc}}  MEM: {{.MemUsage}} ({{.MemPerc}})",
             SANDBOX_NAME],
            timeout=10,
        )
        if stats.returncode == 0:
            print(f"   {stats.stdout.strip()}")

def main():
    parser = argparse.ArgumentParser(description="Brick sandbox manager")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("start",  help="Start or create the sandbox")
    sub.add_parser("stop",   help="Stop the sandbox")
    sub.add_parser("status", help="Show sandbox status")
    reset_p = sub.add_parser("reset", help="Destroy and recreate the sandbox")
    reset_p.add_argument("--rebuild", action="store_true", help="Rebuild Docker image")
    sub.add_parser("shell",  help="Drop into a shell inside the sandbox")

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.command == "start":
        ok, msg = ensure_running()
        print(("✓" if ok else "✗") + "  " + msg)
        sys.exit(0 if ok else 1)

    elif args.command == "stop":
        ok, msg = stop()
        print(("✓" if ok else "✗") + "  " + msg)
        sys.exit(0 if ok else 1)

    elif args.command == "status":
        print_status()

    elif args.command == "reset":
        confirm = input(
            f"This will destroy all data in '{SANDBOX_NAME}'. Type 'yes' to confirm: "
        )
        if confirm.strip().lower() != "yes":
            print("Aborted.")
            sys.exit(1)
        ok, msg = reset(rebuild=args.rebuild)
        print(("✓" if ok else "✗") + "  " + msg)
        sys.exit(0 if ok else 1)

    elif args.command == "shell":
        ok, msg = ensure_running()
        if not ok:
            print(f"✗  {msg}")
            sys.exit(1)
        # Replace process with interactive shell
        os.execvp("docker", ["docker", "exec", "-it", SANDBOX_NAME, "/bin/bash"])

    else:
        print_status()

if __name__ == "__main__":
    import os
    main()