"""Safe YAML/JSON ComputeConfig loading, separate from prepared Case files."""
import json
from pathlib import Path

from sjtu_tpmshx.domain.compute_config import ComputeConfig


def load_config(path):
    path = Path(path)
    text = path.read_text(encoding='utf-8')
    if path.suffix.lower() == '.json':
        data = json.loads(text)
    else:
        import yaml
        data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError('configuration must be a mapping')
    return ComputeConfig.from_dict(data)
