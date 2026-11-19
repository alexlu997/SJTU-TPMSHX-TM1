"""Load the checkout's Python package under its public import name."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

spec = spec_from_file_location(__name__, Path(__file__).with_name("python") / "__init__.py")
package = module_from_spec(spec)
sys.modules[__name__] = package
spec.loader.exec_module(package)
