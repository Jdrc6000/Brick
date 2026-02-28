import threading
from agent import Agent
from tools.builtins import (
    GetCpuUsage, GetMemoryUsage, GetDiskUsage,
    GetSystemInfo, GetTemperatures, GetInodeUsage,
    ListProcesses, SearchProcess, KillProcess, SetProcessPriority,
    GetConnections, PingHost, GetNetworkIO,
    TailLog, FindLargeFiles, ListDirectory,
    ListServices, GetServiceStatus, GetLoginHistory, GetCronJobs,
)

_LOCAL_TOOLS = [
    GetCpuUsage(), GetMemoryUsage(), GetDiskUsage(),
    GetSystemInfo(), GetTemperatures(), GetInodeUsage(),
    ListProcesses(), SearchProcess(), KillProcess(), SetProcessPriority(),
    GetConnections(), PingHost(), GetNetworkIO(),
    TailLog(), FindLargeFiles(), ListDirectory(),
    ListServices(), GetServiceStatus(), GetLoginHistory(), GetCronJobs(),
]

class SessionManager:
    def __init__(self):
        self._sessions: dict[str, Agent] = {}
        self._lock = threading.Lock()

    def get_or_create(self, device: dict) -> Agent:
        name = device["name"]
        with self._lock:
            if name in self._sessions:
                return self._sessions[name]
            agent = Agent(session_id=f"device_{name}", resume=True)
            agent.register_tools(*_LOCAL_TOOLS)
            self._sessions[name] = agent
            print(f"[Sessions] Created session for '{name}'")
            return agent

    def destroy(self, device_name: str):
        with self._lock:
            self._sessions.pop(device_name, None)

    def active_sessions(self) -> list[str]:
        return list(self._sessions.keys())