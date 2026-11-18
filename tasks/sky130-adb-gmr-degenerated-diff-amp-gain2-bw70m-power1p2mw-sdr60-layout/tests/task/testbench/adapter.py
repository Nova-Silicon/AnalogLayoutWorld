from pathlib import Path
from eda.source_suites.additional_suites import Gmr5

def create_suite(root, reference=False):
    return Gmr5(source_path=Path(root)/"upstream/verify.py", reference=reference)
