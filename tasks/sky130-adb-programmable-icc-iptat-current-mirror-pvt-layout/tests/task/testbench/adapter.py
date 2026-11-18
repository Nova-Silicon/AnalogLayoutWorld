from pathlib import Path
from eda.source_suites.root_suites import ProgrammableMirror

def create_suite(root, reference=False):
    return ProgrammableMirror(source_path=Path(root)/"upstream/verify.py", reference=reference)
