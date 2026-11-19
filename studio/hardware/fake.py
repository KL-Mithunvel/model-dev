"""Deterministic fakes for every sampler (Development Rule 8): they run on any machine.

Values depend only on how many times ``sample()`` was called, so tests and browser scenarios
get the same numbers every time. A fake mirrors the keys and units of its real counterpart.
"""

from studio.hardware.base import Reading, unavailable

FAKE_RAM_TOTAL_GB = 32.0


class FakeSystemSampler:
    """Stands in for PsutilSampler."""

    name = "fake-system"

    def __init__(self, cores: int = 8) -> None:
        self.cores = cores
        self.ticks = 0

    def sample(self) -> list[Reading]:
        n = self.ticks
        self.ticks += 1
        core_values = [20.0 + ((n * 7 + index * 13) % 60) for index in range(self.cores)]
        ram_percent = 40.0 + (n % 20)
        readings = [
            Reading("cpu.total", "CPU", "%", sum(core_values) / self.cores, "cpu", maximum=100.0)
        ]
        for index, value in enumerate(core_values):
            readings.append(
                Reading(f"cpu.core.{index}", f"Core {index}", "%", value, "cpu", maximum=100.0)
            )
        readings += [
            Reading("ram.percent", "Memory", "%", ram_percent, "ram", maximum=100.0),
            Reading(
                "ram.used",
                "Memory used",
                "GB",
                ram_percent / 100 * FAKE_RAM_TOTAL_GB,
                "ram",
                maximum=FAKE_RAM_TOTAL_GB,
            ),
            Reading("disk.read", "Disk read", "MB/s", float(1 + (n * 3) % 50), "disk"),
            Reading("disk.write", "Disk write", "MB/s", float((n * 5) % 30), "disk"),
        ]
        return readings


class FakeGpuSampler:
    """Stands in for NvmlSampler. ``present=False`` behaves like a machine without an NVIDIA GPU."""

    name = "fake-gpu"

    def __init__(
        self,
        present: bool = True,
        vram_fraction: float = 0.5,
        temp_c: float = 60.0,
        vram_total_gb: float = 6.0,
        label: str = "Fake GPU",
    ) -> None:
        self.present = present
        self.vram_fraction = vram_fraction
        self.temp_c = temp_c
        self.vram_total_gb = vram_total_gb
        self.label = label
        self.ticks = 0

    def sample(self) -> list[Reading]:
        n = self.ticks
        self.ticks += 1
        if not self.present:
            return [unavailable("gpu.nvidia", "NVIDIA GPU", "gpu", "fake: no GPU present")]
        total = self.vram_total_gb
        return [
            Reading(
                "gpu0.vram_used",
                "GPU memory used",
                "GB",
                self.vram_fraction * total,
                "gpu0",
                maximum=total,
            ),
            Reading("gpu0.vram_total", "GPU memory total", "GB", total, "gpu0"),
            Reading("gpu0.util", "GPU usage", "%", 30.0 + (n * 11) % 50, "gpu0", maximum=100.0),
            Reading("gpu0.temp", "GPU temperature", "°C", self.temp_c, "gpu0"),
            Reading("gpu0.power", "GPU power", "W", 20.0 + n % 10, "gpu0"),
            Reading("gpu0.clock_sm", "GPU core clock", "MHz", 1500.0 + (n * 10) % 300, "gpu0"),
            Reading("gpu0.clock_mem", "GPU memory clock", "MHz", 6000.0, "gpu0"),
            Reading("gpu0.name", self.label, "", 0.0, "gpu0", info=True),
        ]


class UnavailableSampler:
    """Reports one metric as unavailable. Used for the Intel/AMD GPU path, which has no reader yet,
    and as its own fake: it needs no hardware."""

    def __init__(self, name: str, key: str, label: str, group: str, reason: str) -> None:
        self.name = name
        self._reading = unavailable(key, label, group, reason)

    def sample(self) -> list[Reading]:
        return [self._reading]
