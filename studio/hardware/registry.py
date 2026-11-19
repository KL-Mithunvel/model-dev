"""Choose the samplers from ``config.yaml`` (``hardware.sampler``)."""

from typing import Any

from studio.hardware.base import Sampler
from studio.hardware.fake import FakeGpuSampler, FakeSystemSampler, UnavailableSampler
from studio.hardware.nvml_sampler import NvmlSampler
from studio.hardware.psutil_sampler import PsutilSampler

SAMPLER_CHOICES = ("auto", "fake", "fake_no_gpu")
OTHER_GPU_REASON = (
    "Intel and AMD GPU readings are not supported yet (only NVIDIA GPUs are read, through NVML)."
)


def other_gpu_sampler() -> UnavailableSampler:
    """Best-effort Intel/AMD path: there is no reader yet, so it says so plainly."""
    return UnavailableSampler("other-gpu", "gpu.other", "Intel/AMD GPU", "gpu", OTHER_GPU_REASON)


def build_samplers(hardware: dict[str, Any]) -> list[Sampler]:
    """The samplers for a ``hardware`` config section. Raises ValueError for an unknown choice."""
    choice = hardware["sampler"]
    if choice == "auto":
        return [PsutilSampler(), NvmlSampler(), other_gpu_sampler()]
    if choice in ("fake", "fake_no_gpu"):
        fake = hardware["fake"]
        return [
            FakeSystemSampler(cores=fake["cores"]),
            FakeGpuSampler(
                present=choice == "fake",
                vram_fraction=fake["vram_fraction"],
                temp_c=fake["gpu_temp_c"],
                vram_total_gb=fake["vram_total_gb"],
            ),
            other_gpu_sampler(),
        ]
    raise ValueError(f"hardware.sampler must be one of {SAMPLER_CHOICES}, got {choice!r}")
