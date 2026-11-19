"""Build the Python package tree for tools that read modules from disk."""
from contextlib import chdir

from setuptools import Distribution


def build_package(root, directory):
    """Use the same names and data files as the wheel."""
    with chdir(root):
        distribution = Distribution({"script_name": "pyproject.toml"})
        distribution.parse_config_files(["pyproject.toml"])
        command = distribution.get_command_obj("build_py")
        command.build_lib = str(directory)
        command.ensure_finalized()
        command.run()
