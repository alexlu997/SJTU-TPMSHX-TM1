from pathlib import Path

import pytest

from sjtu_tpmshx.validation.sco2_exp.load_sco2_exp import load_exp


_XLSX = Path(__file__).resolve().parents[2] / 'data/raw_data/experiments/sco2/sco2_DG7-t0p6_hx_experiment_summary.xlsx'


@pytest.mark.skipif(not _XLSX.exists(),
                    reason="sCO2 experiment Excel not on this machine")
def test_diamond_redo_cases_are_rejected():
    experiment = load_exp("Diamond")
    redo = experiment[experiment["case"].isin([25, 42])]

    assert set(redo["done"]) == {"重做"}
    assert len(redo) == 4
    assert not redo["ok_done"].any()


@pytest.mark.parametrize("topology", ["Diamond", "Gyroid"])
@pytest.mark.parametrize("reverse_hot", [False, True])
def test_gauge_conversion_endpoint_reference_and_cached_fields(
        monkeypatch, topology, reverse_hot):
    import pandas as pd
    from sjtu_tpmshx.models.sco2_props import sco2_prop
    from sjtu_tpmshx.validation.sco2_exp import load_sco2_exp as loader

    mapping = loader._MAPS[topology]
    raw = pd.DataFrame(index=range(5), columns=range(39), dtype=object)
    for column, label in mapping["guards"].items():
        raw.iloc[3, column] = label
    for field, value in (("L_ch", .182), ("Dh_sheet", .002),
                         ("A_flow", .0006), ("A_heat", .3),
                         ("done", "完成"), ("hb", .04)):
        raw.iloc[4, mapping[field]] = value
    for side, tin, tout, pressure, mdot, cached_q in (
            ("hot", 110. if reverse_hot else 150.,
             150. if reverse_hot else 110., 9., .1, 1.25),
            ("cold", 90., 120., 10., .12, 1.3)):
        for field, value in dict(mdot=mdot, Tin=tin, Tout=tout,
                                 Pin=pressure, Pout=pressure - .1,
                                 hin=500., hout=510., Q=cached_q, dP=.1).items():
            raw.iloc[4, mapping[side][field]] = value
    monkeypatch.setattr(loader.pd, "read_excel", lambda *args, **kwargs: raw)
    monkeypatch.setattr(loader, "tpms_geometry", lambda *args: {"D_h": .002})

    result = loader.load_exp(topology).set_index("side")
    assert not {'h', 'Nu', 'T_wall_K', 'T_other_K', 'dT_streams_K', 'ok_dT'} & set(result)
    assert len(result) == 2  # A reversed stream remains visible and flagged.
    for side, pressure, mdot, cached_q in (
            ("hot", 9., .1, 1.25), ("cold", 10., .12, 1.3)):
        row = result.loc[side]
        assert row.Pin_MPa == pressure
        assert row.Pout_MPa == pytest.approx(pressure - .1)
        assert row.Pin_abs_Pa == pytest.approx(pressure * 1e6 + 101325)
        assert row.Pout_abs_Pa == pytest.approx((pressure - .1) * 1e6 + 101325)
        assert row.P_mean_Pa == pytest.approx((pressure - .05) * 1e6 + 101325)
        assert row.Pin_abs_Pa - row.Pout_abs_Pa == pytest.approx(row.dP_MPa * 1e6)
        assert row.mdot == mdot
        assert row.T_mean_K == pytest.approx((row.Tin_C + row.Tout_C) / 2 + 273.15)
        assert row.Re == pytest.approx(row.rho * row.u * .002 / row.mu)
        assert row.f == pytest.approx(.1e6 * .002 / (.182 * .5 * row.rho * row.u**2))
        assert row.hin_cached_kJ_kg == 500.
        assert row.hout_cached_kJ_kg == 510.
        assert row.Q_cached_kW == cached_q
        assert row.HB_cached == .04 and row.ok_hb_cached
        hin = sco2_prop('H', row.Tin_C + 273.15, pressure * 1e6 + 101325)
        hout = sco2_prop('H', row.Tout_C + 273.15, (pressure - .1) * 1e6 + 101325)
        assert row.hin_J_kg == pytest.approx(hin)
        assert row.hout_J_kg == pytest.approx(hout)
        sign = 1 if side == "hot" else -1
        assert row.Q_kW == pytest.approx(mdot * sign * (hin - hout) / 1000)
    hot, cold = result.loc["hot"], result.loc["cold"]
    assert bool(hot.ok_heat_flow) is not reverse_hot
    assert cold.ok_heat_flow
    assert hot.HB == pytest.approx((cold.Q_kW - hot.Q_kW) / hot.Q_kW)
    assert cold.HB == hot.HB
    assert result.attrs["reference"]["version"] == loader.REFERENCE_VERSION
