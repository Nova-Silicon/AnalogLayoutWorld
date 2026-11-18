from pathlib import Path
from eda.source_suites.complementary_suite import Complementary

def create_suite(root, reference=False):
    return Complementary(source_path=Path(root)/"upstream/verify.py", reference=reference)
