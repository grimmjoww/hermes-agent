"""Pytest bootstrap for the self-evolving-harness plugin tests.

The plugin directory has an ``__init__.py`` (it IS the Hermes plugin package),
which pytest would otherwise try to collect as a test module — and that module
does ``from .harness_core ...`` relative imports that fail outside the host.
Ignore it, and ensure the plugin dir is on sys.path so ``harness_core`` imports
top-level the way the harness test-suite expects.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# Do not collect the plugin package __init__.py as a test module.
collect_ignore = ["__init__.py"]
