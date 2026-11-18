from pathlib import Path
from eda.source_suites.additional_suites import Gmr15

def create_suite(root, reference=False):
    return Gmr15(source_path=Path(root)/"upstream/verify.py", reference=reference)
