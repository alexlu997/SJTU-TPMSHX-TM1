"""Apply NumPy error policy to ordered native operation notices."""
import sys
import warnings

import numpy as np


def floating_events(events, *, stacklevel):
    """Consume (NumPy flags, operation text) pairs in source operation order."""
    flags = ((1, 'divide', 'divide by zero'), (2, 'over', 'overflow'),
             (4, 'under', 'underflow'), (8, 'invalid', 'invalid value'))
    for value, operation in events:
        policy, handler = np.geterr(), np.geterrcall()
        for flag, category, label in flags:
            if not value & flag or policy[category] == 'ignore':
                continue
            text = f'{label} encountered in {operation}'
            mode = policy[category]
            if mode == 'warn':
                warnings.warn(text, RuntimeWarning, stacklevel=stacklevel)
            elif mode == 'raise':
                raise FloatingPointError(text)
            elif mode == 'print':
                print('Warning: ' + text, file=sys.stderr)
            elif mode == 'call':
                if handler is None:
                    raise NameError(f'python callback specified for {label} (in  {operation}) but no function found.')
                handler(label, value)
            elif mode == 'log':
                if handler is None:
                    raise NameError(f'log specified for {label} (in {operation}) but no object with write method found.')
                handler.write('Warning: ' + text + '\n')
