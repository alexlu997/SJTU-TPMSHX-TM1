"""Per-fluid input handlers for ``Main_Menu``.

Extracted verbatim from the ``main`` god object: auto-fill of fluid
properties, temperature-unit conversion/toggle, flow-direction
change handlers, the per-side fluid-config reader, and
the layout drawers. UI-only -- no solver / numeric path. Adopted via
``class Main_Menu(..., FluidInputMixin, ..., QMainWindow)``; external
wiring resolves on the live window through the MRO.

Fluid status labels resolve their styles from the current theme at call time.
"""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from sjtu_tpmshx.models.design_fluids import nu_re_window
from sjtu_tpmshx.models.tpms_calc import compute as tpms_compute
from sjtu_tpmshx.ui.ui_constants import TOAST_MS_MED


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
            # Share the same fluid normalization used for solver inputs.
            from sjtu_tpmshx.ui.window_config import _parse_fluid_label
            _combo = getattr(self, f'combo_fluid{fluid}', None)
            _ftype = _parse_fluid_label(_combo)
            from sjtu_tpmshx.ui.window_config import sco2_nu_from_window
            r = tpms_compute(
                self.combo_tpms.currentText(),
                float(self.le_Lcell.text()), float(self.le_t.text()),
                float(le_u.text()), T_K,
                float(le_Pin.text()), float(self.le_ks.text()),
                fluid_type=_ftype, sco2_nu=sco2_nu_from_window(self))
            df_combo = getattr(self, 'combo_df_mode', None)
            if df_combo is not None and df_combo.currentData() == 'experimental':
                from sjtu_tpmshx.df_surrogate.experimental_correction import apply_correction
                u = float(le_u.text())
                K, cF, _ = apply_correction(
                    self.combo_tpms.currentText(), _ftype,
                    float(self.le_Lcell.text()), float(self.le_t.text()),
                    r['K_df'], r['cF_df'], u)
                r['dP_per_L'] = r['mu'] * u / K + r['rho'] * cF * u * u
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e)); return

        # Use the selected fluid's source range, shared with its Nu model.
        Re = r['Re']
        re_lo, re_hi = nu_re_window(_ftype)
        _re_styles = _fluid_styles()
        re_style = _re_styles['VAL']
        re_tag = ""
        if Re < re_lo:
            re_style = _re_styles['VAL_WARN']
            re_tag = f"  (< {re_lo:g}!)"
        elif Re > re_hi:
            re_style = _re_styles['VAL_WARN']
            re_tag = f"  (> {re_hi:g}!)"

        self.statusBar().showMessage(f"Fluid {fluid} filled.  Re={Re:.0f}{re_tag}  Nu={r['Nu']:.2f}  dP/L={r['dP_per_L']:.1f} Pa/m", TOAST_MS_MED)
        if fluid == 'A':
            self._v_rhoA.setText(f"{r['rho']:.4f}")
            self._v_ReA.setText(f"{Re:.1f}{re_tag}")
            self._v_ReA.setStyleSheet(re_style)
            self._v_NuA.setText(f"{r['Nu']:.4f}")
            self._v_dPLA.setText(f"{r['dP_per_L']:.1f}")
        else:
            self._v_rhoB.setText(f"{r['rho']:.4f}")
            self._v_ReB.setText(f"{Re:.1f}{re_tag}")
            self._v_ReB.setStyleSheet(re_style)
            self._v_NuB.setText(f"{r['Nu']:.4f}")
            self._v_dPLB.setText(f"{r['dP_per_L']:.1f}")
        details = getattr(self, f'_fluid_computed_{fluid}', None)
        if details is not None:
            details._set_expanded(True)

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
        """Match inlet and outlet row units to the current temperature display.

        Called after a menu toggle, preset load, or session restore.
        """
        unit_display = "°C" if getattr(self, '_temp_unit', 'K') == 'C' else "K"
        # Swap the trailing " [K]"/" [°C]" on each label. The label text uses
        # QLabel rich-text HTML so we replace both variants.
        # 2026-05-20 UI sweep: extended the label list with the result-row
        # outlet temperature labels (`_lbl_ToutA_unit`, `_lbl_ToutB_unit`)
        # captured by ui_builders. Previously these stayed `[K]` after a
        # K/°C toggle, mismatching the converted value.
        for attr in ('_lbl_TinA_unit', '_lbl_TinB_unit', '_lbl_sidebar_tout_unit'):
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

    def _toggle_temp_unit(self):
        """Flip between Kelvin and Celsius display for the inlet
        temperature fields. Converts the displayed text AND rewrites the
        label suffixes (`[K]` ↔ `[°C]`) so the UI is self-consistent.
        """
        cur = getattr(self, '_temp_unit', 'K')
        fields = [
            getattr(self, 'le_TinA', None),
            getattr(self, 'le_TinB', None),
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
        self._update_result_summary()
        from sjtu_tpmshx.ui.plot_2d_results import redraw_result_fields
        redraw_result_fields(self)
        self.statusBar().showMessage(
            f"Temperature display switched to {self._temp_unit}.", 3000)

    def _update_tout(self, t_idx: int):
        """Render this run's result scalars in the selected temperature unit."""
        self._update_result_summary()

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

    def _inlet_wall(self, d):
        from sjtu_tpmshx.domain.validator import wall_for_dir
        return wall_for_dir(d, 'inlet')

    def _outlet_wall(self, d):
        from sjtu_tpmshx.domain.validator import wall_for_dir
        return wall_for_dir(d, 'outlet')

    def _fluid_config(self, which):
        """Read a preview BC using the compute adapter's transverse pairs."""
        from sjtu_tpmshx.ui.window_config import _read_partial_bc
        cfg = dict(dir=self._dir_int(getattr(self, f'combo_dir{which}')))
        # Keep the preview's required first-axis fields strict.
        for field in ('in_ctr', 'in_w', 'out_ctr', 'out_w'):
            cfg[field] = float(getattr(self, f'le_pipe{which}_{field}').text())
        bc = _read_partial_bc(self, which, is_3d=self.combo_dim.currentIndex() == 1)
        for field in ('in_z_ctr', 'in_z_w', 'out_z_ctr', 'out_z_w'):
            value = getattr(bc, field)
            if value is not None:
                cfg[field] = value
        return cfg

    def _draw_layout(self):
        from sjtu_tpmshx.ui.layout_drawer import draw_layout
        return draw_layout(self)

    def _preview_initial_geometry(self):
        """Show the restored core envelope without opening input dialogs."""
        import math
        if getattr(self, '_active_tab', 'layout') != 'layout':
            return
        fields = [self.le_L, self.le_H]
        if self.combo_dim.currentIndex() == 1:
            fields.append(self.le_Lz)
        try:
            valid = all(math.isfinite(float(f.text())) and float(f.text()) > 0
                        for f in fields)
        except ValueError:
            valid = False
        if valid:
            self._draw_layout()
