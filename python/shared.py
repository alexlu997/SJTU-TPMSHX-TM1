"""Resolve published shared module names to their current owners on first use."""
from importlib import import_module
from importlib.machinery import ModuleSpec
from importlib.util import find_spec
import sys

_PACKAGES = {"configs": "model_configs", "domain": "data_types", "models": "physical_models",
             "df_surrogate": "physical_models.df_surrogate", "io": "file_io"}
_MOVED = {
    "domain.validator": "preprocess.validator",
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


class _SharedNames:
    """Expose one module object for each old and current spelling."""

    def find_spec(self, fullname, target=None):
        prefix = __name__ + "."
        if not fullname.startswith(prefix):
            return None
        relative = fullname[len(prefix):]
        owner, separator, tail = relative.partition(".")
        spelling = _MOVED.get(relative)
        if spelling is None:
            if relative.startswith(("_native_", "models._native_")):
                spelling = "cpp_interface." + relative.rsplit(".", 1)[-1]
            elif owner in _PACKAGES:
                spelling = _PACKAGES[owner] + separator + tail
            else:
                return None
        canonical = __package__ + "." + spelling
        spec = find_spec(canonical)
        if spec is None:
            return None
        alias = ModuleSpec(fullname, self, is_package=spec.submodule_search_locations is not None)
        alias.loader_state = canonical
        return alias

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        canonical = import_module(module.__spec__.loader_state)
        if hasattr(canonical, "__path__") and _SEARCH_PATH not in canonical.__path__:
            canonical.__path__.insert(0, _SEARCH_PATH)
        sys.modules[module.__name__] = canonical


__path__ = [_SEARCH_PATH]
__spec__.submodule_search_locations = __path__
sys.path_importer_cache[_SEARCH_PATH] = _SharedNames()
