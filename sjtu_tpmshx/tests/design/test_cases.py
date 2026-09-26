import openpyxl
import csv
import pytest
from sjtu_tpmshx.design.cases import load_cases, DesignCase

def _make_xlsx(path):
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["case","hot_fluid","T_in_h_K","P_in_h_kPa","mdot_h",
               "cold_fluid","T_in_c_K","P_in_c_kPa","mdot_c",
               "Q_kW","dT_h_K","dPlim_h","dPlim_c"])
    ws.append([1,"air",688.23,1088.7,0.2855,"water",320.0,200.0,0.5,
               36.7,None,0.075,0.05])            # 用 Q
    ws.append([2,"air",700.0,1000.0,0.25,"water",320.0,200.0,0.5,
               None,80.0,0.07,0.05])             # 用温降 ΔT
    wb.save(path)

def test_load_cases_both_duty(tmp_path):
    f = tmp_path / "spec.xlsx"; _make_xlsx(f)
    cs = load_cases(str(f))
    assert len(cs) == 2
    c1, c2 = cs
    assert isinstance(c1, DesignCase)
    assert abs(c1.P_in_h - 1_088_700.0) < 1            # kPa→Pa
    assert abs(c1.Q - 36_700.0) < 1 and c1.dT is None  # Q 路
    assert c2.Q is None and abs(c2.dT - 80.0) < 1e-9   # 温降 ΔT 路
    assert abs(c1.dPlim_h - 0.075) < 1e-9


def _input_row():
    return dict(case='1.0', hot_fluid='air', T_in_h_K=400., P_in_h_kPa=200.,
                mdot_h=.02, cold_fluid='water', T_in_c_K=300., P_in_c_kPa=200.,
                mdot_c=.01, Q_kW=1., dT_h_K='', dPlim_h=.05, dPlim_c=.05)


def _write_row(path, row):
    if path.suffix == '.csv':
        with path.open('w', newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(row))
            writer.writeheader()
            writer.writerow(row)
    else:
        workbook = openpyxl.Workbook()
        workbook.active.append(list(row))
        workbook.active.append(list(row.values()))
        workbook.save(path)
        workbook.close()


@pytest.mark.parametrize('suffix', ['.csv', '.xlsx'])
@pytest.mark.parametrize('field,value,error_field', [
    ('case', '1.9', 'case'), ('case', 'inf', 'case'),
    ('Q_kW', 'nan', 'Q'), ('dT_h_K', 'inf', 'dT'),
    ('dPlim_h', 'nan', 'dPlim_h'), ('dPlim_c', '-inf', 'dPlim_c'),
])
def test_load_cases_rejects_invalid_requirements(tmp_path, suffix, field, value, error_field):
    row = _input_row()
    row[field] = value
    path = tmp_path / ('input' + suffix)
    _write_row(path, row)
    with pytest.raises(ValueError, match=error_field):
        load_cases(str(path))


@pytest.mark.parametrize('suffix', ['.csv', '.xlsx'])
@pytest.mark.parametrize('identifier,expected', [('1.0', 1), ('9007199254740993', 9007199254740993)])
def test_table_integer_identifiers_are_preserved(tmp_path, suffix, identifier, expected):
    row = _input_row()
    row['case'] = identifier
    path = tmp_path / ('input' + suffix)
    _write_row(path, row)
    case, = load_cases(str(path))
    assert case.case == expected
    assert case.Q == 1000. and case.P_in_h == 200000.


@pytest.mark.parametrize('field', ['Q', 'dT', 'dPlim_h', 'dPlim_c'])
@pytest.mark.parametrize('value', [float('nan'), float('inf')])
def test_direct_design_case_rejects_nonfinite_requirements(field, value):
    values = dict(case=1, hot_fluid='air', T_in_h=400., P_in_h=200000., mdot_h=.02,
                  cold_fluid='water', T_in_c=300., P_in_c=200000., mdot_c=.01,
                  Q=None, dT=None, dPlim_h=.05, dPlim_c=.05)
    values[field] = value
    with pytest.raises(ValueError, match=field):
        DesignCase(**values)


def test_direct_forward_case_need_not_supply_sizing_duty():
    case = DesignCase(1, 'air', 400., 200000., .02, 'water', 300., 200000., .01,
                      None, .05, .05)
    assert case.Q is None and case.dT is None
