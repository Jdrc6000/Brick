import logging
import ollama
import config
from tools.executor import ToolExecutor
from memory.short_term import ShortTermMemory
from history.conversation import ConversationHistory
from agent.prompt_builder import PromptBuilder

log = logging.getLogger("brick.runner")

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
        # Clamp to a safe range; never allow 0 (unbound msg) or runaway loops.
        self.max_iterations = max(1, min(max_iterations, 50))

    # Internal helpers
    def _build_messages(self) -> list[dict]:
        system_prompt = self.prompt_builder.system_prompt()
        return [{"role": "system", "content": system_prompt}] + self.memory.get()

    def _tools(self) -> list[dict] | None:
        schemas = self.executor.registry.all_ollama_schemas()
        return schemas if schemas else None

    def _extract_final_text(self, msg: dict) -> str:
        """Pull clean text content from a message dict, never None."""
        return (msg.get("content") or "").strip()

    def _record_tool_call(
        self,
        messages: list[dict],
        tool_calls_used: list[dict],
        tool_call: dict,
    ) -> None:
        """Execute one tool call and append the result to messages/history/memory."""
        fn = tool_call["function"]
        tool_name = fn["name"]
        tool_params = fn["arguments"]

        log.info("Tool call: %s(%s)", tool_name, tool_params)

        result = self.executor.execute({"name": tool_name, "parameters": tool_params})

        tool_calls_used.append({
            "name": tool_name,
            "parameters": tool_params,
            "result": result,
        })

        tool_msg: dict = {"role": "tool", "content": result}
        if tool_call_id := tool_call.get("id"):
            tool_msg["tool_call_id"] = tool_call_id

        messages.append(tool_msg)
        self.memory.add_raw(tool_msg)
        self.history.append("tool", f"[Tool: {tool_name}] {result}")

    # Public API
    def run(self, user_input: str) -> str:
        """Run the agent and return only the final text response."""
        final, _ = self.run_with_tools(user_input)
        return final

    def run_with_tools(self, user_input: str) -> tuple[str, list[dict]]:
        """
        Run the agent and return (final_text, tool_calls_used).
        Each entry in tool_calls_used is:
            {"name": str, "parameters": dict, "result": str}
        """
        self.history.append("user", user_input)
        self.memory.add("user", user_input)

        messages = self._build_messages()
        tools = self._tools()
        tool_calls_used: list[dict] = []

        for iteration in range(self.max_iterations):
            try:
                response = ollama.chat(
                    model=self.model,
                    messages=messages,
                    tools=tools,
                    options={"temperature": 0.7},
                )
            except Exception as e:
                log.exception("ollama.chat failed on iteration %d", iteration)
                final = f"[Runner] Model error: {e}"
                self.history.append("assistant", final)
                self.memory.add("assistant", final)
                return final, tool_calls_used

            msg = response["message"]

            if msg.get("tool_calls"):
                # Append the assistant turn (may contain partial text + tool calls).
                messages.append(msg)
                self.memory.add_raw(msg)

                # Persist any interstitial text the model produced.
                if interstitial := (msg.get("content") or "").strip():
                    self.history.append("assistant", interstitial)

                for tc in msg["tool_calls"]:
                    self._record_tool_call(messages, tool_calls_used, tc)

            else:
                final = self._extract_final_text(msg)
                # If model went silent after tool calls, nudge it
                if not final and tool_calls_used:
                    messages.append({
                        "role": "user", 
                        "content": "Summarize what you found."
                    })
                    continue  # loop again to get a real response
                self.history.append("assistant", final)
                self.memory.add("assistant", final)
                return final, tool_calls_used

        # Max iterations reached without a clean text response.
        # Return a safe fallback rather than whatever the last tool-call message was.
        log.warning("Max iterations (%d) reached without a text response.", self.max_iterations)
        final = (
            "[Brick] Hit the iteration ceiling without reaching a conclusion. "
            "Something is stuck. Check the tool results above."
        )
        self.history.append("assistant", final)
        self.memory.add("assistant", final)
        return final, tool_calls_used

    def stream(self, user_input: str):
        """
        Generator that yields SSE-compatible event dicts:
          {"type": "tool_start",  "name": str, "parameters": dict}
          {"type": "tool_result", "name": str, "result": str}
          {"type": "token",       "text": str}
          {"type": "error",       "message": str}
          {"type": "done",        "tool_calls": list}
        The "done" event is guaranteed to be emitted exactly once.
        """
        self.history.append("user", user_input)
        self.memory.add("user", user_input)

        messages = self._build_messages()
        tools = self._tools()
        tool_calls_used: list[dict] = []

        for iteration in range(self.max_iterations):
            try:
                response = ollama.chat(
                    model=self.model,
                    messages=messages,
                    tools=tools,
                    options={"temperature": 0.7},
                )
            except Exception as e:
                log.exception("ollama.chat failed on iteration %d (stream)", iteration)
                yield {"type": "error", "message": f"Model error: {e}"}
                yield {"type": "done", "tool_calls": tool_calls_used}
                return

            msg = response["message"]

            if msg.get("tool_calls"):
                messages.append(msg)
                self.memory.add_raw(msg)

                if interstitial := (msg.get("content") or "").strip():
                    self.history.append("assistant", interstitial)

                for tc in msg["tool_calls"]:
                    fn = tc["function"]
                    tool_name = fn["name"]
                    tool_params = fn["arguments"]

                    yield {"type": "tool_start", "name": tool_name, "parameters": tool_params}

                    result = self.executor.execute({"name": tool_name, "parameters": tool_params})
                    tool_calls_used.append({
                        "name": tool_name,
                        "parameters": tool_params,
                        "result": result,
                    })

                    yield {"type": "tool_result", "name": tool_name, "result": result}

                    tool_msg: dict = {"role": "tool", "content": result}
                    if tc_id := tc.get("id"):
                        tool_msg["tool_call_id"] = tc_id
                    messages.append(tool_msg)
                    self.memory.add_raw(tool_msg)
                    self.history.append("tool", f"[Tool: {tool_name}] {result}")

            else:
                # Stream the final text response token by token.
                try:
                    stream = ollama.chat(
                        model=self.model,
                        messages=messages,
                        tools=None,
                        options={"temperature": 0.7},
                        stream=True,
                    )
                    full_text = ""
                    for chunk in stream:
                        token = (chunk.get("message", {}).get("content") or "")
                        if token:
                            full_text += token
                            yield {"type": "token", "text": token}
                except Exception as e:
                    log.exception("Streaming final response failed (stream)")
                    yield {"type": "error", "message": f"Stream error: {e}"}
                    yield {"type": "done", "tool_calls": tool_calls_used}
                    return

                self.history.append("assistant", full_text)
                self.memory.add("assistant", full_text)
                yield {"type": "done", "tool_calls": tool_calls_used}
                return  # Clean exit — done emitted exactly once.

        # Max iterations reached.
        log.warning("Stream: max iterations (%d) reached.", self.max_iterations)
        final = (
            "[Brick] Hit the iteration ceiling. Something is stuck. "
            "Check the tool results above."
        )
        self.history.append("assistant", final)
        self.memory.add("assistant", final)
        yield {"type": "token", "text": final}
        yield {"type": "done", "tool_calls": tool_calls_used}