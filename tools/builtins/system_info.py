import platform
import socket
import time
import psutil
from tools.base import BaseTool


class GetSystemInfo(BaseTool):
    name = "get_system_info"
    description = (
        "Returns static and dynamic system identity: hostname, OS, kernel version, "
        "architecture, uptime, boot time, timezone, CPU model, and FQDN."
    )

    def parameters(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    def run(self) -> dict:
        boot_time = psutil.boot_time()
        uptime_seconds = int(time.time() - boot_time)
        h, rem = divmod(uptime_seconds, 3600)
        m, s = divmod(rem, 60)

        try:
            fqdn = socket.getfqdn()
        except Exception:
            fqdn = None

        try:
            with open("/proc/cpuinfo") as f:
                cpu_model = next(
                    (line.split(":")[1].strip() for line in f if "model name" in line),
                    None,
                )
        except Exception:
            cpu_model = platform.processor() or None

        return {
            "hostname": socket.gethostname(),
            "fqdn": fqdn,
            "os": platform.system(),
            "os_release": platform.release(),
            "os_version": platform.version(),
            "distro": _get_distro(),
            "kernel": platform.uname().release,
            "architecture": platform.machine(),
            "cpu_model": cpu_model,
            "cpu_logical_cores": psutil.cpu_count(logical=True),
            "cpu_physical_cores": psutil.cpu_count(logical=False),
            "total_ram_gb": round(psutil.virtual_memory().total / 1024 ** 3, 2),
            "boot_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(boot_time)),
            "uptime": f"{h}h {m}m {s}s",
            "uptime_seconds": uptime_seconds,
            "python_version": platform.python_version(),
        }


def _get_distro() -> str | None:
    try:
        with open("/etc/os-release") as f:
            info = dict(
                line.strip().split("=", 1)
                for line in f
                if "=" in line
            )
        name = info.get("PRETTY_NAME", info.get("NAME", "")).strip('"')
        return name or None
    except Exception:
        return None


class GetTemperatures(BaseTool):
    name = "get_temperatures"
    description = (
        "Returns hardware temperatures from all available sensors: CPU, NVMe, GPU, etc. "
        "Flags components exceeding high/critical thresholds. Returns None if sensors unavailable."
    )

    def parameters(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    def run(self) -> dict:
        try:
            raw = psutil.sensors_temperatures()
        except AttributeError:
            return {"error": "Temperature sensors not supported on this platform."}

        if not raw:
            return {"error": "No temperature sensors found. May require root or kernel modules."}

        sensors = {}
        alerts = []
        for name, entries in raw.items():
            readings = []
            for e in entries:
                reading = {
                    "label": e.label or name,
                    "current_c": e.current,
                    "high_c": e.high,
                    "critical_c": e.critical,
                    "status": "ok",
                }
                if e.critical and e.current >= e.critical:
                    reading["status"] = "critical"
                    alerts.append(f"{name}/{e.label}: {e.current}°C (critical threshold: {e.critical}°C)")
                elif e.high and e.current >= e.high:
                    reading["status"] = "warning"
                    alerts.append(f"{name}/{e.label}: {e.current}°C (high threshold: {e.high}°C)")
                readings.append(reading)
            sensors[name] = readings

        return {
            "sensors": sensors,
            "alerts": alerts,
            "any_critical": any("critical" in a for a in alerts),
        }


class GetInodeUsage(BaseTool):
    name = "get_inode_usage"
    description = (
        "Returns inode usage per mount point. Inode exhaustion prevents new file creation "
        "even when disk space is free. Flags mounts above 80% inode usage."
    )

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Specific mount point. Omit for all.",
                }
            },
            "required": [],
        }

    def run(self, path: str = None) -> dict:
        results = []
        warnings = []
        partitions = psutil.disk_partitions()

        for p in partitions:
            if path and p.mountpoint != path:
                continue
            try:
                psutil.disk_usage(p.mountpoint)
            except (PermissionError, FileNotFoundError):
                continue
            try:
                vfs = _statvfs(p.mountpoint)
                if vfs["f_files"] == 0:
                    continue
                used = vfs["f_files"] - vfs["f_ffree"]
                percent = round(used / vfs["f_files"] * 100, 1)
                entry = {
                    "mountpoint": p.mountpoint,
                    "device": p.device,
                    "inodes_total": vfs["f_files"],
                    "inodes_used": used,
                    "inodes_free": vfs["f_ffree"],
                    "percent": percent,
                    "status": (
                        "critical" if percent > 90 else
                        "warning" if percent > 80 else
                        "ok"
                    ),
                }
                results.append(entry)
                if percent > 80:
                    warnings.append(f"{p.mountpoint}: {percent}% inodes used")
            except Exception:
                continue

        return {"mounts": results, "warnings": warnings}


def _statvfs(path: str) -> dict:
    import os
    s = os.statvfs(path)
    return {"f_files": s.f_files, "f_ffree": s.f_ffree, "f_favail": s.f_favail}