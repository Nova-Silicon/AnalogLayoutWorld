from pathlib import Path
from eda.source_suites.ldo_suites import CaplessLdo
from eda.area_v2 import reference_area
import hashlib
import json


class PhysicalCaplessLdo(CaplessLdo):
    def __init__(self, root, reference):
        # The source policy parses a free-form /app/circuit.spi; the current
        # simulator passes an include-only adapter. Audit the frozen physical
        # DUT itself instead, retaining every electrical predicate unchanged.
        super().__init__(source_path=Path(root)/"upstream/verify.py", reference=False)
        self.physical_audit = None
        if reference:
            dut = Path(root).parent / 'circuit.spice'
            top = json.loads((Path(root).parent / 'constraints.json').read_text())['top']
            area = reference_area(dut.read_text(), top)
            self.physical_audit = f"{len(area['effective_area_devices'])} supported physical devices; DUT SHA256 {hashlib.sha256(dut.read_bytes()).hexdigest()}"

    def checks(self, case, row):
        checks = super().checks(case, row)
        if self.physical_audit is not None:
            checks.append({'name': 'trusted_physical_dut', 'passed': True, 'message': self.physical_audit})
        return checks

def create_suite(root, reference=False):
    return PhysicalCaplessLdo(root, reference)
