"""The sampler interface: every source of hardware readings looks the same.

A sampler returns a list of ``Reading`` objects. A reading either has a number and a unit, or
says "unavailable" with a reason. Samplers never raise because a library or a GPU is missing:
``safe_sample`` turns any unexpected error into one "unavailable" reading, so the monitor keeps
running (Development Rule 7: hardware is read at runtime, never assumed).
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Reading:
    """One measurement. ``value`` is None if unavailable (then ``reason`` says why)."""

    key: str  # stable id such as "cpu.total" or "gpu0.vram_used"
    label: str  # human name shown in the UI
    unit: str  # "%", "GB", "MB/s", "°C", "W", "MHz"
    value: float | None
    group: str  # "cpu" | "ram" | "disk" | "gpu0" | "gpu"
    reason: str = ""  # only for unavailable readings
    maximum: float | None = None  # known upper bound (total VRAM, 100 for percentages)
    info: bool = (
        False  # a label only (for example a GPU's name): goes to the catalog, never into samples
    )

    @property
    def available(self) -> bool:
        return self.value is not None


def unavailable(key: str, label: str, group: str, reason: str, unit: str = "") -> Reading:
    return Reading(key=key, label=label, unit=unit, value=None, group=group, reason=reason)


class Sampler(Protocol):
    """Something that can be asked for the current readings."""

    name: str

    def sample(self) -> list[Reading]: ...


def safe_sample(sampler: Sampler) -> list[Reading]:
    """Call ``sampler.sample()``; an unexpected error becomes an 'unavailable' reading."""
    try:
        return list(sampler.sample())
    except Exception as error:  # a sampler bug must never stop the monitor
        reason = f"{sampler.name} failed: {type(error).__name__}: {error}"
        return [unavailable(f"{sampler.name}.error", f"{sampler.name} sampler", "system", reason)]
