from tools.registry import ToolRegistry
from tools.remote_executor import RemoteToolExecutor
from tools.base import BaseTool
from memory.short_term import ShortTermMemory
from history.conversation import ConversationHistory
from history.store import HistoryStore
from agent.prompt_builder import PromptBuilder
from agent.runner import AgentRunner
import config

class Agent:
    def __init__(
        self,
        session_id: str = "default",
        model: str = config.OLLAMA_MODEL,
        resume: bool = True,
        device_ip: str = None,
    ):
        self.session_id = session_id
        self.model = model
        self.device_ip = device_ip

        self.registry = ToolRegistry()
        self.executor = RemoteToolExecutor(self.registry, device_ip=device_ip)

        store = HistoryStore()
        self.history = ConversationHistory(session_id, store)
        self.memory = ShortTermMemory()

        if resume and len(self.history) > 0:
            self.memory.load_from(self.history.as_chat_messages())
            print(f"[Agent] Resumed session '{session_id}' ({len(self.history)} messages)")

        if device_ip:
            print(f"[Agent] Remote execution target: {device_ip}:{7700}")

        self.prompt_builder = PromptBuilder(self.registry)
        self.runner = AgentRunner(
            prompt_builder=self.prompt_builder,
            executor=self.executor,
            memory=self.memory,
            history=self.history,
            model=model,
        )

    def register_tool(self, tool: BaseTool) -> "Agent":
        self.registry.register(tool)
        return self

    def register_tools(self, *tools: BaseTool) -> "Agent":
        for tool in tools:
            self.registry.register(tool)
        return self

    def chat(self, message: str) -> str:
        return self.runner.run(message)

    def reset(self) -> None:
        self.history.clear()
        self.memory.clear()
        print(f"[Agent] Session '{self.session_id}' reset.")