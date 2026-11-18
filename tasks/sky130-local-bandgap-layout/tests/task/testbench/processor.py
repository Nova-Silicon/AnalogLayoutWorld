"""Accepted bandgap temperature-sweep measurements, independent of DUT names.

The formula and 34-point grid match source_records/local/bandgap/testbench.
An absent/incomplete waveform returns no derived values so the required
measurements fail; it must not turn into a falsely successful partial sweep.
"""
import math


def process_case(case, work, values):
    if case.get("kind") != "temperature":
        return {}
    try:
        rows = [[float(x) for x in line.split()]
                for line in (work / "temp_curve.dat").read_text().splitlines() if line.strip()]
        if (len(rows) != 34 or any(len(row) != 4 for row in rows)
                or [row[0] for row in rows] != list(range(-40, 126, 5))
                or not all(math.isfinite(x) for row in rows for x in row)):
            return {}
        reference = next(row[1] for row in rows if row[0] == 25)
        if reference <= 0:
            return {}
        refs = [row[1] for row in rows]
        return {"curve_min_V": min(refs), "curve_max_V": max(refs),
                "temperature_coefficient_ppm_K": (max(refs)-min(refs))/reference/165*1e6,
                "iq_max_A": max(-row[3] for row in rows)}
    except (OSError, ValueError, StopIteration):
        return {}
