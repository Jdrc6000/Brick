from collections import deque
from memory.base import BaseMemory
import config

class ShortTermMemory(BaseMemory):
    def __init__(self, window: int = config.SHORT_TERM_WINDOW):
        self.window = window
        self._messages: deque[dict] = deque(maxlen=window)

    def add(self, role: str, content: str) -> None:
        self._messages.append({"role": role, "content": content})

    def add_raw(self, message: dict) -> None:
        self._messages.append(message)

    def get(self) -> list[dict]:
        return list(self._messages)

    def clear(self) -> None:
        self._messages.clear()

    def load_from(self, messages: list[dict]) -> None:
        self.clear()
        for msg in messages[-self.window:]:
            self._messages.append(msg)

    def __len__(self):
        return len(self._messages)