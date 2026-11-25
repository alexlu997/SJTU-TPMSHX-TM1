"""Resolve published shared module names to their current owners on first use."""
from importlib import import_module
from importlib.machinery import ModuleSpec
from importlib.util import find_spec
import sys

_PACKAGES = {"configs": "model_configs", "domain": "data_types", "models": "physical_models",
             "df_surrogate": "physical_models.df_surrogate", "io": "file_io"}
_MOVED = {
    "_native_quick_prepare": "preprocess.quick_design",
    "models._native_quick_prepare": "preprocess.quick_design",
    "df_surrogate.ingest_cfd_kappa": "development.runs.cfd_asym.ingest_cfd_kappa",
    "df_surrogate.kappa_asym": "development.runs.cfd_asym.kappa_asym",
    "df_surrogate.load_sco2_cfd": "preprocess.offline.load_sco2_cfd",
    "domain.range_policy": "physical_models.range_policy",
    "io.cli_options": "applications.cli.cli_options",
    "io.yaml_config": "file_io.config_io",
    "logutil": "run_control.logutil",
    "result_display": "postprocess.result_display",
    "result_math": "postprocess.result_math",
    **{f"domain.{name}": f"run_control.{name}" for name in (
        "cancellation", "module_ports", "paused_run", "provenance", "run_environment", "run_warnings")},
}
_SEARCH_PATH = __file__


def _df_child(name):
    relative = f"df_surrogate.{name}"
    if relative in _MOVED:
        return import_module(f"{__name__}.{relative}")
    raise AttributeError(f"module '{__package__}.{_PACKAGES['df_surrogate']}' has no attribute {name!r}")


class _SharedNames:
    """Resolve published modules to their current owners."""

    def _shared_target(self, fullname):
        prefix = __name__ + "."
        if fullname.startswith(prefix):
            relative = fullname[len(prefix):]
        else:
            # A from-import asks the canonical package for a child with the old name.
            parent, _, child = fullname.rpartition(".")
            owner = next((key for key, value in _PACKAGES.items()
                          if parent == __package__ + "." + value), None)
            if owner == "df_surrogate":
                return None
            relative = f"{owner}.{child}"
            if relative not in _MOVED and not relative.startswith("models._native_"):
                return None
        owner, separator, tail = relative.partition(".")
        spelling = _MOVED.get(relative)
        if spelling is None:
            if relative.startswith(("_native_", "models._native_")):
                spelling = "cpp_interface." + relative.rsplit(".", 1)[-1]
            elif owner in _PACKAGES:
                spelling = _PACKAGES[owner] + separator + tail
            else:
                return None
        return __package__ + "." + spelling

    def find_spec(self, fullname, target=None):
        driver_prefix = __package__ + ".solvers.backends.cpp."
        if fullname.startswith(driver_prefix):
            driver = fullname[len(driver_prefix):]
            if driver == "quick_design":
                directory = "solvers"
            elif driver in ("full_2d_stage", "full_3d_stage", "run_state"):
                directory = "cpp_interface"
            else:
                directory = "cpp_interface.solver_library"
            canonical = f"{__package__}.{directory}.{driver}"
        else:
            canonical = self._shared_target(fullname)
        if canonical is None:
            return None
        spec = find_spec(canonical)
        if spec is None:
            return None
        alias = ModuleSpec(fullname, self, is_package=spec.submodule_search_locations is not None)
        alias.origin = spec.origin
        alias.has_location = spec.has_location
        alias.loader_state = canonical
        return alias

    def get_code(self, fullname):
        canonical = self.find_spec(fullname).loader_state
        return find_spec(canonical).loader.get_code(canonical)

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        canonical = import_module(module.__spec__.loader_state)
        if hasattr(canonical, "__path__") and _SEARCH_PATH not in canonical.__path__:
            canonical.__path__.insert(0, _SEARCH_PATH)
        if module.__name__ == __name__ + ".df_surrogate":
            # A from-import looks up the published child on this package object.
            canonical.__getattr__ = _df_child
        sys.modules[module.__name__] = canonical


__path__ = [_SEARCH_PATH]
__spec__.submodule_search_locations = __path__
sys.path_importer_cache[_SEARCH_PATH] = _SharedNames()
