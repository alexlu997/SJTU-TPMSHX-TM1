"""Safe YAML/JSON ComputeConfig loading, separate from prepared Case files."""
from pathlib import Path

from .text_file import read_json, write_json as write_json


def load_config(path):
    from tm1.data_types.compute_config import ComputeConfig

    path = Path(path)
    if path.suffix.lower() == '.json':
        data = read_json(path)
    else:
        import yaml
        data = yaml.safe_load(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError('configuration must be a mapping')
    return ComputeConfig.from_dict(data)
