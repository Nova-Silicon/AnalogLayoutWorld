"""PDK packaging boundaries; these tests do not execute physical EDA algorithms."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
PDK = REPO / "docker/pdk"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verify = load_module("pdk_verify", PDK / "verify.py")
prepare = load_module("pdk_prepare", PDK / "prepare.py")


class VendoredAssets(unittest.TestCase):
    def test_installed_file_set_and_bytes_match_the_reviewed_manifest(self):
        result = verify.verify(PDK / "sky130")
        self.assertTrue(result["verified"])
        self.assertEqual(result["runtime_prefix"], "/opt/analog-layout/pdks/sky130")

    def test_algorithm_inputs_remain_at_the_qualified_revisions(self):
        # Independent anchors prevent accidentally "fixing" a changed deck or
        # model merely by regenerating its manifest during release packaging.
        anchors = {
            "klayout/sky130A_mr.drc": "0d2fb47af78697b56ec8cb819a49d54c64a64ac08dd4160f31889415f5004ad7",
            "klayout/sky130.lvs": "5b4ede4bdb4744b60e42c9b29baa93f40bb24430fb8f3a48a276a712a492ac38",
            "python/sky130/pcells/mosfets.py": "5887380a280b06de222c6600329f2a7306cbff9a8771ea5f99ee3a822871d285",
            "python/sky130/pcells/resistors.py": "98a6428098be4bb1e72a6f87e809a45657571181ac23cb232176123413cd56f9",
            "sky130A/libs.tech/combined/continuous/sky130.lib.spice": "c7e9fe87ffc2685bc56da02f92cd48b1403a5e9da85cc7978027fb0ca347d581",
            "sky130A/libs.tech/ngspice/sky130.lib.spice": "17c208a699228f5acb87bf59c09c22a4c4d3937b6766b4957737d34e8e075f64",
            "sky130A/libs.tech/magic/sky130A.tech": "59c4356c1da52fa38a40c8cefdd2cfef7a0afd91825a42fc06aa8f1913b4f214",
            "sky130A/libs.tech/netgen/sky130A_setup.tcl": "7a33f3f54fab57a9d9b0887ac7b7b64ce6c454110e8b7f01f3cfb90a1282dc94",
        }
        for relative, expected in anchors.items():
            with self.subTest(relative=relative):
                actual = hashlib.sha256((PDK / "sky130" / relative).read_bytes()).hexdigest()
                self.assertEqual(actual, expected)

    def test_all_declared_model_corners_have_a_complete_local_closure(self):
        root = PDK / "sky130/sky130A/libs.tech/combined/continuous"
        files, edges = prepare.model_closure(root / "sky130.lib.spice", root)
        record = json.loads((PDK / "sky130/model-includes.json").read_text())
        self.assertEqual(len(files), record["file_count"])
        self.assertEqual(edges, record["edges"])
        self.assertEqual({p.name for p in files}, {p.name for p in root.iterdir()})
        self.assertTrue(record["all_corner_sections_scanned"])

    def test_binned_models_have_their_own_complete_unmodified_closure(self):
        root = PDK / "sky130/sky130A"
        files, edges = prepare.model_closure(root / "libs.tech/ngspice/sky130.lib.spice", root)
        record = json.loads((PDK / "sky130/binned-model-includes.json").read_text())
        self.assertEqual(len(files), record["file_count"])
        self.assertEqual(len(files), 319)
        self.assertEqual(edges, record["edges"])
        self.assertEqual(len(edges), 704)
        self.assertTrue(any(path.is_relative_to(root / "libs.ref") for path in files))
        self.assertNotEqual((root / "libs.tech/ngspice/sky130.lib.spice").read_bytes(),
                            (root / "libs.tech/combined/continuous/sky130.lib.spice").read_bytes())

    def test_runtime_paths_licenses_and_reference_documents_are_present(self):
        root = PDK / "sky130"
        self.assertEqual((root / "sky130A/libs.tech/netgen/setup.tcl").read_bytes(),
                         (root / "sky130A/libs.tech/netgen/sky130A_setup.tcl").read_bytes())
        for path in ("licenses/Apache-2.0", "licenses/GPL-3",
                     "licenses/gdsfactory-skywater130-MIT", "licenses/open-pdks-LICENSE",
                     "docs/skywater-pdk/LICENSE", "docs/skywater-pdk/rules.rst",
                     "docs/DEVICE_API.md", "docs/DEVICE_API.zh-CN.md"):
            with self.subTest(path=path):
                self.assertTrue((root / path).is_file())
        rc = (root / "sky130A/libs.tech/magic/sky130A.magicrc").read_text()
        tcl = (root / "sky130A/libs.tech/magic/sky130A.tcl").read_text()
        self.assertIn("set PDK_ROOT /opt/analog-layout/pdks/sky130", rc)
        self.assertIn("set TECHPATH /opt/analog-layout/pdks/sky130", tcl)


class FileBoundary(unittest.TestCase):
    def make_fixture(self, root: Path):
        (root / "model.spice").write_text("* example\n")
        content = (root / "model.spice").read_bytes()
        manifest = {"schema": "analoglayoutworld-sky130-runtime-v1",
                    "runtime_prefix": "/opt/analog-layout/pdks/sky130",
                    "asset_file_count": 1, "asset_bytes": len(content),
                    "files": {"model.spice": {"bytes": len(content),
                              "sha256": hashlib.sha256(content).hexdigest()}}}
        (root / "asset-manifest.json").write_text(json.dumps(manifest))

    def test_changed_missing_or_extra_file_is_rejected(self):
        for mutation in ("changed", "missing", "extra"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.make_fixture(root)
                if mutation == "changed":
                    (root / "model.spice").write_text("* changed\n")
                elif mutation == "missing":
                    (root / "model.spice").unlink()
                else:
                    (root / "private-config.json").write_text("{}")
                with self.assertRaises(ValueError):
                    verify.verify(root)

    def test_symlink_cannot_smuggle_a_file_into_the_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_fixture(root)
            (root / "alias").symlink_to(root / "model.spice")
            with self.assertRaisesRegex(ValueError, "Symbolic"):
                verify.verify(root)

    def test_source_models_cannot_reference_outside_or_dynamic_paths(self):
        for reference in ("../outside.spice", "/absolute.spice", "${MODEL_ROOT}/x.spice"):
            with self.subTest(reference=reference), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "models"
                root.mkdir()
                (Path(directory) / "outside.spice").write_text("* outside\n")
                entry = root / "main.spice"
                entry.write_text(f".include {reference}\n")
                with self.assertRaises((ValueError, FileNotFoundError)):
                    prepare.model_closure(entry, root)

    def test_magic_relocation_is_limited_to_one_fallback_assignment(self):
        self.assertEqual(prepare.relocate_magic("set TECHPATH /build/pdk\nkeep\n"),
                         "set TECHPATH /opt/analog-layout/pdks/sky130\nkeep\n")
        with self.assertRaises(ValueError):
            prepare.relocate_magic("set PDK_ROOT /a\nset TECHPATH /b\n")
        with self.assertRaises(ValueError):
            prepare.relocate_magic("no fallback assignment\n")


if __name__ == "__main__":
    unittest.main()
