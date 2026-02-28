from typing import Dict
from tools.base import BaseTool

class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        if not tool.name:
            raise ValueError(f"Tool {tool} has no name.")
        self._tools[tool.name] = tool
        print(f"[Registry] Registered tool: {tool.name!r}")

    def get(self, name: str) -> BaseTool:
        if name not in self._tools:
            raise KeyError(f"Unknown tool: {name!r}. Available: {list(self._tools)}")
        return self._tools[name]

    def all_schemas(self) -> list[dict]:
        return [t.schema() for t in self._tools.values()]

    def all_ollama_schemas(self) -> list[dict]:
        return [t.ollama_schema() for t in self._tools.values()]

    def names(self) -> list[str]:
        return list(self._tools.keys())