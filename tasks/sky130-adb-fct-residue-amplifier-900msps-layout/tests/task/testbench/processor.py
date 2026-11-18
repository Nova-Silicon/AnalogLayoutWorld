"""Original FCT sample analysis, with strict missing/duplicate/nonfinite checks."""
import cmath
import math
import re

def dft(samples):
    count = len(samples)
    return [
        sum(value * cmath.exp(-2j * math.pi * k * n / count) for n, value in enumerate(samples))
        for k in range(count // 2 + 1)
    ]

def analyze(values, sample_count, tone_bin, input_peak):
    names = [
        f"out{side}{suffix}_{index:03d}"
        for index in range(sample_count)
        for suffix in ("", "_early")
        for side in ("p", "n")
    ] + ["power_w"]
    if any(name not in values or not math.isfinite(values[name]) for name in names):
        return None
    outp = [values[f"outp_{index:03d}"] for index in range(sample_count)]
    outn = [values[f"outn_{index:03d}"] for index in range(sample_count)]
    outp_early = [values[f"outp_early_{index:03d}"] for index in range(sample_count)]
    outn_early = [values[f"outn_early_{index:03d}"] for index in range(sample_count)]
    differential = [p - n for p, n in zip(outp, outn)]
    differential_track = [p - n for p, n in zip(outp_early, outn_early)]
    common_mode = [(p + n) / 2 for p, n in zip(outp, outn)]
    mean = sum(differential) / sample_count
    spectrum = dft([value - mean for value in differential])
    fundamental = abs(spectrum[tone_bin])
    spur = max(abs(value) for index, value in enumerate(spectrum[1:], 1) if index != tone_bin)
    output_peak = 2 * fundamental / sample_count
    return {
        "gain_vv": output_peak / input_peak,
        "sfdr_db": 20 * math.log10(max(fundamental, 1e-30) / max(spur, 1e-30)),
        "cm_mean_v": sum(common_mode) / sample_count,
        "output_min_v": min(outp + outn),
        "output_max_v": max(outp + outn),
        "hold_movement_ratio": math.sqrt(
            sum((track - held) ** 2 for track, held in zip(differential_track, differential))
            / max(sum(held ** 2 for held in differential), 1e-30)
        ),
        "power_w": values["power_w"],
    }


def process_case(case, work, values):
    names = {f"out{side}{suffix}_{index:03d}" for index in range(32)
             for suffix in ("", "_early") for side in ("p", "n")} | {"power_w"}
    measured = {}
    for line in (work / "command.log").read_text(errors="replace").splitlines():
        match = re.match(r"^\s*([A-Za-z]\w*)\s*=\s*(\S+)", line)
        if match and match[1].lower() in names:
            name = match[1].lower()
            if name in measured:
                raise ValueError(f"Duplicate FCT measurement: {name}")
            value = float(match[2])
            if not math.isfinite(value):
                raise ValueError(f"Nonfinite FCT measurement: {name}")
            measured[name] = value
    if names - measured.keys():
        raise ValueError(f"Missing FCT measurements: {sorted(names - measured.keys())}")
    amplitude = case["amplitude"]
    metrics = analyze(measured, 32, 5 if amplitude == "10mv" else 3,
                      0.010 if amplitude == "10mv" else 0.020)
    if metrics is None:
        raise ValueError("Incomplete FCT sampled-data metrics")
    # The shared runner already parses the directly measured power_w.
    metrics.pop("power_w")
    return metrics
