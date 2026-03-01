# BRICK (レンガ)
> Deadpan sysadmin AI assistant with real tools, a personal sandbox, and zero tolerance for nonsense.
```
brick@system ~$ status
● BRICK  [operational]
   provider : ollama
   model    : devstral-small-2:24b
   tools    : 28 registered
   sandbox  : running
```

## Table of Contents
1. [What it is](#what-it-is)
2. [Tools](#tools)
3. [The Pit](#the-pit)
3. [Web UI](#web-ui)
4. [CLI Mode](#cli-mode)
5. [Roadmap](#roadmap)
3. [Notes](#notes)
4. [Project Structure](#project-structure)

## What it is
Brick is a locally-hosted AI sysadmin assistant that has actual access to your machines. It monitors them, runs commands, kills processes, reads logs, pings hosts, and does computational work in an isolated Alpine Linux Docker sandbox it calls **The Pit**.

It talks to you though a slick terminal-aesthetic web UI. It streams responses live. It's dry, clinical, and mildly sarcastic - because that's the appropriate energy for a sysadmin tool.

## Tools
Brick has 27 built-in tools across 6 categories
### System Metrics
| Tool | What it does |
|------|-------------|
| `get_cpu_usage` | Overall + per-core CPU %, load averages, iowait, pressure score |
| `get_memory_usage` | RAM/swap breakdown, top memory processes, page fault rates |
| `get_disk_usage` | Per-mount usage + per-device I/O rates (MB/s, latency) |

### System Info
| Tool | What it does |
|------|-------------|
| `get_system_info` | Hostname, OS, kernel, uptime, CPU model, RAM total |
| `get_temperatures` | Hardware sensor readings, threshold alerts |
| `get_inode_usage` | Inode usage per mount — catches the "disk full but df disagrees" problem |

### Processes
| Tool | What it does |
|------|-------------|
| `list_processes` | Top processes by CPU or memory, with threads/FDs/uptime |
| `search_process` | Find a process by name or PID, full cmdline + process tree |
| `kill_process` | SIGTERM by PID — refuses PIDs < 100 and its own PID |
| `set_process_priority` | Change nice value (−20 to 19) |

### Network
| Tool | What it does |
|------|-------------|
| `get_connections` | Active TCP/UDP connections with process names, optional reverse DNS |
| `ping_host` | Latency stats (min/avg/max/jitter), packet loss, optional traceroute |
| `get_network_io` | Per-interface throughput rates, error rates, drop rates |

### Files & Logs
| Tool | What it does |
|------|-------------|
| `tail_log` | Last N lines of any log file or journalctl, with regex filtering |
| `find_large_files` | Finds files over a size threshold, sorted by size |
| `list_directory` | `ls -lah` equivalent with permissions, owner, size |

### Services & Security
| Tool | What it does |
|------|-------------|
| `list_services` | Systemd services filtered by state (running/failed/inactive/all) |
| `get_service_status` | Detailed status for a specific service, recent log lines |
| `get_login_history` | Recent logins + currently logged-in users, optional failed-only |
| `get_cron_jobs` | All cron entries for current user + system-wide |

### Sandbox (The Pit)
| Tool | What it does |
|------|-------------|
| `sandbox_exec` | Run a shell command inside the sandbox |
| `sandbox_status` | Container status, CPU/memory usage, disk usage |
| `sandbox_write_file` | Write a file into the sandbox |
| `sandbox_read_file` | Read a file from the sandbox |
| `sandbox_list_files` | List files in the sandbox |
| `sandbox_install_package` | Install apk or pip packages (persist until reset) |
| `sandbox_reset` | ⚠ Destroy and recreate the sandbox. Brick will note his displeasure. |

## The Pit
The Pit is Brick's personal workspace. It's a persistent Alpine Linux Docker container with a `/workspace` volume that survives between sessions.

Brick uses it for anything conputational or potentially destructive - scripts, file parsing, config testing, anything that shouldn't touch the host. If you ask Brick to do something experimental, it goes to the Pit first.

```
┌────────────────────────────────┐
│  brick-sandbox (Alpine Linux)  │
│  /workspace  ← persistent      │
│  mem_limit: 512m               │
│  cpus: 1.0                     │
│  network: brick-internal       │
└────────────────────────────────┘
```

## Web UI
The UI is a single-page terminal aesthetic chat interface with:
* **Live SSE streaming** - tokens appear as they're generated
* **Tool accordion** - each tool shows a collapsible pill with parameters and result
* **Spinner -> checkmark** status transitions as tools complete
* **Markdown rendering** - code blocks, tables, headers all render properly
* **Session persistance** - conversation history loads on refresh
* **CLR button** - wipes the session

### Error pages

Brick handles his own error pages, also powered by the LLM:
* 403 - Unregistered IP gets a personalised dismissal. Brick has been watching.
* 404 - The path never existed. Brick searched everywhere. It's gone.
* 500 - Bricks fault. He knows. He's handling it. Leave

## CLI Mode
For quick local testing without the web server:
```bash
python main.py
```
```
You: what's eating all my cpu
  [Runner] Tool call: get_cpu_usage({})
  [Runner] Tool call: list_processes({"sort_by": "cpu", "limit": 10})
Assistant: Chrome. PID 8421. 340% CPU across 12 threads. It's been doing this for 47 minutes. ...
```

## Roadmap
Planned improvements:
| Feature | Priority | Notes |
|---------|----------|-------|
| Centralised tool registry | high |  |
| More tools | medium |  |
| Web UI themes | low | Dark / light mode |

## Notes
* This is just self-driven personal project, meaning:
    * The code will be messy
    * There will be bugs
    * It is not supposed to be easy to use
    * it is severely undocumented
* Adding new tools is not trivial - I will fix this in the future...

## Project Structure
```
brick/
├── agent/
│   ├── agent.py          # Agent class — main entry point
│   ├── prompt_builder.py # System prompt + personality
│   └── runner.py         # Agent loop, tool calling, streaming
├── tools/
│   ├── base.py           # BaseTool abstract class
│   ├── registry.py       # Tool registry
│   ├── executor.py       # Local tool executor
│   ├── remote_executor.py# Routes tool calls local vs remote
│   └── builtins/         # All 27 built-in tools
├── memory/
│   └── short_term.py     # Sliding window context memory
├── history/
│   ├── conversation.py   # Per-session message history
│   └── store.py          # JSON persistence
├── templates/
│   ├── index.html        # Web UI
│   ├── forbidden.html    # 403 — go away
│   ├── not_found.html    # 404 — never was
│   └── internal_error.html # 500 — my fault
├── sandbox/
│   └── Dockerfile        # Alpine Linux sandbox image
├── server.py             # Flask server + SSE streaming
├── brick-client.py       # Remote device daemon
├── sandbox-manager.py    # CLI sandbox management
├── devices.py            # Device registry
├── config.py             # Model + runtime config
└── main.py               # CLI mode
```

---

*Brick monitors. Brick reports. Brick fixes.*