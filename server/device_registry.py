import json
import os
import secrets
import threading
from datetime import datetime
from typing import Optional

REGISTRY_PATH = os.environ.get("DEVICE_REGISTRY_PATH", ".brick_devices.json")

class Device:
    def __init__(self, data: dict):
        self.id: str = data["id"]
        self.name: str = data["name"]
        self.api_key: str = data["api_key"]
        self.agent_url: Optional[str] = data.get("agent_url")  # e.g. http://192.168.1.x:8765
        self.description: str = data.get("description", "")
        self.created_at: str = data.get("created_at", datetime.utcnow().isoformat())
        self.last_seen: Optional[str] = data.get("last_seen")
        self.tags: list[str] = data.get("tags", [])

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "api_key": self.api_key,
            "agent_url": self.agent_url,
            "description": self.description,
            "created_at": self.created_at,
            "last_seen": self.last_seen,
            "tags": self.tags,
        }

    def public_dict(self) -> dict:
        """Safe to send to frontend — no API key."""
        d = self.to_dict()
        d.pop("api_key")
        return d

class DeviceRegistry:
    def __init__(self, path: str = REGISTRY_PATH):
        self.path = path
        self._lock = threading.Lock()
        self._devices: dict[str, Device] = {}  # keyed by id
        self._key_index: dict[str, str] = {}   # api_key -> device_id
        self._load()

    def _load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path) as f:
                data = json.load(f)
            for d in data.get("devices", []):
                dev = Device(d)
                self._devices[dev.id] = dev
                self._key_index[dev.api_key] = dev.id
        except Exception as e:
            print(f"[Registry] Failed to load: {e}")

    def _save(self):
        with open(self.path, "w") as f:
            json.dump(
                {"devices": [d.to_dict() for d in self._devices.values()]},
                f, indent=2
            )

    def authenticate(self, api_key: str) -> Optional[Device]:
        with self._lock:
            device_id = self._key_index.get(api_key)
            if not device_id:
                return None
            dev = self._devices[device_id]
            dev.last_seen = datetime.utcnow().isoformat()
            self._save()
            return dev

    def register(self, name: str, description: str = "", agent_url: str = None, tags: list = None) -> Device:
        with self._lock:
            device_id = f"dev_{secrets.token_hex(6)}"
            api_key = f"bk_{secrets.token_urlsafe(32)}"
            dev = Device({
                "id": device_id,
                "name": name,
                "api_key": api_key,
                "agent_url": agent_url,
                "description": description,
                "created_at": datetime.utcnow().isoformat(),
                "tags": tags or [],
            })
            self._devices[device_id] = dev
            self._key_index[api_key] = device_id
            self._save()
            return dev

    def get(self, device_id: str) -> Optional[Device]:
        return self._devices.get(device_id)

    def list_all(self) -> list[Device]:
        return list(self._devices.values())

    def update(self, device_id: str, **kwargs) -> Optional[Device]:
        with self._lock:
            dev = self._devices.get(device_id)
            if not dev:
                return None
            for k, v in kwargs.items():
                if hasattr(dev, k) and k not in ("id", "api_key"):
                    setattr(dev, k, v)
            self._save()
            return dev

    def delete(self, device_id: str) -> bool:
        with self._lock:
            dev = self._devices.pop(device_id, None)
            if not dev:
                return False
            self._key_index.pop(dev.api_key, None)
            self._save()
            return True

    def rotate_key(self, device_id: str) -> Optional[str]:
        """Generate a new API key for a device."""
        with self._lock:
            dev = self._devices.get(device_id)
            if not dev:
                return None
            self._key_index.pop(dev.api_key, None)
            dev.api_key = f"bk_{secrets.token_urlsafe(32)}"
            self._key_index[dev.api_key] = device_id
            self._save()
            return dev.api_key