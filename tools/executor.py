from tools.registry import ToolRegistry

class ToolExecutor:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    def execute(self, tool_call: dict) -> str:
        name = tool_call.get("name")
        params = tool_call.get("parameters", {})

        if not name:
            return "[ToolExecutor] Error: tool call missing 'name' field."

        try:
            tool = self.registry.get(name)
            result = tool.run(**params)
            return str(result)
        
        except KeyError as e:
            return f"[ToolExecutor] Error: {e}"
        
        except TypeError as e:
            return f"[ToolExecutor] Bad parameters for {name!r}: {e}"

        except Exception as e:
            return f"[ToolExecutor] Tool {name!r} raised an error: {e}"