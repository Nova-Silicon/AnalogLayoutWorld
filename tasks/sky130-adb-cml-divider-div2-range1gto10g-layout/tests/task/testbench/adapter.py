from pathlib import Path
from eda.source_suites.divider_suites import CmlDivider

def create_suite(root, reference=False):
    return CmlDivider(source_path=Path(root)/"upstream/verify.py", reference=reference)
