from abc import ABC, abstractmethod

class BaseMemory(ABC):
    @abstractmethod
    def add(self, role: str, content: str) -> None: ...

    @abstractmethod
    def get(self) -> list[dict]: ...

    @abstractmethod
    def clear(self) -> None: ...