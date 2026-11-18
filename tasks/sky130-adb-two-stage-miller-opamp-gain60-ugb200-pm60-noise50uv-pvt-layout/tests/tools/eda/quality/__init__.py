"""Program-only engineering measurements of one frozen layout.

This package reads existing GDS/LVS evidence. It never runs a model, starts
extraction, looks up a historical trial, or computes a footprint numerator.
"""
from .collect import VERSION, collect

__all__ = ["VERSION", "collect"]
