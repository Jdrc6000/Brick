from tools.builtins import *
from agent import Agent

if __name__ == "__main__":
    agent = (
        Agent(session_id="demo", resume=True)
        .register_tools(
            GetCpuUsage(), GetMemoryUsage(), GetDiskUsage(),
            GetSystemInfo(), GetTemperatures(), GetInodeUsage(),
            ListProcesses(), SearchProcess(), KillProcess(), SetProcessPriority(),
            GetConnections(), PingHost(), GetNetworkIO(),
            TailLog(), FindLargeFiles(), ListDirectory(),
            ListServices(), GetServiceStatus(), GetLoginHistory(), GetCronJobs(),
            SandboxExec(), SandboxInstallPackage(), SandboxListFiles(), SandboxReadFile(), SandboxReset(), SandboxStatus(), SandboxWriteFile()
        )
    )

    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            break

        if not user_input:
            continue
        if user_input.lower() == "quit":
            print("Goodbye!")
            break
        if user_input.lower() == "reset":
            agent.reset()
            continue

        reply = agent.chat(user_input)
        print(f"Assistant: {reply}")