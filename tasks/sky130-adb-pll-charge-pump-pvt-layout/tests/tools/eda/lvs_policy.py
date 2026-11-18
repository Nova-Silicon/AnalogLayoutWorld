"""Trusted SKY130 LVS alternatives; never configured by a submission.

The second deck only adds the reviewed, symmetric all-terminal-same-net
cleanup. Extraction, units, model readers and reference adapters are unchanged.
"""
from __future__ import annotations

from pathlib import Path


ORIGINAL_DECK_SHA256 = "5b4ede4bdb4744b60e42c9b29baa93f40bb24430fb8f3a48a276a712a492ac38"
DUMMY_PURGE_DECK_SHA256 = "4ccd09af8377d92ae78236cfbc03a4e14c9dee8c0f6edcf832aa756a1e1e6e6a"
DUMMY_PURGE_FLAGS = {
    "purge_same_net_devices": "true",
    "purge_sd_shorted_mos": "false",
    "purge_floating_two_terminal": "false",
}
POLICY_VERSION = "sky130-original-or-same-net-v2"


def is_qualified_deck_sha256(value: str) -> bool:
    return value in (ORIGINAL_DECK_SHA256, DUMMY_PURGE_DECK_SHA256)


def dummy_purge_deck() -> Path:
    """Locate and authenticate the private, package-owned alternative."""
    from .runtime import sha256

    path = Path(__file__).with_name("sky130_dummy_purge_20261103_v2.lvs")
    if path.is_symlink() or not path.is_file() or sha256(path) != DUMMY_PURGE_DECK_SHA256:
        raise ValueError("The reviewed same-net LVS deck is missing or has changed")
    return path


def validate_dummy_flags(flags: dict, command: list) -> None:
    """Check both the recorded policy and the actual KLayout arguments."""
    for key, value in DUMMY_PURGE_FLAGS.items():
        arguments = [item for previous, item in zip(command, command[1:])
                     if previous == "-rd" and isinstance(item, str)
                     and item.startswith(key + "=")]
        if flags.get(key) != value or arguments != [f"{key}={value}"]:
            raise ValueError(f"Unqualified same-net LVS switch: {key}")
