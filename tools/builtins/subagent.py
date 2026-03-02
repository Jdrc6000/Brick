"""
SubAgent tool — lets the main agent spin up a focused sub-agent for a delegated task.
"""
import logging
import ollama
from tools.base import BaseTool
from tools.registry import ToolRegistry
from tools.remote_executor import RemoteToolExecutor

log = logging.getLogger("brick.subagent")

# All tools available to sub-agents — main agent picks a subset
from tools.builtins import (
    GetCpuUsage, GetMemoryUsage, GetDiskUsage, GetSystemInfo,
    GetTemperatures, GetInodeUsage, ListProcesses, SearchProcess,
    KillProcess, SetProcessPriority, GetConnections, PingHost,
    GetNetworkIO, TailLog, FindLargeFiles, ListDirectory,
    ListServices, GetServiceStatus, GetLoginHistory, GetCronJobs,
    SandboxExec, SandboxStatus, SandboxWriteFile, SandboxReadFile,
    SandboxInstallPackage, SandboxListFiles, SandboxReset, WebSearch,
)

AVAILABLE_TOOLS = {
    "get_cpu_usage": GetCpuUsage,
    "get_memory_usage": GetMemoryUsage,
    "get_disk_usage": GetDiskUsage,
    "get_system_info": GetSystemInfo,
    "get_temperatures": GetTemperatures,
    "get_inode_usage": GetInodeUsage,
    "list_processes": ListProcesses,
    "search_process": SearchProcess,
    "kill_process": KillProcess,
    "set_process_priority": SetProcessPriority,
    "get_connections": GetConnections,
    "ping_host": PingHost,
    "get_network_io": GetNetworkIO,
    "tail_log": TailLog,
    "find_large_files": FindLargeFiles,
    "list_directory": ListDirectory,
    "list_services": ListServices,
    "get_service_status": GetServiceStatus,
    "get_login_history": GetLoginHistory,
    "get_cron_jobs": GetCronJobs,
    "sandbox_exec": SandboxExec,
    "sandbox_status": SandboxStatus,
    "sandbox_write_file": SandboxWriteFile,
    "sandbox_read_file": SandboxReadFile,
    "sandbox_install_package": SandboxInstallPackage,
    "sandbox_list_files": SandboxListFiles,
    "sandbox_reset": SandboxReset,
    "web_search": WebSearch,
}

_SUBAGENT_BASE_SYSTEM = """
You are a focused sub-agent spawned by Brick to complete a specific task.
You have a limited toolset. Complete your task, report findings concisely, then stop.
Do not ask clarifying questions. Make reasonable assumptions. Be precise.
"""

MAX_SUBAGENT_ITERATIONS = 8

class SpawnSubagent(BaseTool):
    name = "spawn_subagent"
    description = (
        "Spawn a focused sub-agent to handle a specific delegated task. "
        "The sub-agent gets its own system prompt, a restricted toolset you define, "
        "and a clean context window. It runs to completion and returns its findings. "
        "Use this for parallel workstreams, isolated investigations, or tasks that "
        "would pollute the main context (e.g. scraping lots of log data, benchmarking, "
        "multi-step file processing). The sub-agent cannot spawn further sub-agents."
    )

    def __init__(self, device_ip: str | None = None):
        self.device_ip = device_ip

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": (
                        "Clear, self-contained task description for the sub-agent. "
                        "Include all context it needs — it has no memory of the main conversation."
                    ),
                },
                "tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        f"List of tool names to give the sub-agent. "
                        f"Available: {sorted(AVAILABLE_TOOLS.keys())}"
                    ),
                },
                "system_addendum": {
                    "type": "string",
                    "description": (
                        "Optional extra system prompt instructions appended to the base. "
                        "Use to set tone, constraints, or output format for this specific task."
                    ),
                },
                "model": {
                    "type": "string",
                    "description": "Model override for the sub-agent. Defaults to same model as main agent.",
                },
            },
            "required": ["task", "tools"],
        }

    def run(
        self,
        task: str,
        tools: list[str],
        system_addendum: str = "",
        model: str = None,
    ) -> str:
        import config

        # Build the sub-agent's restricted registry
        registry = ToolRegistry()
        invalid_tools = []
        for tool_name in tools:
            if tool_name == "spawn_subagent":
                continue  # No recursion
            if tool_name not in AVAILABLE_TOOLS:
                invalid_tools.append(tool_name)
                continue
            registry.register(AVAILABLE_TOOLS[tool_name]())

        if invalid_tools:
            log.warning("SubAgent: unknown tools requested: %s", invalid_tools)

        if not registry.names():
            return "[SubAgent] Error: no valid tools provided."

        executor = RemoteToolExecutor(registry, device_ip=self.device_ip)
        tool_schemas = registry.all_ollama_schemas()

        system_prompt = _SUBAGENT_BASE_SYSTEM.strip()
        if system_addendum:
            system_prompt += f"\n\n{system_addendum.strip()}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task},
        ]

        use_model = model or config.OLLAMA_MODEL
        log.info(
            "SubAgent spawned — model=%s tools=%s task=%.80s…",
            use_model, registry.names(), task,
        )

        # Run the sub-agent loop
        for iteration in range(MAX_SUBAGENT_ITERATIONS):
            try:
                response = ollama.chat(
                    model=use_model,
                    messages=messages,
                    tools=tool_schemas,
                    options={"temperature": 0.3},  # Lower temp — focused task
                )
            except Exception as e:
                return f"[SubAgent] Model error on iteration {iteration}: {e}"

            msg = response["message"]

            if msg.get("tool_calls"):
                messages.append(msg)
                for tc in msg["tool_calls"]:
                    fn = tc["function"]
                    tool_name = fn["name"]
                    tool_params = fn["arguments"]
                    log.info("SubAgent tool call: %s(%s)", tool_name, tool_params)

                    result = executor.execute({"name": tool_name, "parameters": tool_params})

                    tool_msg = {"role": "tool", "content": result}
                    if tc_id := tc.get("id"):
                        tool_msg["tool_call_id"] = tc_id
                    messages.append(tool_msg)
            else:
                # Sub-agent reached a conclusion
                final = (msg.get("content") or "").strip()
                if not final and len(messages) > 2:
                    # Nudge for a summary if it went silent after tool calls
                    messages.append({"role": "user", "content": "Summarize your findings."})
                    continue
                log.info("SubAgent completed after %d iterations.", iteration + 1)
                return final or "[SubAgent] Task completed with no output."

        return (
            "[SubAgent] Hit iteration limit without completing. "
            "Last tool results are in the sub-agent's internal context."
        )