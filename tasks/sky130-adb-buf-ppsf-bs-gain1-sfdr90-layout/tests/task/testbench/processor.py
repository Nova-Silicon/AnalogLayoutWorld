"""Original upstream SFDR definition and strict source acceptance predicates."""
import bisect
import math
from pathlib import Path

def dynamic_metrics(path: Path, frequency_hz: float) -> tuple[float, float]:
    samples = []
    for line in path.read_text().splitlines():
        try:
            fields = [float(value) for value in line.split()]
        except ValueError:
            continue
        # wrdata emits time,VOP,time,VON for two vectors.
        if len(fields) >= 4 and 49e-6 <= fields[0] < 50e-6:
            samples.append((fields[0], fields[1] - fields[3]))
    if len(samples) < 900:
        raise ValueError(f"expected a 1 ns, 1 us final window, got {len(samples)} samples")
    # Resample the adaptive transient output onto 1000 uniform points before
    # taking a rectangular-window DFT. The full Nyquist band is searched, so
    # harmonics and high-frequency switching spurs count; this also avoids
    # treating irregular simulator time points as a uniform FFT grid.
    uniform_start = 49e-6
    uniform_step = 1e-9
    n = 1000
    source_times = [time for time, _ in samples]
    source_values = [value for _, value in samples]
    values = []
    for index in range(n):
        time = uniform_start + index * uniform_step
        right = bisect.bisect_right(source_times, time) - 1
        right = max(0, min(right, len(source_times) - 2))
        fraction = (time - source_times[right]) / (source_times[right + 1] - source_times[right])
        values.append(source_values[right] + fraction * (source_values[right + 1] - source_values[right]))
    fundamental_bin = round(frequency_hz * uniform_step * n)
    if fundamental_bin < 1 or fundamental_bin > 50:
        raise ValueError(f"fundamental bin {fundamental_bin} outside 1 MHz..50 MHz")

    def amplitude(bin_index: int) -> float:
        omega = 2 * math.pi * bin_index / n
        real = sum(value * math.cos(omega * index) for index, value in enumerate(values))
        imag = sum(value * math.sin(omega * index) for index, value in enumerate(values))
        return 2 * math.hypot(real, imag) / n

    fundamental = amplitude(fundamental_bin)
    largest_spur = max(amplitude(bin_index) for bin_index in range(1, n // 2 + 1)
                       if bin_index != fundamental_bin)
    gain = fundamental / 0.8
    sfdr = 20 * math.log10(fundamental / max(largest_spur, 1e-30))
    return gain, sfdr


def process_case(case, work, values):
    if case["analysis"] == "ac":
        required = ("gain_min_vv", "gain_1mhz_vv", "gain_40mhz_vv",
                    "power_w", "input_current_40mhz_a")
        if not all(key in values and math.isfinite(values[key]) for key in required):
            raise ValueError("Incomplete original AC/DC measurement set")
        passed = (values["gain_min_vv"] > 0.99
                  and values["power_w"] < 1e-3
                  and values["input_current_40mhz_a"] < 20e-6)
        return {"source_ac_pass": float(passed)}
    if values.get("simulation_complete") != 1:
        raise ValueError("Missing transient completion marker")
    gain, sfdr = dynamic_metrics(Path(work) / "dynamic.dat", case["frequency_hz"])
    if not (math.isfinite(gain) and math.isfinite(sfdr)):
        raise ValueError("Nonfinite SFDR result")
    return {"fundamental_gain_vv": gain, "sfdr_db": sfdr,
            "source_sfdr_pass": float(gain > 0.95 and sfdr > case["sfdr_limit_db"])}
