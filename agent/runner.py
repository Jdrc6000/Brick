import ollama
import config
from tools.executor import ToolExecutor
from memory.short_term import ShortTermMemory
from history.conversation import ConversationHistory
from agent.prompt_builder import PromptBuilder

class AgentRunner:
    def __init__(
        self,
        prompt_builder: PromptBuilder,
        executor: ToolExecutor,
        memory: ShortTermMemory,
        history: ConversationHistory,
        model: str = config.OLLAMA_MODEL,
        max_iterations: int = config.MAX_ITERATIONS,
    ):
        self.prompt_builder = prompt_builder
        self.executor = executor
        self.memory = memory
        self.history = history
        self.model = model
        self.max_iterations = max_iterations

    def run(self, user_input: str) -> str:
        """Run the agent and return the final text response."""
        final, _ = self.run_with_tools(user_input)
        return final

    def run_with_tools(self, user_input: str) -> tuple[str, list[dict]]:
        """
        Run the agent and return (final_text, tool_calls_used).

        Each entry in tool_calls_used is:
            {
                "name": str,          # tool function name
                "parameters": dict,   # arguments passed
                "result": str,        # raw result string
            }
        """
        self.history.append("user", user_input)
        self.memory.add("user", user_input)

        system_prompt = self.prompt_builder.system_prompt()
        tools = self.executor.registry.all_ollama_schemas()
        messages = [{"role": "system", "content": system_prompt}] + self.memory.get()

        tool_calls_used: list[dict] = []

        for iteration in range(self.max_iterations):
            response = ollama.chat(
                model=self.model,
                messages=messages,
                tools=tools if tools else None,
                options={"temperature": 0.7},
            )
            msg = response["message"]

            if msg.get("tool_calls"):
                messages.append(msg)
                self.memory.add_raw(msg)
                if msg.get("content"):
                    self.history.append("assistant", msg["content"])

                for tool_call in msg["tool_calls"]:
                    fn = tool_call["function"]
                    tool_name = fn["name"]
                    tool_params = fn["arguments"]

                    print(f"  [Runner] Tool call: {tool_name}({tool_params})")
                    result = self.executor.execute({"name": tool_name, "parameters": tool_params})

                    # Record for the caller
                    tool_calls_used.append({
                        "name": tool_name,
                        "parameters": tool_params,
                        "result": result,
                    })

                    tool_msg = {
                        "role": "tool",
                        "content": result,
                    }
                    if tool_call_id := tool_call.get("id"):
                        tool_msg["tool_call_id"] = tool_call_id

                    messages.append(tool_msg)
                    self.memory.add_raw(tool_msg)
                    self.history.append("tool", f"[Tool: {tool_name}] {result}")

            else:
                final = (msg.get("content") or "").strip()
                self.history.append("assistant", final)
                self.memory.add("assistant", final)
                return final, tool_calls_used

        final = (msg.get("content") or "").strip()
        self.history.append("assistant", final)
        self.memory.add("assistant", final)
        return final, tool_calls_used