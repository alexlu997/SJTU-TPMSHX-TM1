"""Per-fluid input handlers for ``Main_Menu``.

Extracted verbatim from the ``main`` god object: auto-fill of fluid
properties, temperature-unit conversion/toggle, flow-direction & shape
change handlers, edge-combo sync, the per-side fluid-config reader, and
the layout drawers. UI-only -- no solver / numeric path. Adopted via
``class Main_Menu(..., FluidInputMixin, ..., QMainWindow)``; external
wiring resolves on the live window through the MRO.

_auto_fill_fluid originally read the module-level _VAL / _VAL_WARN style
globals from main.py; those went stale after a theme switch. It now
resolves them at call time via _fluid_styles(), so the Re label respects
a live ThemeManager.rebuild(). Behaviour-identical at first paint.
"""

from __future__ import annotations

import numpy as np

from PySide6.QtWidgets import QMessageBox

from sjtu_tpmshx.models.tpms_calc import compute as tpms_compute
from sjtu_tpmshx.ui.ui_constants import RE_NU_LO, RE_NU_HI, TOAST_MS_MED


def _fluid_styles() -> dict:
    """Resolve the Re-label stylesheets from the current theme at call
    time (the old module-global _VAL/_VAL_WARN snapshot in main.py went
    stale after a theme switch)."""
    try:
        from sjtu_tpmshx.ui.theme import _build_styles
        s = _build_styles()
        return {'VAL': s.get('VAL', ''), 'VAL_WARN': s.get('VAL_WARN', '')}
    except Exception:
        return {'VAL': '', 'VAL_WARN': ''}


class FluidInputMixin:
    """Fluid auto-fill, temp-unit, direction/shape, layout-draw handlers."""

    def _auto_fill_fluid(self, fluid: str):
        if not self.compute_tpms():
            return
        le_u, le_Tin, le_Pin = {
            'A': (self.le_uA, self.le_TinA, self.le_PinA),
            'B': (self.le_uB, self.le_TinB, self.le_PinB),
        }[fluid]
        try:
            T_K = self._temp_to_K(le_Tin)
            # 2026-05-09 (option B) — route per-side fluid type through to
            # tpms_compute so water side picks up water properties + the
            # Pr-substitution Nu correlation. Falls back to 'air' if combo
            # not present (legacy compute path).
            from sjtu_tpmshx.models.tpms_calc import parse_fluid_type
            _combo = getattr(self, f'combo_fluid{fluid}', None)
            _ftype = parse_fluid_type(_combo) if _combo is not None else 'air'
            from sjtu_tpmshx.ui.window_config import sco2_nu_from_window
            r = tpms_compute(
                self.combo_tpms.currentText(),
                float(self.le_Lcell.text()), float(self.le_t.text()),
                float(le_u.text()), T_K,
                float(le_Pin.text()), float(self.le_ks.text()),
                fluid_type=_ftype, sco2_nu=sco2_nu_from_window(self))
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e)); return

        # Convert face HTC [W/(m2K)] to volumetric HTC [W/(m3K)] —
        # delegated to domain.compute_volumetric_htc (Phase 4 #4).
        from sjtu_tpmshx.domain.validator import compute_volumetric_htc
        h_v_vol = compute_volumetric_htc(r['A_0'], r['H_sf'])

        # Re range check against Nu v4.1 calibration window.
        Re = r['Re']
        _re_styles = _fluid_styles()
        re_style = _re_styles['VAL']
        re_tag = ""
        if Re < RE_NU_LO:
            re_style = _re_styles['VAL_WARN']
            re_tag = f"  (< {RE_NU_LO}!)"
        elif Re > RE_NU_HI:
            re_style = _re_styles['VAL_WARN']
            re_tag = f"  (> {RE_NU_HI}!)"

        self.statusBar().showMessage(f"Fluid {fluid} filled.  Re={Re:.0f}{re_tag}  Nu={r['Nu']:.2f}  dP/L={r['dP_per_L']:.1f} Pa/m", TOAST_MS_MED)
        if fluid == 'A':
            self._mu_A, self._h_vA, self._K_ffA, self._rho_A = r['mu'], h_v_vol, r['K_ff'], r['rho']
            self._v_rhoA.setText(f"{r['rho']:.4f}")
            self._v_ReA.setText(f"{Re:.1f}{re_tag}")
            self._v_ReA.setStyleSheet(re_style)
            self._v_NuA.setText(f"{r['Nu']:.4f}")
            self._v_dPLA.setText(f"{r['dP_per_L']:.1f}")
        else:
            self._mu_B, self._h_vB, self._K_ffB, self._rho_B = r['mu'], h_v_vol, r['K_ff'], r['rho']
            self._v_rhoB.setText(f"{r['rho']:.4f}")
            self._v_ReB.setText(f"{Re:.1f}{re_tag}")
            self._v_ReB.setStyleSheet(re_style)
            self._v_NuB.setText(f"{r['Nu']:.4f}")
            self._v_dPLB.setText(f"{r['dP_per_L']:.1f}")

    def auto_fill_fluid_a(self): self._auto_fill_fluid('A')

    def auto_fill_fluid_b(self): self._auto_fill_fluid('B')

    def _apply_fluid_defaults(self, side):
        """Push typical u / T / P defaults into the given side's inputs when
        the fluid-type combo changes. `side` is 'A' or 'B'."""
        if side not in ('A', 'B'):
            return
        combo = getattr(self, f'combo_fluid{side}', None)
        if combo is None:
            return
        name = combo.currentText().strip()
        defaults = self._FLUID_DEFAULTS.get(name)
        if defaults is None:
            return
        # Honour the current temperature display unit.
        T_val = defaults['T']
        if getattr(self, '_temp_unit', 'K') == 'C':
            T_val = T_val - 273.15
        targets = (
            (f'le_u{side}',  f"{defaults['u']:.3g}"),
            (f'le_Tin{side}', f"{T_val:.2f}"),
            (f'le_Pin{side}', f"{defaults['P']:.0f}"),
        )
        for attr, txt in targets:
            le = getattr(self, attr, None)
            if le is None:
                continue
            try:
                le.setText(txt)
                # Tier 25: keep the undo baseline in step with this
                # programmatic write (fluid-type combo change). These
                # fields are not the ones that re-fire fluid defaults
                # (that's the combo), so refreshing the baseline here is
                # safe and prevents a later manual edit's Ctrl+Z jumping
                # back across the auto-applied defaults to a stale value.
                ul = getattr(self, '_undo_last', None)
                if ul is not None:
                    ul[attr] = txt
            except Exception:
                continue
        self.statusBar().showMessage(
            f"Fluid {side} → {name}: applied u={defaults['u']:.3g} m/s · "
            f"T={defaults['T']:.1f} K · P={defaults['P']:.0f} Pa.", 5000)

    def _wire_fluid_defaults(self):
        for side in ('A', 'B'):
            combo = getattr(self, f'combo_fluid{side}', None)
            if combo is None:
                continue
            combo.currentIndexChanged.connect(
                lambda _i, s=side: self._apply_fluid_defaults(s))

    def _temp_to_K(self, le):
        """Return the float value of a temperature QLineEdit in Kelvin,
        honouring the current `_temp_unit` flag. Callers anywhere in the
        compute path should go through this rather than `float(le.text())`
        so the K/°C toggle stays sound.
        """
        v = float(le.text())
        if getattr(self, '_temp_unit', 'K') == 'C':
            v += 273.15
        return v

    def _set_temp_K(self, le, kelvin_value, fmt='{:.2f}'):
        """Write a Kelvin temperature into a QLineEdit, converting to the
        currently displayed unit. Single source of truth — replaces ad-hoc
        `setText(f"{val - 273.15:.2f}")` snippets in preset-load and
        session-restore that previously had drift potential (one would
        subtract, another would add, depending on _temp_unit timing).
        """
        if le is None or kelvin_value is None or kelvin_value == '':
            return
        try:
            v = float(kelvin_value)
        except (TypeError, ValueError):
            return
        if getattr(self, '_temp_unit', 'K') == 'C':
            v -= 273.15
        try:
            le.setText(fmt.format(v))
        except Exception:
            pass

    def _sync_temp_unit_labels(self):
        """Refresh the `[K]`/`[°C]` suffix on the three temperature row
        labels (T_inA, T_inB) + the header button caption to
        match `self._temp_unit`. Call whenever the unit changes, whether via
        the toggle button, preset load, or session restore — prevents the
        value-vs-label mismatch the user reported."""
        unit_display = "°C" if getattr(self, '_temp_unit', 'K') == 'C' else "K"
        # Swap the trailing " [K]"/" [°C]" on each label. The label text uses
        # QLabel rich-text HTML so we replace both variants.
        # 2026-05-20 UI sweep: extended the label list with the result-row
        # outlet temperature labels (`_lbl_ToutA_unit`, `_lbl_ToutB_unit`)
        # captured by ui_builders. Previously these stayed `[K]` after a
        # K/°C toggle, mismatching the converted value.
        for attr in ('_lbl_TinA_unit', '_lbl_TinB_unit', '_lbl_TsInit_unit',
                     '_lbl_ToutA_unit', '_lbl_ToutB_unit'):
            lbl = getattr(self, attr, None)
            if lbl is None:
                continue
            try:
                txt = lbl.text()
                txt = (txt.replace("[K]", f"[{unit_display}]")
                          .replace("[°C]", f"[{unit_display}]"))
                lbl.setText(txt)
            except Exception:
                pass
        if hasattr(self, 'btn_temp_unit'):
            self.btn_temp_unit.setText(unit_display)
            self.btn_temp_unit.setToolTip(
                f"Temperatures currently in {unit_display}. Click to switch.")

    def _toggle_temp_unit(self):
        """Flip between Kelvin and Celsius display for the three main
        temperature fields. Converts the displayed text AND rewrites the
        label suffixes (`[K]` ↔ `[°C]`) so the UI is self-consistent.
        """
        cur = getattr(self, '_temp_unit', 'K')
        fields = [
            getattr(self, 'le_TinA', None),
            getattr(self, 'le_TinB', None),
            getattr(self, 'le_TsInit', None),
        ]
        def _fmt(v):
            return f"{v:.2f}"
        if cur == 'K':
            # K → °C
            for le in fields:
                if le is None:
                    continue
                try:
                    v = float(le.text())
                    le.setText(_fmt(v - 273.15))
                except Exception:
                    pass
            self._temp_unit = 'C'
        else:
            # °C → K
            for le in fields:
                if le is None:
                    continue
                try:
                    v = float(le.text())
                    le.setText(_fmt(v + 273.15))
                except Exception:
                    pass
            self._temp_unit = 'K'
        self._sync_temp_unit_labels()
        # 2026-05-20 UI sweep: re-render the cached outlet temperature
        # results in the new unit so the result-row value follows the
        # label suffix instead of staying as raw Kelvin from the last
        # solve.
        _tout_cache = getattr(self, '_tout_K_cache', None)
        if _tout_cache is not None:
            try:
                ta_K, tb_K = _tout_cache
                self._set_temp_K(self._r_ToutA, ta_K)
                self._set_temp_K(self._r_ToutB, tb_K)
            except Exception:
                pass
        self.statusBar().showMessage(
            f"Temperature display switched to {self._temp_unit}.", 3000)

    def _update_tout(self, t_idx: int):
        """Render this run's result scalars in the selected temperature unit."""
        cached = getattr(self, '_tout_K_cache', None)
        if cached is not None:
            self._set_temp_K(self._r_ToutA, cached[0])
            self._set_temp_K(self._r_ToutB, cached[1])

    def _on_shape_changed(self, idx):
        """Show/hide controls based on domain shape (Rectangle vs Polygon)."""
        is_poly = idx > 0
        # Show polygon pipe edge config
        self._poly_pipe_frame.setVisible(is_poly)
        self._poly_pipe_label.setVisible(is_poly)
        # Hide rect-only controls
        for w in self._rect_only_widgets:
            w.setVisible(not is_poly)
        # Show polygon-only controls
        for w in self._poly_only_widgets:
            w.setVisible(is_poly)
        if is_poly:
            self._update_edge_combos()

    def _on_dir_changed(self):
        """Relabel inlet/outlet fields to match selected flow-axis.

        dir 0/1 (±x) stream → cross1 = Y, cross2 = Z
        dir 2/3 (±y) stream → cross1 = X, cross2 = Z
        dir 4/5 (±z) stream → cross1 = X, cross2 = Y
        The UI fields `in_ctr/in_w/out_ctr/out_w` always control cross1;
        `in_z_ctr` etc. always control cross2 — labels show the real axis
        so user knows which coord they're editing.
        """
        # Cross-axis labels delegated to domain.validator (Phase 4 #4).
        from sjtu_tpmshx.domain.validator import cross_axes_for_dir
        for combo, prefix in [(self.combo_dirA, 'pipeA'),
                              (self.combo_dirB, 'pipeB')]:
            try:
                c1, c2 = cross_axes_for_dir(combo.currentIndex())
            except ValueError:
                c1, c2 = 'Y', 'Z'
            for io, cap in (('in', 'Inlet'), ('out', 'Outlet')):
                for kind, suffix in (('ctr', 'centre'), ('w', 'width')):
                    lbl1 = getattr(self, f'_lbl_{prefix}_{io}_{kind}', None)
                    if lbl1 is not None:
                        lbl1.setText(f"{cap} {c1}-{suffix} [m]")
                    lbl2 = getattr(self, f'_lbl_{prefix}_{io}_z_{kind}', None)
                    if lbl2 is not None:
                        lbl2.setText(f"{cap} {c2}-{suffix} [m] (3D)")

    def _dir_int(self, combo):
        # 0=+x 1=-x 2=+y 3=-y 4=+z 5=-z (z-dirs: 3D only)
        return combo.currentIndex()

    def _is_x_dir(self, d): return d in (0, 1)

    def _inlet_wall(self, d):
        from sjtu_tpmshx.domain.validator import wall_for_dir
        return wall_for_dir(d, 'inlet')

    def _outlet_wall(self, d):
        from sjtu_tpmshx.domain.validator import wall_for_dir
        return wall_for_dir(d, 'outlet')

    def _fluid_config(self, which):
        """Read config for fluid A or B. Returns dict (optional z-partial keys
        for fluid A: `in_z_ctr`, `in_z_w`, `out_z_ctr`, `out_z_w`)."""
        if which == 'A':
            d = self._dir_int(self.combo_dirA)
            cfg = dict(dir=d,
                in_ctr=float(self.le_pipeA_in_ctr.text()),
                in_w=float(self.le_pipeA_in_w.text()),
                out_ctr=float(self.le_pipeA_out_ctr.text()),
                out_w=float(self.le_pipeA_out_w.text()))
            # z-partial (only when 3D mode shows the fields)
            if (hasattr(self, 'le_pipeA_in_z_ctr')
                    and not self.le_pipeA_in_z_ctr.isHidden()):
                try:
                    cfg['in_z_ctr']  = float(self.le_pipeA_in_z_ctr.text())
                    cfg['in_z_w']    = float(self.le_pipeA_in_z_w.text())
                    cfg['out_z_ctr'] = float(self.le_pipeA_out_z_ctr.text())
                    cfg['out_z_w']   = float(self.le_pipeA_out_z_w.text())
                except ValueError:
                    pass
            return cfg
        else:
            d = self._dir_int(self.combo_dirB)
            cfg = dict(dir=d,
                in_ctr=float(self.le_pipeB_in_ctr.text()),
                in_w=float(self.le_pipeB_in_w.text()),
                out_ctr=float(self.le_pipeB_out_ctr.text()),
                out_w=float(self.le_pipeB_out_w.text()))
            # z-partial (only when 3D mode shows the fields)
            if (hasattr(self, 'le_pipeB_in_z_ctr')
                    and not self.le_pipeB_in_z_ctr.isHidden()):
                try:
                    cfg['in_z_ctr']  = float(self.le_pipeB_in_z_ctr.text())
                    cfg['in_z_w']    = float(self.le_pipeB_in_z_w.text())
                    cfg['out_z_ctr'] = float(self.le_pipeB_out_z_ctr.text())
                    cfg['out_z_w']   = float(self.le_pipeB_out_z_w.text())
                except ValueError:
                    pass
            return cfg

    def _update_edge_combos(self):
        """Populate edge combo boxes with readable edge descriptions."""
        from sjtu_tpmshx.solvers import unstructured_mesh as um
        try:
            L = float(self.le_L.text())
            H = float(self.le_H.text())
        except ValueError:
            return
        shape = self.combo_shape.currentText()
        if shape == 'Hexagon':
            verts = um.hexagon(L, H)
        elif shape == 'Octagon':
            verts = um.octagon(L, H)
        else:
            return
        n_v = len(verts)
        cx, cy = verts[:, 0].mean(), verts[:, 1].mean()

        items = []
        for i in range(n_v):
            p0, p1 = verts[i], verts[(i + 1) % n_v]
            mid = 0.5 * (p0 + p1)
            # Descriptive direction label
            dx, dy = mid[0] - cx, mid[1] - cy
            if abs(dx) > abs(dy):
                side = "Right" if dx > 0 else "Left"
            else:
                side = "Top" if dy > 0 else "Bottom"
            edge = p1 - p0
            elen = np.linalg.norm(edge) * 1000
            items.append(f"E{i}: {side} ({elen:.1f} mm)")

        for cb in (self.combo_edge_inA, self.combo_edge_outA,
                   self.combo_edge_inB, self.combo_edge_outB):
            cb.blockSignals(True)
            cb.clear()
            cb.addItems(items)
            cb.blockSignals(False)
        # Defaults: A left->right, B bottom->top
        if shape == 'Octagon' and n_v == 8:
            self.combo_edge_inA.setCurrentIndex(6)
            self.combo_edge_outA.setCurrentIndex(2)
            self.combo_edge_inB.setCurrentIndex(0)
            self.combo_edge_outB.setCurrentIndex(4)
        elif shape == 'Hexagon' and n_v == 6:
            self.combo_edge_inA.setCurrentIndex(5)
            self.combo_edge_outA.setCurrentIndex(2)
            self.combo_edge_inB.setCurrentIndex(0)
            self.combo_edge_outB.setCurrentIndex(3)

    def _draw_layout(self):
        from sjtu_tpmshx.ui.layout_drawer import draw_layout
        return draw_layout(self)

    def _draw_layout_rect(self, ax, L, H, Lmm, Hmm):
        from sjtu_tpmshx.ui.layout_drawer import draw_layout_rect
        return draw_layout_rect(self, ax, L, H, Lmm, Hmm)

    def _draw_layout_polygon(self, ax, L, H, Lmm, Hmm):
        from sjtu_tpmshx.ui.layout_drawer import draw_layout_polygon
        return draw_layout_polygon(self, ax, L, H, Lmm, Hmm)
