"""Offline checks of pinned Docker build inputs and their path boundaries."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]


def module(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "docker" / f"{name}.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class DockerAssets(unittest.TestCase):
    def setUp(self):
        self.lock = json.loads((ROOT / "docker/sources.lock.json").read_text())
        self.fetch = module("fetch_sources")

    def test_native_source_lock_is_public_and_pinned(self):
        rows = self.fetch.validate_lock(self.lock)
        self.assertEqual(len(rows), 8)
        self.assertRegex(self.lock["base_image"], r"^ubuntu:22\.04@sha256:[0-9a-f]{64}$")
        by_name = {row["name"]: row for row in rows}
        self.assertEqual(by_name["ngspice-46.tar.gz"]["sha256"],
                         "a0d1699af1940b06649276dcd6ff5a566c8c0cad01b2f7b5e99dedbb4d64c19b")

    def test_source_lock_rejects_path_escape_duplicate_and_credentials(self):
        mutations = [
            lambda rows: rows[0].update(name="../archive.tar.gz"),
            lambda rows: rows[1].update(name=rows[0]["name"]),
            lambda rows: rows[0].update(url="https://secret:password@www.python.org/source"),
            lambda rows: rows[0].update(url="http://www.python.org/source"),
            lambda rows: rows[0].update(url="https://private.invalid/source"),
            lambda rows: rows[0].update(sha256=""),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                changed = copy.deepcopy(self.lock)
                mutation(changed["files"])
                with self.assertRaises(ValueError):
                    self.fetch.validate_lock(changed)

    def test_python_artifacts_match_complete_requirement_lock(self):
        record = json.loads((ROOT / "docker/python-artifacts.lock.json").read_text())
        self.assertEqual(len(record["files"]), 99)
        normalized = lambda value: re.sub(r"[-_.]+", "-", value).lower()
        expected = {}
        for row in record["files"]:
            self.assertEqual(urlsplit(row["url"]).netloc, "files.pythonhosted.org")
            self.assertEqual(urlsplit(row["url"]).scheme, "https")
            self.assertRegex(row["sha256"], r"^[0-9a-f]{64}$")
            key = normalized(row["name"])
            self.assertNotIn(key, expected)
            expected[key] = (row["version"], row["sha256"])
        actual = {}
        for line in (ROOT / "docker/requirements.lock").read_text().splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            matched = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^ ]+) --hash=sha256:([0-9a-f]{64})", line)
            self.assertIsNotNone(matched)
            name, version, digest = matched.groups()
            actual[normalized(name)] = (version, digest)
        self.assertEqual(actual, expected)
        self.assertEqual([row["name"] for row in record["files"] if row["format"] == "sdist"], ["rectpack"])

    def test_runtime_paths_are_only_image_local(self):
        paths = module("finalize_runtime").runtime_paths()
        self.assertIn("netgen_setup", paths)
        self.assertIn("model_lib", paths)
        self.assertEqual(str(paths["model_lib"]),
                         "/opt/analog-layout/pdks/sky130/sky130A/libs.tech/combined/continuous/sky130.lib.spice")
        self.assertEqual(str(paths["model_lib_binned"]),
                         "/opt/analog-layout/pdks/sky130/sky130A/libs.tech/ngspice/sky130.lib.spice")
        for path in paths.values():
            self.assertTrue(path.is_absolute())
            self.assertTrue(path.is_relative_to("/opt/analog-layout"))

    def test_build_context_references_exist_and_excludes_task_copy(self):
        dockerfile = (ROOT / "docker/Dockerfile").read_text()
        self.assertNotIn("# syntax=", dockerfile)
        for line in dockerfile.splitlines():
            if line.startswith("COPY ") and "--from=" not in line:
                fields = line.split()[1:-1]
                for source in fields:
                    self.assertTrue(source.startswith("docker/"))
                    self.assertTrue((ROOT / source).exists(), source)
        self.assertIn("--require-hashes", dockerfile)
        self.assertIn("--no-build-isolation", dockerfile)
        self.assertIn("libgomp1", dockerfile)
        self.assertNotRegex(dockerfile, r"(?i)COPY\s+.*\b(?:tasks|tests|results|jobs|runs)/")

    def test_magic_manuals_match_the_paper_files_at_the_guides_path(self):
        runtime = module("check_runtime")
        texts = ROOT / "docker/magic-docs/text"
        self.assertEqual(set(runtime.check_magic_manuals(texts)),
                         {"ext2spice.txt", "extract.txt", "extresist.txt", "flatten.txt", "gds.txt"})
        self.assertIn("COPY docker/magic-docs/text/ /opt/analog-layout/tools/magic/lib/magic/doc/text/",
                      (ROOT / "docker/Dockerfile").read_text().splitlines())


class WheelLoaderAudit(unittest.TestCase):
    def setUp(self):
        self.runtime = module("check_runtime")
        self.site = Path("/opt/analog-layout/python/lib/python3.12/site-packages")
        self.bundle = self.site / "example.libs"
        self.library = self.bundle / "libhelper.so.1"
        self.consumer = self.site / "example/core.cpython-312-x86_64-linux-gnu.so"
        self.success = subprocess.CompletedProcess([], 0,
            f"libhelper.so.1 => {self.site}/example/../example.libs/libhelper.so.1 (0x123)\n"
            f"libdependency.so.2 => {self.bundle}/libdependency.so.2 (0x456)\n")
        self.dynamic = " 0x000000000000000f (RPATH) Library rpath: [$ORIGIN/../example.libs]\n"

    def test_parent_rpath_and_closed_dependency_graph_prove_auxiliary_library(self):
        result = self.runtime.parent_loader_context(
            self.library, self.bundle, [self.consumer], {self.consumer: self.success}, lambda _: self.dynamic)
        self.assertEqual(result["consumer"], str(self.consumer))
        self.assertEqual(result["declared_loader_paths"], [{"kind": "RPATH", "value": "$ORIGIN/../example.libs"}])

    def test_a_missing_dependency_in_parent_context_is_still_rejected(self):
        bad = subprocess.CompletedProcess([], 0, self.success.stdout + "libmissing.so => not found\n")
        result = self.runtime.parent_loader_context(
            self.library, self.bundle, [self.consumer], {self.consumer: bad}, lambda _: self.dynamic)
        self.assertIsNone(result)

    def test_missing_rpath_or_unrelated_loaded_library_is_not_an_exemption(self):
        for output, dynamic in [(self.success.stdout, ""),
                                ("libother.so => /usr/lib/libother.so (0x123)\n", self.dynamic)]:
            with self.subTest(output=output, dynamic=dynamic):
                process = subprocess.CompletedProcess([], 0, output)
                result = self.runtime.parent_loader_context(
                    self.library, self.bundle, [self.consumer], {self.consumer: process}, lambda _: dynamic)
                self.assertIsNone(result)

    def test_wheel_record_ownership_must_be_unique(self):
        site = self.site

        class Distribution:
            metadata = {"Name": "example"}
            files = [Path("example.libs/libhelper.so.1"), Path("example/core.cpython-312-x86_64-linux-gnu.so")]

            def locate_file(self, value):
                return site / value

        with patch.object(self.runtime.importlib.metadata, "distributions", return_value=[Distribution()]):
            name, consumers = self.runtime.wheel_consumers(self.library, site)
            self.assertEqual(name, "example")
            self.assertIn(self.consumer, consumers)
        with patch.object(self.runtime.importlib.metadata, "distributions", return_value=[Distribution(), Distribution()]):
            self.assertEqual(self.runtime.wheel_consumers(self.library, site), (None, set()))


if __name__ == "__main__":
    unittest.main()
