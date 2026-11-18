from pathlib import Path
from eda.source_suites.raw_ota_suites import FoldedCascode

def create_suite(root, reference=False):
    return FoldedCascode(source_path=Path(root)/"upstream/verify.py", reference=reference)
