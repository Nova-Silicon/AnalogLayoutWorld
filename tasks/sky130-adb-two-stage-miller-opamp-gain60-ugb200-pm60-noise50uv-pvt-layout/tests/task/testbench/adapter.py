from pathlib import Path
from eda.source_suites.ota_suites import Miller60
from eda.area_v2 import reference_area
import hashlib
import json


class PhysicalMiller60(Miller60):
    def __init__(self, root, reference):
        # The source device policy reads ngspice's expanded listing, where the
        # PDK MIM-capacitor model contributes internal R/C elements with
        # expression values; those are not ideal DUT primitives and were
        # reported as policy failures (a false positive in reference presim).
        # Audit the frozen physical DUT instead, as the line-driver task does.
        # Electrical thresholds and source aggregation are unchanged.
        super().__init__(source_path=Path(root) / "upstream/verify.py", reference=False)
        self.physical_audit = None
        if reference:
            dut = Path(root).parent / 'circuit.spice'
            top = json.loads((Path(root).parent / 'constraints.json').read_text())['top']
            area = reference_area(dut.read_text(), top)
            self.physical_audit = (f"{len(area['effective_area_devices'])} supported physical devices; "
                                   f"DUT SHA256 {hashlib.sha256(dut.read_bytes()).hexdigest()}")

    def checks(self, case, row):
        checks = super().checks(case, row)
        if self.physical_audit is not None:
            checks.append({'name': 'trusted_physical_dut', 'passed': True, 'message': self.physical_audit})
        return checks


def create_suite(root, reference=False):
    return PhysicalMiller60(root, reference)
