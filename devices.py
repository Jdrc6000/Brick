"""
Device registry. Add/remove entries here to control access.
Matching is done by IP address or hostname.
"""

DEVICES = [
    {
        "name": "joshs-macbook",
        "ip": "192.168.0.39",
        "description": "Josh's Macbook M4",
        "tags": ["mac", "laptop"],
    },
    {
        "name": "joshs-pc",
        "ip": "192.168.0.16",
        "description": "Josh's PC",
        "tags": ["pc", "windows"],
    },
    {
        "name": "wills-pc",
        "ip": "192.168.0.118",
        "description": "Will's PC",
        "tags": ["pc", "windows"],
    },
]

# Built lookup tables
DEVICE_BY_IP: dict[str, dict] = {d["ip"]: d for d in DEVICES}
DEVICE_BY_NAME: dict[str, dict] = {d["name"]: d for d in DEVICES}

def get_device(ip: str, hostname: str = None) -> dict | None:
    """Return device info if the IP or hostname is registered, else None."""
    if ip in DEVICE_BY_IP:
        return DEVICE_BY_IP[ip]
    if hostname and hostname in DEVICE_BY_NAME:
        return DEVICE_BY_NAME[hostname]
    # Strip domain suffix and try again
    if hostname:
        short = hostname.split(".")[0]
        if short in DEVICE_BY_NAME:
            return DEVICE_BY_NAME[short]
    return None