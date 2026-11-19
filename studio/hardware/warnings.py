"""Specific warnings with a suggested fix, from the latest readings. Pure: no I/O, easy to test.

Thresholds come from ``config.yaml`` (``hardware.warnings``). Each warning has a stable ``id`` so
the UI can keep its place, a ``severity`` ("warning" or "info"), what is wrong (``message``)
and what to do about it (``fix``).
"""

from typing import Any


def evaluate(
    values: dict[str, float], catalog: dict[str, dict[str, Any]], hardware: dict[str, Any]
) -> list[dict[str, str]]:
    """Return the warnings for one sample. ``values`` maps metric key -> number (available only)."""
    limits = hardware["warnings"]
    found: list[dict[str, str]] = []
    gpu_present = any(
        key.startswith("gpu0.") and entry["available"] for key, entry in catalog.items()
    )

    if not gpu_present:
        if hardware["device"] == "cuda":
            found.append(
                {
                    "id": "no_gpu_but_cuda",
                    "severity": "warning",
                    "message": "hardware.device is set to cuda, but no NVIDIA GPU was found.",
                    "fix": "Set hardware.device to auto or cpu in config.yaml, or install the NVIDIA "
                    "driver if this computer has a GPU.",
                }
            )
        else:
            found.append(
                {
                    "id": "no_gpu",
                    "severity": "info",
                    "message": "No NVIDIA GPU was found, so training will use the CPU.",
                    "fix": "Training on the CPU works but is much slower. If this computer has an "
                    "NVIDIA GPU, install or update its driver and restart the app.",
                }
            )
    else:
        used, total = values.get("gpu0.vram_used"), values.get("gpu0.vram_total")
        if used is not None and total and used / total >= limits["vram_fraction"]:
            found.append(
                {
                    "id": "vram_high",
                    "severity": "warning",
                    "message": f"GPU memory is {used:.1f} / {total:.1f} GB ({used / total:.0%} full).",
                    "fix": "Lower the batch size or the image size, or close other programs that use "
                    "the GPU, before training runs out of memory.",
                }
            )
        temp = values.get("gpu0.temp")
        if temp is not None and temp >= limits["gpu_temp_c"]:
            found.append(
                {
                    "id": "gpu_hot",
                    "severity": "warning",
                    "message": f"The GPU is at {temp:.0f} °C (the warning level is {limits['gpu_temp_c']} °C).",
                    "fix": "Check that the fans and air vents are clear, or pause training until it cools. "
                    "A hot GPU slows itself down.",
                }
            )

    percent = values.get("ram.percent")
    if percent is not None and percent / 100 >= limits["ram_fraction"]:
        used_gb = values.get("ram.used")
        detail = f" ({used_gb:.1f} GB used)" if used_gb is not None else ""
        found.append(
            {
                "id": "ram_high",
                "severity": "warning",
                "message": f"Memory is {percent:.0f} % full{detail}.",
                "fix": "Close other programs or use fewer data-loading workers; a full memory makes "
                "the computer swap to disk and slows everything down.",
            }
        )
    return found
