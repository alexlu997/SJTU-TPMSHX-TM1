"""Read the named decision and objective columns written by BO checkpoints."""
import csv

import numpy as np


def read_pareto_csv(path, decision_dim_expected=None):
    with open(path, newline='', encoding='utf-8-sig') as source:
        reader = csv.DictReader(source)
        header = reader.fieldnames or []
        dimension = len(header) - 2 if decision_dim_expected is None else decision_dim_expected
        columns = [f'x{i}' for i in range(dimension)] + ['Q_W_per_m', 'dP_Pa']
        if dimension < 1 or len(header) != len(columns) or set(header) != set(columns):
            raise ValueError(f'Pareto CSV must contain x0..x{dimension - 1}, '
                             'Q_W_per_m and dP_Pa for the configured field layout')
        rows = []
        for index, row in enumerate(reader):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f'Pareto row {index} does not match the CSV columns')
            try:
                values = np.asarray([row[name] for name in columns], dtype=float)
            except ValueError as exc:
                raise ValueError(f'Pareto row {index} contains nonnumeric values') from exc
            if not np.all(np.isfinite(values)):
                raise ValueError(f'Pareto row {index} contains nonfinite values')
            rows.append(values)
    return np.asarray(rows, dtype=float).reshape(-1, len(columns))
