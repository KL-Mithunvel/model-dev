"""NVIDIA GPUs through NVML (the nvidia-ml-py package): load, VRAM, temperature, power, clocks.

Both the package and the driver library are optional at run time. Without either, the sampler
reports one "unavailable" reading that says what is missing. A metric a GPU does not support
(laptop GPUs often hide power) is reported unavailable on its own; the others keep working.
"""

from studio.hardware.base import Reading, unavailable

try:
    import pynvml
except ImportError:
    pynvml = None

GIB = 1024**3
MILLIWATT = 1000.0
NO_GPU_GROUP = "gpu"


class NvmlSampler:
    name = "nvml"

    def __init__(self) -> None:
        self._handles: list = []
        self._names: list[str] = []
        self._problem = ""
        self._init()

    def _init(self) -> None:
        if pynvml is None:
            self._problem = "the nvidia-ml-py package is not installed"
            return
        try:
            pynvml.nvmlInit()
            count = pynvml.nvmlDeviceGetCount()
            for index in range(count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(index)
                name = pynvml.nvmlDeviceGetName(handle)
                self._handles.append(handle)
                self._names.append(name.decode() if isinstance(name, bytes) else str(name))
        except Exception as error:  # NVMLError_LibraryNotFound, DriverNotLoaded, ...
            self._problem = f"no NVIDIA driver library was found ({type(error).__name__}: {error})"
            return
        if not self._handles:
            self._problem = "NVML works but reports no NVIDIA GPU"

    def sample(self) -> list[Reading]:
        if self._problem:
            return [unavailable("gpu.nvidia", "NVIDIA GPU", NO_GPU_GROUP, self._problem)]
        readings: list[Reading] = []
        for index, handle in enumerate(self._handles):
            readings.extend(self._one_gpu(index, handle))
        return readings

    def _one_gpu(self, index: int, handle) -> list[Reading]:
        group = f"gpu{index}"
        tag = self._names[index]
        out: list[Reading] = []

        def metric(key, label, unit, read, scale=1.0, maximum=None):
            try:
                out.append(
                    Reading(f"{group}.{key}", label, unit, read() / scale, group, maximum=maximum)
                )
            except Exception as error:
                out.append(
                    unavailable(
                        f"{group}.{key}",
                        label,
                        group,
                        f"{tag} does not report this ({type(error).__name__})",
                        unit,
                    )
                )

        try:
            memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
            total_gb = memory.total / GIB
            out.append(
                Reading(
                    f"{group}.vram_used",
                    "GPU memory used",
                    "GB",
                    memory.used / GIB,
                    group,
                    maximum=total_gb,
                )
            )
            out.append(Reading(f"{group}.vram_total", "GPU memory total", "GB", total_gb, group))
        except Exception as error:
            reason = f"{tag} does not report memory ({type(error).__name__})"
            out.append(unavailable(f"{group}.vram_used", "GPU memory used", group, reason, "GB"))
        metric(
            "util",
            "GPU usage",
            "%",
            lambda: pynvml.nvmlDeviceGetUtilizationRates(handle).gpu,
            maximum=100.0,
        )
        metric(
            "temp",
            "GPU temperature",
            "°C",
            lambda: pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU),
        )
        metric(
            "power",
            "GPU power",
            "W",
            lambda: pynvml.nvmlDeviceGetPowerUsage(handle),
            scale=MILLIWATT,
        )
        metric(
            "clock_sm",
            "GPU core clock",
            "MHz",
            lambda: pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_SM),
        )
        metric(
            "clock_mem",
            "GPU memory clock",
            "MHz",
            lambda: pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_MEM),
        )
        # The device name travels as the label of an info reading so the UI can title the card.
        out.append(Reading(f"{group}.name", tag, "", 0.0, group, info=True))
        return out

    def close(self) -> None:
        if pynvml is not None and self._handles:
            try:
                pynvml.nvmlShutdown()
            except Exception:  # shutting down must never raise
                pass
