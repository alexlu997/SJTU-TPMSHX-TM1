"""Safe YAML/JSON ComputeConfig loading, separate from prepared Case files."""
import json
from pathlib import Path

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')


def load_config(path):
    from sjtu_tpmshx.data_types.compute_config import ComputeConfig

    path = Path(path)
    if path.suffix.lower() == '.json':
        data = read_json(path)
    else:
        import yaml
        data = yaml.safe_load(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError('configuration must be a mapping')
    return ComputeConfig.from_dict(data)
