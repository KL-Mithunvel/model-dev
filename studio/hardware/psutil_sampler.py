"""CPU (total and per core), RAM and disk I/O through psutil. psutil is optional at run time."""

import time
from collections.abc import Callable

from studio.hardware.base import Reading, unavailable

try:
    import psutil
except ImportError:  # the monitor still starts; these readings say why they are missing
    psutil = None

GIB = 1024**3
MB = 1_000_000  # disk rates are decimal megabytes per second, like most disk tools


class PsutilSampler:
    name = "psutil"

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._last_disk: tuple[float, int, int] | None = None
        if psutil is None:
            return
        psutil.cpu_percent(percpu=True)  # the first call has no baseline; prime it
        self._last_disk = self._disk_counters()

    def _disk_counters(self) -> tuple[float, int, int] | None:
        counters = psutil.disk_io_counters()
        if counters is None:
            return None
        return (self._clock(), counters.read_bytes, counters.write_bytes)

    def sample(self) -> list[Reading]:
        if psutil is None:
            reason = "the psutil package is not installed"
            return [
                unavailable("cpu.total", "CPU", "cpu", reason, "%"),
                unavailable("ram.percent", "Memory", "ram", reason, "%"),
                unavailable("disk.read", "Disk read", "disk", reason, "MB/s"),
            ]
        readings = self._cpu() + self._ram() + self._disk()
        return readings

    def _cpu(self) -> list[Reading]:
        cores = psutil.cpu_percent(percpu=True)
        if not cores:
            return [unavailable("cpu.total", "CPU", "cpu", "the system reports no CPU cores", "%")]
        readings = [Reading("cpu.total", "CPU", "%", sum(cores) / len(cores), "cpu", maximum=100.0)]
        for index, value in enumerate(cores):
            readings.append(
                Reading(f"cpu.core.{index}", f"Core {index}", "%", value, "cpu", maximum=100.0)
            )
        return readings

    def _ram(self) -> list[Reading]:
        memory = psutil.virtual_memory()
        total = memory.total / GIB
        return [
            Reading("ram.percent", "Memory", "%", memory.percent, "ram", maximum=100.0),
            Reading(
                "ram.used",
                "Memory used",
                "GB",
                (memory.total - memory.available) / GIB,
                "ram",
                maximum=total,
            ),
        ]

    def _disk(self) -> list[Reading]:
        current = self._disk_counters()
        if current is None or self._last_disk is None:
            reason = "this system does not report disk counters"
            return [
                unavailable("disk.read", "Disk read", "disk", reason, "MB/s"),
                unavailable("disk.write", "Disk write", "disk", reason, "MB/s"),
            ]
        elapsed = max(current[0] - self._last_disk[0], 1e-6)
        read = max(current[1] - self._last_disk[1], 0) / elapsed / MB
        write = max(current[2] - self._last_disk[2], 0) / elapsed / MB
        self._last_disk = current
        return [
            Reading("disk.read", "Disk read", "MB/s", read, "disk"),
            Reading("disk.write", "Disk write", "MB/s", write, "disk"),
        ]
