from pathlib import Path
from eda.source_suites.basic import Telescopic

def create_suite(root, reference=False):
    return Telescopic(source_path=Path(root)/"upstream/verify.py", reference=reference)
