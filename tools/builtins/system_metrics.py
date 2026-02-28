import psutil
import time
from tools.base import BaseTool

def _to_mb(b): return round(b / 1024 / 1024, 1)
def _to_gb(b): return round(b / 1024 / 1024 / 1024, 2)

class GetCpuUsage(BaseTool):
    name = "get_cpu_usage"
    description = (
        "Returns detailed CPU usage: overall and per-core percentages, load averages, "
        "CPU time breakdown (user/system/idle/iowait/steal), per-core frequencies, "
        "and a pressure score (0-100) with label (ok/warning/critical)."
    )

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "interval": {
                    "type": "number",
                    "description": "Sampling interval in seconds (default 1.0 for accuracy)"
                }
            },
            "required": []
        }

    def run(self, interval: float = 1.0) -> dict:
        overall = psutil.cpu_percent(interval=interval)
        per_core = psutil.cpu_percent(interval=None, percpu=True)
        times = psutil.cpu_times_percent(interval=None)
        times_breakdown = {
            "user": times.user,
            "system": times.system,
            "idle": times.idle,
            "iowait": getattr(times, "iowait", None),
            "steal": getattr(times, "steal", None),
            "nice": getattr(times, "nice", None),
        }

        try:
            load_1, load_5, load_15 = psutil.getloadavg()
            cpu_count = psutil.cpu_count(logical=True)
            load_avg = {
                "1min": round(load_1, 2),
                "5min": round(load_5, 2),
                "15min": round(load_15, 2),
                "normalized_percent": round(load_1 / cpu_count * 100, 1),
            }
        except AttributeError:
            load_avg = None  # Windows

        try:
            freqs = psutil.cpu_freq(percpu=True)
            per_core_freq = [
                {"core": i, "current_mhz": round(f.current, 1), "max_mhz": round(f.max, 1)}
                for i, f in enumerate(freqs)
            ] if freqs else []
        except Exception:
            per_core_freq = []

        iowait = times_breakdown.get("iowait") or 0
        normalized = load_avg["normalized_percent"] if load_avg else overall
        pressure = min(100, round(overall * 0.6 + iowait * 0.3 + normalized * 0.1, 1))

        return {
            "overall_percent": overall,
            "per_core_percent": per_core,
            "core_count": {
                "logical": psutil.cpu_count(logical=True),
                "physical": psutil.cpu_count(logical=False),
            },
            "times_percent": times_breakdown,
            "load_averages": load_avg,
            "per_core_freq_mhz": per_core_freq,
            "pressure_score": pressure,
            "pressure_label": (
                "critical" if pressure > 80 else
                "warning" if pressure > 60 else
                "ok"
            ),
        }

class GetMemoryUsage(BaseTool):
    name = "get_memory_usage"
    description = (
        "Returns detailed RAM and swap statistics including pressure label, "
        "top memory-consuming processes with RSS/VMS breakdown, and page fault rates."
    )

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "top_processes": {
                    "type": "integer",
                    "description": "Number of top memory processes to include (default 5, max 20)"
                }
            },
            "required": []
        }

    def run(self, top_processes: int = 5) -> dict:
        top_processes = min(top_processes, 20)
        ram = psutil.virtual_memory()
        swap = psutil.swap_memory()

        pressure = (
            "critical" if ram.percent > 90 else
            "warning" if ram.percent > 75 else
            "moderate" if ram.percent > 60 else
            "ok"
        )

        procs = []
        for p in psutil.process_iter(["pid", "name", "memory_info", "memory_percent"]):
            try:
                mi = p.info["memory_info"]
                procs.append({
                    "pid": p.info["pid"],
                    "name": p.info["name"],
                    "shared_mb": _to_mb(getattr(mi, "shared", 0)),
                    "memory_percent": round(p.info["memory_percent"] or 0, 2),
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        procs.sort(key=lambda x: x["memory_percent"], reverse=True)

        try:
            with open("/proc/vmstat") as f:
                vmstat = dict(line.split() for line in f if line.strip())
            page_faults = {
                "minor_faults_total": int(vmstat.get("pgfault", 0)),
                "major_faults_total": int(vmstat.get("pgmajfault", 0)),
            }
        except Exception:
            page_faults = None

        return {
            "ram": {
                "total_mb": _to_mb(ram.total),
                "used_mb": _to_mb(ram.used),
                "available_mb": _to_mb(ram.available),
                "cached_mb": _to_mb(getattr(ram, "cached", 0)),
                "buffers_mb": _to_mb(getattr(ram, "buffers", 0)),
                "percent": ram.percent,
                "pressure": pressure,
            },
            "swap": {
                "total_mb": _to_mb(swap.total),
                "used_mb": _to_mb(swap.used),
                "free_mb": _to_mb(swap.free),
                "percent": swap.percent,
                "swapped_in_mb": _to_mb(swap.sin),
                "swapped_out_mb": _to_mb(swap.sout),
            },
            "top_processes_by_rss": procs[:top_processes],
            "page_faults": page_faults,
        }

class GetDiskUsage(BaseTool):
    name = "get_disk_usage"
    description = (
        "Returns disk usage per mount point with status flags, plus per-device I/O rates "
        "(MB/s read/write, ops/s, estimated latency) sampled over a short interval."
    )

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Specific mount point (e.g. '/'). Omit for all."
                },
                "sample_io_seconds": {
                    "type": "number",
                    "description": "Interval to sample I/O rates over (default 1.0)"
                }
            },
            "required": []
        }

    def run(self, path: str = None, sample_io_seconds: float = 1.0) -> dict:
        io_before = psutil.disk_io_counters(perdisk=True)
        time.sleep(sample_io_seconds)
        io_after = psutil.disk_io_counters(perdisk=True)

        partitions = psutil.disk_partitions()
        usage_data = []
        for p in partitions:
            if path and p.mountpoint != path:
                continue
            try:
                usage = psutil.disk_usage(p.mountpoint)
                usage_data.append({
                    "mountpoint": p.mountpoint,
                    "device": p.device,
                    "fstype": p.fstype,
                    "total_gb": _to_gb(usage.total),
                    "used_gb": _to_gb(usage.used),
                    "free_gb": _to_gb(usage.free),
                    "percent": usage.percent,
                    "status": (
                        "critical" if usage.percent > 90 else
                        "warning" if usage.percent > 75 else
                        "ok"
                    ),
                })
            except (PermissionError, FileNotFoundError):
                continue

        io_rates = {}
        for dev, after in io_after.items():
            before = io_before.get(dev)
            if not before:
                continue
            elapsed = sample_io_seconds
            reads_delta = max(after.read_count - before.read_count, 1)
            writes_delta = max(after.write_count - before.write_count, 1)
            io_rates[dev] = {
                "read_mb_per_s": round((after.read_bytes - before.read_bytes) / elapsed / 1024 / 1024, 3),
                "write_mb_per_s": round((after.write_bytes - before.write_bytes) / elapsed / 1024 / 1024, 3),
                "reads_per_s": round((after.read_count - before.read_count) / elapsed, 1),
                "writes_per_s": round((after.write_count - before.write_count) / elapsed, 1),
                "avg_read_latency_ms": round((after.read_time - before.read_time) / reads_delta, 2),
                "avg_write_latency_ms": round((after.write_time - before.write_time) / writes_delta, 2),
            }

        warnings = [p["mountpoint"] for p in usage_data if p["status"] != "ok"]
        return {
            "partitions": usage_data,
            "io_rates": io_rates,
            "warnings": warnings,
        }