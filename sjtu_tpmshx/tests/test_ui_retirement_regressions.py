"""Exercise the repaired input/preview paths with isolated real Qt controls."""
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QMessageBox, QTableWidget, QTableWidgetItem
from matplotlib.figure import Figure


@pytest.fixture
def win(tmp_path, monkeypatch):
    from sjtu_tpmshx.controllers import user_storage

    def directory(location, *parts):
        path = tmp_path.joinpath(location.name, *parts)
        path.mkdir(parents=True, exist_ok=True)
        return path

    monkeypatch.setattr(user_storage, '_directory', directory)
    from sjtu_tpmshx.main import Main_Menu
    window = Main_Menu()
    yield window
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_real_fluid_builder_enables_each_supported_fluid(win):
    from sjtu_tpmshx.ui.window_config import config_from_window
    for side in ('A', 'B'):
        combo = getattr(win, 'combo_fluid' + side)
        assert [combo.itemText(i) for i in range(combo.count())] == ['Air', 'Water', 'sCO₂']
        for index, fluid in enumerate(('air', 'water', 'sco2')):
            assert combo.model().item(index).isEnabled()
            combo.setCurrentIndex(index)
            assert getattr(config_from_window(win), 'fluid_' + side).type == fluid


@pytest.mark.parametrize('bad', ['', 'invalid', 'nan'])
def test_normal_compute_ignores_2d_drafts_and_checks_them_in_3d(win, monkeypatch, bad):
    from sjtu_tpmshx.ui.window_config import config_from_window
    win.combo_dim.setCurrentIndex(0)
    names = ['le_Lz', 'le_Nz'] + [name for name in win._SESSION_LINE_EDITS if '_z_' in name]
    for name in names:
        field = getattr(win, name)
        field.setText(bad)
        field.setProperty('inpError', 'true')
    dialogs = []
    monkeypatch.setattr(QMessageBox, 'exec', lambda self: dialogs.append(self.text()))
    assert win._validate_inputs_preflight()
    cfg = config_from_window(win).validate()
    assert cfg.solver.Nz == 1 and cfg.geometry.Lz_m is None
    assert cfg.bc_A.in_z_ctr is None and cfg.bc_B.out_z_w is None
    assert [getattr(win, name).text() for name in names] == [bad] * len(names)
    assert not dialogs
    win.combo_dim.setCurrentIndex(1)
    assert not win._validate_inputs_preflight()
    assert dialogs
    with pytest.raises(ValueError, match='Lz|Nz'):
        config_from_window(win)


@pytest.mark.parametrize('side', ['A', 'B'])
@pytest.mark.parametrize('fluid,index,u,T,P', [
    ('air', 0, 20., 422., 192362.),
    ('water', 1, .1, 300., 2e5),
    ('sco2', 2, 2., 350., 12e6),
])
def test_autofill_dp_uses_selected_df_model(win, side, fluid, index, u, T, P):
    from sjtu_tpmshx.models.tpms_calc import compute
    from sjtu_tpmshx.df_surrogate.experimental_correction import apply_correction
    getattr(win, 'combo_fluid' + side).setCurrentIndex(index)
    win.combo_tpms.setCurrentText('Gyroid')
    win.le_Lcell.setText('7'); win.le_t.setText('.6'); win.le_ks.setText('16')
    for field, value in (('u', u), ('Tin', T), ('Pin', P)):
        getattr(win, 'le_' + field + side).setText(str(value))
    base = compute('Gyroid', 7., .6, u, T, P, 16., fluid_type=fluid)
    K, cF, _ = apply_correction('Gyroid', fluid, 7., .6, base['K_df'], base['cF_df'], u)
    corrected = base['mu'] * u / K + base['rho'] * cF * u**2
    for mode, expected in (('cfd_smooth', base['dP_per_L']), ('experimental', corrected)):
        win.combo_df_mode.setCurrentIndex(win.combo_df_mode.findData(mode))
        assert getattr(win, '_v_dPL' + side).text() == '—'
        win._auto_fill_fluid(side)
        assert getattr(win, '_v_dPL' + side).text() == f'{expected:.1f}'
    assert corrected != pytest.approx(base['dP_per_L'])
    assert compute('Gyroid', 7., .6, u, T, P, 16., fluid_type=fluid)['dP_per_L'] == base['dP_per_L']


def test_zone_drag_matches_domain_size_and_neighbour_clamp():
    from sjtu_tpmshx.ui.zone_editor import ZoneHandleManager
    table = QTableWidget(3, 4)
    for row, bounds in enumerate(((0., 50.), (50., 75.), (75., 100.))):
        for col, value in enumerate(bounds):
            table.setItem(row, col, QTableWidgetItem(str(value)))
    canvas = Figure().canvas
    window = SimpleNamespace(zone_table=table, chk_zones=SimpleNamespace(isChecked=lambda: True),
                             _zone_axis=lambda: 'y', canvas_layout=canvas, _draw_layout=lambda: None)
    manager = ZoneHandleManager(window)
    ax = canvas.figure.add_subplot()
    manager.draw_handles(ax, 182., 42.)
    manager._on_press(SimpleNamespace(inaxes=ax, ydata=21.))
    manager._on_motion(SimpleNamespace(ydata=22.))
    assert manager._drag_pending_pct == pytest.approx(100*22/42)
    np.testing.assert_allclose(manager._handles[0][1].get_offsets(), [[91., 22.]])
    manager._on_release(None)
    assert table.item(0, 1).text() == table.item(1, 0).text() == '52.4'
    manager.draw_handles(ax, 182., 42.)
    manager._on_press(SimpleNamespace(inaxes=ax, ydata=.524*42))
    manager._on_motion(SimpleNamespace(ydata=40.))
    np.testing.assert_allclose(manager._handles[0][1].get_offsets(), [[91., .74*42]])
    manager._on_release(None)
    assert table.item(0, 1).text() == table.item(1, 0).text() == '74.0'


@pytest.mark.parametrize('columns', [4, 6])
def test_zone_cell_validation_follows_actual_column_roles(win, columns):
    table = win.zone_table
    table.setColumnCount(columns)
    table.setRowCount(1)
    for col in range(columns):
        table.setItem(0, col, QTableWidgetItem('1'))
    role = Qt.ItemDataRole.UserRole + 1
    for col in range(columns - 2):
        table.item(0, col).setText('0')
        assert table.item(0, col).data(role) == 'false'
        table.item(0, col).setText('101')
        assert table.item(0, col).data(role) == 'true'
    for col in range(columns - 2, columns):
        table.item(0, col).setText('-1')
        assert table.item(0, col).data(role) == 'true'
        table.item(0, col).setText('.4')
        assert table.item(0, col).data(role) == 'false'


@pytest.mark.parametrize('direction', range(6))
def test_3d_layout_rectangles_follow_both_port_axes(direction, monkeypatch):
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    from sjtu_tpmshx.ui.layout_drawer import draw_layout_rect_3d
    from sjtu_tpmshx.domain.validator import cross_axes_for_dir
    fig = Figure()
    fig.canvas.wheelEvent = lambda event: None
    ax = fig.add_subplot(projection='3d')
    patches = []
    original = Poly3DCollection.__init__

    def capture(self, verts, *args, **kwargs):
        patches.append(np.asarray(verts[0]))
        original(self, verts, *args, **kwargs)

    monkeypatch.setattr(Poly3DCollection, '__init__', capture)
    cfg = dict(dir=direction, in_ctr=.021, in_w=.02, out_ctr=.025, out_w=.01,
               in_z_ctr=.021, in_z_w=.01, out_z_ctr=.015, out_z_w=.008)
    window = SimpleNamespace(_fluid_config=lambda side: cfg)
    draw_layout_rect_3d(window, ax, .182, .042, .042)
    normal = direction // 2
    cross = ['XYZ'.index(a) for a in cross_axes_for_dir(direction)]
    extent = [182., 42., 42.][normal]
    for end, bounds in enumerate(((11., 31., 16., 26.), (20., 30., 11., 19.))):
        vertices = patches[end]
        expected_face = extent if (direction % 2 == 1) != bool(end) else 0.
        np.testing.assert_allclose(vertices[:, normal], expected_face)
        np.testing.assert_allclose([vertices[:, cross[0]].min(), vertices[:, cross[0]].max(),
                                   vertices[:, cross[1]].min(), vertices[:, cross[1]].max()], bounds)


def test_experimental_autofill_rejects_unsupported_inlet_without_stale_preview(win, monkeypatch):
    win.combo_fluidA.setCurrentIndex(0)
    win.le_uA.setText('.001')
    win.combo_df_mode.setCurrentIndex(win.combo_df_mode.findData('cfd_smooth'))
    win._auto_fill_fluid('A')
    assert win._v_dPLA.text() != '—'
    win.combo_df_mode.setCurrentIndex(win.combo_df_mode.findData('experimental'))
    errors = []
    monkeypatch.setattr(QMessageBox, 'critical', lambda *args: errors.append(args[-1]))
    win._auto_fill_fluid('A')
    assert len(errors) == 1 and 'requires' in errors[0] and 'm/s' in errors[0]
    assert win._v_dPLA.text() == '—'


@pytest.mark.parametrize('side', ['A', 'B'])
@pytest.mark.parametrize('partial_end', ['in', 'out'])
@pytest.mark.parametrize('hidden', [False, True])
def test_real_port_reader_preserves_each_end_and_matches_preview(win, side, partial_end, hidden):
    from sjtu_tpmshx.ui.window_config import config_from_window
    win.combo_dim.setCurrentIndex(1)
    win.le_Nz.setText('20')
    for end in ('in', 'out'):
        for field, value in (('ctr', '.021'), ('w', '.008')):
            widget = getattr(win, f'le_pipe{side}_{end}_z_{field}')
            widget.setText(value if end == partial_end else '')
            widget.setHidden(hidden)
    cfg = config_from_window(win, strict=True).validate()
    bc = getattr(cfg, f'bc_{side}')
    preview = win._fluid_config(side)
    for end in ('in', 'out'):
        for field, value in (('ctr', .021), ('w', .008)):
            key = f'{end}_z_{field}'
            expected = value if end == partial_end else None
            assert getattr(bc, key) == expected
            assert preview.get(key) == expected


@pytest.mark.parametrize('side', ['A', 'B'])
@pytest.mark.parametrize('end', ['in', 'out'])
@pytest.mark.parametrize('missing', ['ctr', 'w'])
def test_real_port_reader_rejects_half_pair_and_ignores_2d_draft(win, side, end, missing):
    from sjtu_tpmshx.ui.window_config import config_from_window
    win.combo_dim.setCurrentIndex(1)
    win.le_Nz.setText('20')
    for field, value in (('ctr', '.021'), ('w', '.008')):
        getattr(win, f'le_pipe{side}_{end}_z_{field}').setText(value)
    widget = getattr(win, f'le_pipe{side}_{end}_z_{missing}')
    widget.clear()
    with pytest.raises(ValueError, match='must be set together'):
        config_from_window(win, strict=True)
    with pytest.raises(ValueError, match='must be set together'):
        win._fluid_config(side)
    win.combo_dim.setCurrentIndex(0)
    bc = getattr(config_from_window(win, strict=True), f'bc_{side}')
    assert bc.in_z_ctr is None and bc.out_z_w is None
    assert not any('_z_' in key for key in win._fluid_config(side))
    assert widget.text() == ''


@pytest.mark.parametrize('side', ['A', 'B'])
def test_3d_layout_omits_invalid_port_instead_of_drawing_full_face(win, side):
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    from sjtu_tpmshx.ui.layout_drawer import draw_layout_rect_3d
    win.combo_dim.setCurrentIndex(1)
    getattr(win, f'le_pipe{side}_out_z_ctr').setText('.021')
    getattr(win, f'le_pipe{side}_out_z_w').clear()
    fig = Figure()
    fig.canvas.wheelEvent = lambda event: None
    ax = fig.add_subplot(projection='3d')
    draw_layout_rect_3d(win, ax, .182, .042, .042)
    # Only the other fluid contributes its inlet and outlet face patches.
    assert sum(isinstance(artist, Poly3DCollection) for artist in ax.collections) == 2
    labels = [text.get_text() for text in ax.texts]
    assert f'Inlet_{side}' not in labels and f'Outlet_{side}' not in labels
    assert f'Fluid {side} skipped' in win.statusBar().currentMessage()
