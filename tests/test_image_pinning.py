"""Image distribution edits must keep every task and provenance aligned."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("alw_image_pinning", ROOT / "scripts/pin_base_image.py")
pins = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pins)
IMAGE = "ghcr.io/example/analoglayoutworld-eda@sha256:" + hashlib.sha256(b"manifest-fixture").hexdigest()


class ImagePinning(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="alw-pin-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        rows = [{"task_id": f"example-{i:02d}"} for i in range(40)]
        self.manifest = self.root / "configs/paper-v1/tasks.json"
        self.manifest.parent.mkdir(parents=True)
        self.manifest.write_text(json.dumps({"task_count": 40, "tasks": rows}))
        self.paths = []
        for row in rows:
            for role in ("environment", "tests"):
                path = self.root / "tasks" / row["task_id"] / role / "Dockerfile"
                path.parent.mkdir(parents=True)
                path.write_text("ARG ALW_BASE_IMAGE=analoglayoutworld/eda:paper-v1\n"
                                "FROM ${ALW_BASE_IMAGE}\nCOPY . /alb-workspace/\nENTRYPOINT []\n")
                self.paths.append(path)

    def test_dry_run_changes_nothing_then_apply_updates_all_and_is_idempotent(self):
        before = {path: path.read_bytes() for path in self.paths}
        review = pins.pin(self.root, IMAGE)
        self.assertEqual(len(review["changed_tasks"]), 40)
        self.assertEqual(len(review["changed_dockerfiles"]), 80)
        self.assertEqual(before, {path: path.read_bytes() for path in self.paths})
        pins.pin(self.root, IMAGE, apply=True)
        self.assertEqual(len(pins.task_defaults(self.root)), 40)
        self.assertEqual(set(pins.task_defaults(self.root).values()), {IMAGE})
        self.assertEqual(len(pins.deployment_defaults(self.root)), 80)
        self.assertEqual(set(pins.deployment_defaults(self.root).values()), {IMAGE})
        for path in self.paths:
            self.assertEqual(path.read_bytes(), before[path].replace(
                b"analoglayoutworld/eda:paper-v1", IMAGE.encode()))
        self.assertEqual(pins.pin(self.root, IMAGE, apply=True)["changed_tasks"], [])

    def test_partial_release_and_inconsistent_defaults_are_rejected_before_writes(self):
        last = self.paths[-1]
        last.write_text(last.read_text().replace("eda:paper-v1", "eda:other"))
        first = self.paths[0].read_bytes()
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            pins.pin(self.root, IMAGE, apply=True)
        self.assertEqual(self.paths[0].read_bytes(), first)
        data = json.loads(self.manifest.read_text()); data["tasks"].pop()
        self.manifest.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "complete 40"):
            pins.pin(self.root, IMAGE, apply=True)

    def test_only_active_arg_changes_when_comments_contain_old_reference(self):
        comment = "# Example: ARG ALW_BASE_IMAGE=analoglayoutworld/eda:paper-v1\n"
        for path in self.paths:
            path.write_text(comment + path.read_text())
        pins.pin(self.root, IMAGE, apply=True)
        for path in self.paths:
            self.assertTrue(path.read_text().startswith(comment))
            self.assertEqual(pins.dockerfile_default(path), IMAGE)

    def test_missing_or_symlinked_verifier_refuses_all_writes(self):
        first = self.paths[0].read_bytes()
        last = self.paths[-1]
        original = last.read_text()
        last.unlink()
        with self.assertRaisesRegex(ValueError, "regular file"):
            pins.pin(self.root, IMAGE, apply=True)
        self.assertEqual(self.paths[0].read_bytes(), first)
        last.symlink_to(self.paths[0])
        with self.assertRaisesRegex(ValueError, "regular file"):
            pins.pin(self.root, IMAGE, apply=True)
        self.assertEqual(self.paths[0].read_bytes(), first)
        last.unlink()
        last.write_text(original)

    def test_verifier_base_mismatch_does_not_change_forty_task_default_api(self):
        self.paths[-1].write_text(self.paths[-1].read_text().replace("eda:paper-v1", "eda:other"))
        self.assertEqual(len(pins.task_defaults(self.root)), 40)
        with self.assertRaisesRegex(ValueError, "80 agent/verifier.*inconsistent"):
            pins.deployment_defaults(self.root)

    def test_missing_or_dynamic_default_and_changed_from_rejected_before_writes(self):
        first = self.paths[0].read_bytes()
        for contents in ["FROM example:base\n", "ARG ALW_BASE_IMAGE=${OTHER}\nFROM ${ALW_BASE_IMAGE}\n",
                         "ARG ALW_BASE_IMAGE=analoglayoutworld/eda:paper-v1\nFROM different:base\n",
                         "ARG ALW_BASE_IMAGE=analoglayoutworld/eda:paper-v1\n# Previous: FROM ${ALW_BASE_IMAGE}\nFROM ubuntu:22.04\n",
                         "ARG ALW_BASE_IMAGE=analoglayoutworld/eda:paper-v1\nFROM ${ALW_BASE_IMAGE}\nFROM ubuntu:22.04\n"]:
            with self.subTest(contents=contents):
                self.paths[-1].write_text(contents)
                with self.assertRaises(ValueError):
                    pins.pin(self.root, IMAGE, apply=True)
                self.assertEqual(self.paths[0].read_bytes(), first)

    def test_rejects_tag_only_image_id_credentials_and_shell_or_path_syntax(self):
        for value in ["analoglayoutworld/eda:paper-v1", "sha256:" + "d" * 64,
                      "ghcr.io/example/eda@sha256:TODO", IMAGE + ";touch /tmp/unwanted",
                      "https://" + IMAGE, "secret:password@" + IMAGE, IMAGE.replace("/example/", "/../")]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                pins.pinned_reference(value)


if __name__ == "__main__":
    unittest.main()
