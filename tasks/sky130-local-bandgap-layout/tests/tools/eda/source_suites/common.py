"""Load the task-packaged, unmodified upstream checker and its local helpers."""
import importlib.util
from pathlib import Path
import sys


def load_source(slug: str, source_path: Path):
    path = source_path.resolve(strict=True)
    name = 'alb_prototype_' + slug.replace('-', '_')
    # Each frozen verifier has its own utils.py; do not accidentally reuse a
    # previously imported task's module. No source attribute is patched.
    previous_utils = sys.modules.pop('utils', None)
    sys.path.insert(0, str(path.parent))
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
        sys.modules.pop('utils', None)
        if previous_utils is not None:
            sys.modules['utils'] = previous_utils
    return module


def point_id(point) -> str:
    return '__'.join(str(x) for x in point)
