from abc import ABC, abstractmethod

class BaseTool(ABC):
    name: str = ""
    description: str = ""

    @abstractmethod
    def run(self, **kwargs) -> str: ...

    def parameters(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters(),
        }

    def ollama_schema(self) -> dict:
        """Return the tool schema in Ollama's native tool-calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters(),
            },
        }

    def __repr__(self) -> str:
        return f"<Tool name={self.name!r}>"