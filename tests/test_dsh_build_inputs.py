"""Check the package manager can consume the release's fixed build inputs."""
from __future__ import annotations

import base64
import hashlib
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DSHBuildInputTests(unittest.TestCase):
    def test_frozen_lock_binds_the_shipped_pnpm_hook(self):
        root = ROOT / "harnesses/deepseek-harness"
        lock = (root / "pnpm-lock.yaml").read_text()
        declared = re.search(r"(?m)^pnpmfileChecksum: (sha256-\S+)$", lock)
        self.assertIsNotNone(declared)
        actual = "sha256-" + base64.b64encode(hashlib.sha256((root / ".pnpmfile.cjs").read_bytes()).digest()).decode()
        self.assertEqual(declared.group(1), actual,
                         "A frozen pnpm install rejects a missing/different bound hook")
        self.assertEqual((root / "npmrc.empty").read_text().strip(), "")

    def test_explicit_tarball_override_stays_on_public_npm(self):
        lock = (ROOT / "harnesses/deepseek-harness/pnpm-lock.yaml").read_text()
        urls = re.findall(r"tarball:\s*([^\s,}]+)", lock)
        self.assertTrue(urls)
        for url in urls:
            self.assertTrue(url.startswith("https://registry.npmjs.org/"), url)
        self.assertIn("'@deepseek-ai/dsh':\n        specifier: 0.2.1-rc.5", lock)


if __name__ == "__main__":
    unittest.main()
