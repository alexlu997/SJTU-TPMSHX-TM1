"""Resolve existing low-level solver imports to the stage bindings."""
from sjtu_tpmshx.shared import _SEARCH_PATH

__path__ = [_SEARCH_PATH]
__spec__.submodule_search_locations = __path__
