import re
import socket
import subprocess
import platform
import time
import psutil
from tools.base import BaseTool

def _reverse_dns(ip: str) -> str | None:
    try:
        return socket.gethostbyaddr(ip)[0]
    except (socket.herror, socket.gaierror, OSError):
        return None

class GetConnections(BaseTool):
    name = "get_connections"
    description = (
        "Lists active network connections with process names, local/remote addresses, "
        "status, and optional reverse DNS lookup on remote IPs."
    )

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "description": "'tcp', 'udp', or 'all' (default 'tcp')",
                },
                "listening_only": {
                    "type": "boolean",
                    "description": "Only return listening ports (default false)",
                },
                "reverse_dns": {
                    "type": "boolean",
                    "description": "Resolve remote IPs to hostnames (default false, slower)",
                },
                "exclude_loopback": {
                    "type": "boolean",
                    "description": "Exclude 127.x.x.x connections (default true)",
                },
            },
            "required": [],
        }

    def run(
        self,
        kind: str = "tcp",
        listening_only: bool = False,
        reverse_dns: bool = False,
        exclude_loopback: bool = True,
    ) -> dict:
        kind_map = {"tcp": "tcp", "udp": "udp", "all": "inet"}
        conn_kind = kind_map.get(kind, "tcp")
        connections: list[dict] = []

        for conn in psutil.net_connections(kind=conn_kind):
            if listening_only and conn.status != "LISTEN":
                continue

            laddr = f"{conn.laddr.ip}:{conn.laddr.port}" if conn.laddr else None
            raddr_ip = conn.raddr.ip if conn.raddr else None
            raddr = f"{raddr_ip}:{conn.raddr.port}" if conn.raddr else None

            if exclude_loopback and raddr_ip and raddr_ip.startswith("127."):
                continue

            hostname = _reverse_dns(raddr_ip) if (reverse_dns and raddr_ip) else None

            proc_name = proc_user = None
            if conn.pid:
                try:
                    p = psutil.Process(conn.pid)
                    proc_name = p.name()
                    proc_user = p.username()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            connections.append({
                "pid": conn.pid,
                "process": proc_name,
                "user": proc_user,
                "local_address": laddr,
                "remote_address": raddr,
                "remote_hostname": hostname,
                "status": conn.status,
                "type": kind,
            })

        status_summary: dict[str, int] = {}
        for c in connections:
            s = c["status"]
            status_summary[s] = status_summary.get(s, 0) + 1

        return {
            "connections": connections,
            "count": len(connections),
            "status_summary": status_summary,
        }

class PingHost(BaseTool):
    name = "ping_host"
    description = (
        "Pings a host and returns latency stats: min/avg/max/jitter and packet loss. "
        "Optionally runs a traceroute to show hop count and path."
    )

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "host": {
                    "type": "string",
                    "description": "Hostname or IP to ping (e.g. '8.8.8.8' or 'google.com')",
                },
                "count": {
                    "type": "integer",
                    "description": "Number of ping packets (default 5, max 10)",
                },
                "traceroute": {
                    "type": "boolean",
                    "description": "Also run traceroute to get hop count (default false, slower)",
                },
            },
            "required": ["host"],
        }

    # Matches: min/avg/max/mdev or min/avg/max/jitter (float variants).
    _RTT_RE = re.compile(
        r"(\d+\.?\d*)/(\d+\.?\d*)/(\d+\.?\d*)/(\d+\.?\d*)\s*ms"
    )
    # Matches packet loss: "0%", "12.5%", "100%"
    _LOSS_RE = re.compile(r"(\d+\.?\d*)%\s*(packet\s*)?loss", re.IGNORECASE)

    def run(self, host: str, count: int = 5, traceroute: bool = False) -> dict:
        count = max(1, min(count, 10))
        system = platform.system()

        if system == "Windows":
            cmd = ["ping", "-n", str(count), host]
        else:
            cmd = ["ping", "-c", str(count), "-W", "2", host]

        result: dict = {"host": host, "reachable": False}

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            output = proc.stdout + proc.stderr
            result["reachable"] = proc.returncode == 0
            result["raw_output"] = output[:1000]

            for line in output.splitlines():
                # RTT statistics line
                m = self._RTT_RE.search(line)
                if m:
                    result["latency_ms"] = {
                        "min": float(m.group(1)),
                        "avg": float(m.group(2)),
                        "max": float(m.group(3)),
                        "jitter": float(m.group(4)),
                    }
                # Windows average
                m2 = re.search(r"Average\s*=\s*(\d+)ms", line)
                if m2:
                    result.setdefault("latency_ms", {})["avg"] = float(m2.group(1))

                # Packet loss — supports both integer and float percentages.
                m3 = self._LOSS_RE.search(line)
                if m3:
                    result["packet_loss_percent"] = float(m3.group(1))

            result["packets_sent"] = count

        except subprocess.TimeoutExpired:
            result["error"] = "Ping timed out"
        except FileNotFoundError:
            result["error"] = "ping command not available"

        if traceroute:
            try:
                tr_cmd = (
                    ["tracert", "-d", "-h", "20", host]
                    if system == "Windows"
                    else ["traceroute", "-m", "20", "-n", host]
                )
                tr = subprocess.run(tr_cmd, capture_output=True, text=True, timeout=30)
                tr_lines = [l for l in tr.stdout.splitlines() if l.strip()]
                result["traceroute"] = {
                    "hop_count": max(0, len(tr_lines) - 1),
                    "output": tr.stdout[:1500],
                }
            except Exception as e:
                result["traceroute"] = {"error": str(e)}

        return result

class GetNetworkIO(BaseTool):
    name = "get_network_io"
    description = (
        "Returns per-interface network I/O: bytes sent/recv (totals and rates in MB/s), "
        "packet counts, error rates, and drop rates. Flags degraded interfaces."
    )

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "interface": {
                    "type": "string",
                    "description": "Specific interface (e.g. 'eth0'). Omit for all.",
                },
                "sample_seconds": {
                    "type": "number",
                    "description": "Sampling window to compute rates (default 1.0)",
                },
            },
            "required": [],
        }

    def run(self, interface: str | None = None, sample_seconds: float = 1.0) -> dict:
        sample_seconds = max(0.1, min(float(sample_seconds), 10.0))

        def to_mb(b: int | float) -> float:
            return round(b / 1_048_576, 2)

        before = psutil.net_io_counters(pernic=True)
        time.sleep(sample_seconds)
        after = psutil.net_io_counters(pernic=True)

        stats = psutil.net_if_stats()
        addrs = psutil.net_if_addrs()
        result: dict[str, dict] = {}

        for iface, a in after.items():
            if interface and iface != interface:
                continue
            b = before.get(iface)
            if not b:
                continue

            is_up = stats[iface].isup if iface in stats else None
            speed_mbps = stats[iface].speed if iface in stats else None
            ip_addrs = [
                addr.address
                for addr in addrs.get(iface, [])
                if addr.family == socket.AF_INET
            ]

            total_packets = a.packets_recv + a.packets_sent
            error_rate = round(
                (a.errin + a.errout) / max(total_packets, 1) * 100, 3
            )
            drop_rate = round(
                (a.dropin + a.dropout) / max(total_packets, 1) * 100, 3
            )

            result[iface] = {
                "is_up": is_up,
                "ip_addresses": ip_addrs,
                "speed_mbps": speed_mbps,
                "totals": {
                    "sent_mb": to_mb(a.bytes_sent),
                    "recv_mb": to_mb(a.bytes_recv),
                    "packets_sent": a.packets_sent,
                    "packets_recv": a.packets_recv,
                },
                "rates": {
                    "send_mb_per_s": round(
                        (a.bytes_sent - b.bytes_sent) / sample_seconds / 1_048_576, 3
                    ),
                    "recv_mb_per_s": round(
                        (a.bytes_recv - b.bytes_recv) / sample_seconds / 1_048_576, 3
                    ),
                },
                "errors": {
                    "in": a.errin,
                    "out": a.errout,
                    "error_rate_percent": error_rate,
                },
                "drops": {
                    "in": a.dropin,
                    "out": a.dropout,
                    "drop_rate_percent": drop_rate,
                },
                "degraded": error_rate > 0.1 or drop_rate > 0.1,
            }

        degraded = [iface for iface, data in result.items() if data.get("degraded")]
        return {"interfaces": result, "degraded_interfaces": degraded}