from datetime import datetime
from typing import Optional
from history.store import HistoryStore

class ConversationHistory:
    def __init__(self, session_id: str, store: Optional[HistoryStore] = None):
        self.session_id = session_id
        self.store = store or HistoryStore()
        self._messages: list[dict] = self.store.load(session_id)
    
    def append(self, role: str, content: str) -> None:
        msg = {
            "role": role,
            "content": content,
            "timestamp": datetime.utcnow().isoformat(),
        }
        self._messages.append(msg)
        self.store.save(self.session_id, self._messages)

    def all(self) -> list[dict]:
        return list(self._messages)

    # bug fix:
    #  old function stripped tool-call ids
    def as_chat_messages(self) -> list[dict]:
        result = []
        for m in self._messages:
            role = m.get("role")
            content = (m.get("content") or "").strip()
            if role == "assistant" and not content:   # tool-call-only assistant msg
                continue
            if role == "tool":                         # tool result row
                continue
            result.append({"role": role, "content": content})
        return result

    def clear(self) -> None:
        self._messages = []
        self.store.delete(self.session_id)

    def __len__(self):
        return len(self._messages)