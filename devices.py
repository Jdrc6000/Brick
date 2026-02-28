DEVICES = [
    {
        "name": "joshs-macbook",
        "ip": "192.168.0.39",
        "description": "Joshs Macbook M4",
        "tags": ["mac", "laptop"],
    }
]

DEVICE_BY_IP: dict[str, dict] = {d["ip"]: d for d in DEVICES}