"""Independent numerical state with its exact local prepared-case reference."""
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .model_refs import ModelRef, freeze_mapping


@dataclass(frozen=True)
class SolverCheckpoint:
    case_file: str
    case_id: str
    model_refs: tuple[ModelRef, ...]
    native_state: Mapping
    state_format: str = 'full_3d_continuation_v1'

    def __post_init__(self):
        if self.state_format != 'full_3d_continuation_v1':
            raise ValueError('unsupported solver checkpoint format')
        if not isinstance(self.case_id, str) or not self.case_id:
            raise ValueError('solver checkpoint requires a case identifier')
        if not isinstance(self.case_file, str) or not Path(self.case_file).is_absolute():
            raise ValueError('solver checkpoint requires an absolute prepared-case path')
        if any(not isinstance(ref, ModelRef) for ref in self.model_refs):
            raise TypeError('solver checkpoint requires ModelRef values')
        if not isinstance(self.native_state, Mapping) or not self.native_state:
            raise ValueError('solver checkpoint requires native state fields')
        for name, value in self.native_state.items():
            if not isinstance(name, str) or not name or '\0' in name:
                raise ValueError('invalid solver checkpoint field name')
            if not isinstance(value, str) and not (
                isinstance(value, np.ndarray) and value.ndim == 1
                and value.dtype in (np.dtype('float64'), np.dtype('uint64'), np.dtype('int64'), np.dtype('uint8'))
            ):
                raise TypeError('solver checkpoint fields require UTF-8 text or exact typed arrays')
        object.__setattr__(self, 'model_refs', tuple(self.model_refs))
        object.__setattr__(self, 'native_state', freeze_mapping(self.native_state))
