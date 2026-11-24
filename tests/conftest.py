"""Test setup.

protocol.py and connection.py have no Home Assistant imports, so they are loaded
straight from their files; the tests run with plain pytest or under the HA plugin.
"""

import importlib.util
import pathlib
import sys
import types

try:  # Under CI (pytest-homeassistant-custom-component) use the HA harness.
    import pytest_homeassistant_custom_component  # noqa: F401

    pytest_plugins = "pytest_homeassistant_custom_component"
except ImportError:  # Plain pytest: no HA needed for these tests.
    pass

_PKG = pathlib.Path(__file__).resolve().parent.parent / "custom_components" / "gofanco_matrix"


def load(name: str):
    """Import custom_components.gofanco_matrix.<name> without running the package __init__."""
    pkg_name = "gofanco_matrix_standalone"
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(_PKG)]
        sys.modules[pkg_name] = pkg
    full = f"{pkg_name}.{name}"
    if full in sys.modules:
        return sys.modules[full]
    spec = importlib.util.spec_from_file_location(full, _PKG / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[full] = module
    spec.loader.exec_module(module)
    return module
