from sjtu_tpmshx.applications.design.cases import load_cases, DesignCase

_HEADER = ("case,hot_fluid,T_in_h_K,P_in_h_kPa,mdot_h,"
           "cold_fluid,T_in_c_K,P_in_c_kPa,mdot_c,Q_kW,dT_h_K,dPlim_h,dPlim_c")

def _write_csv(path):
    path.write_text(
        _HEADER + "\n"
        "1,air,688.23,1088.7,0.2855,water,320.0,200.0,0.5,36.7,,0.075,0.05\n"
        "2,air,700.0,1000.0,0.25,water,320.0,200.0,0.5,,80.0,0.07,0.05\n",
        encoding="utf-8")

def test_load_csv_both_duty(tmp_path):
    f = tmp_path / "spec.csv"; _write_csv(f)
    cs = load_cases(str(f))
    assert len(cs) == 2
    c1, c2 = cs
    assert isinstance(c1, DesignCase)
    assert abs(c1.P_in_h - 1_088_700.0) < 1            # kPa→Pa
    assert abs(c1.Q - 36_700.0) < 1 and c1.dT is None  # Q 路 (空格=None)
    assert c2.Q is None and abs(c2.dT - 80.0) < 1e-9   # 温降路
    assert abs(c1.dPlim_h - 0.075) < 1e-9
    assert c1.hot_fluid == "air" and c1.cold_fluid == "water"
