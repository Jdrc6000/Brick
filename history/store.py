import json
import os
import config

class HistoryStore:
    def __init__(self, directory: str = config.HISTORY_DIR):
        self.directory = directory
        os.makedirs(directory, exist_ok=True)

    def _path(self, session_id: str) -> str:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id)
        return os.path.join(self.directory, f"{safe}.json")

    def load(self, session_id: str) -> list[dict]:
        path = self._path(session_id)
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []

    def save(self, session_id: str, messages: list[dict]) -> None:
        path = self._path(session_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(messages, f, indent=2, ensure_ascii=False)

    def delete(self, session_id: str) -> None:
        path = self._path(session_id)
        if os.path.exists(path):
            os.remove(path)

    def list_sessions(self) -> list[str]:
        return [
            f[:-5] for f in os.listdir(self.directory) if f.endswith(".json")
        ]