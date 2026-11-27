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

from decimal import Decimal, InvalidOperation
import math

from PySide6.QtWidgets import QMessageBox

from sjtu_tpmshx.data_types.validator import convert_temp_decimal, temp_text_to_kelvin
from sjtu_tpmshx.applications.gui.ui.field_factory import _format_decimal_exact
from sjtu_tpmshx.physical_models.design_fluids import nu_re_window
from sjtu_tpmshx.physical_models.tpms_calc import compute as tpms_compute
from sjtu_tpmshx.applications.gui.ui.ui_constants import TOAST_MS_MED


def _fluid_styles() -> dict:
    """Resolve the Re-label stylesheets from the current theme at call
    time (the old module-global _VAL/_VAL_WARN snapshot in main.py went
    stale after a theme switch)."""
    try:
        from sjtu_tpmshx.applications.gui.ui.theme import _build_styles
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
            from sjtu_tpmshx.applications.gui.ui.window_config import (
                config_from_window, df_mode_from_window, fluid_types_from_window,
                mass_flow_active, sco2_nu_from_window,
            )
            fluid_types = fluid_types_from_window(self)
            _ftype = fluid_types[fluid]
            if mass_flow_active(self, fluid):
                from sjtu_tpmshx.preprocess.api import resolve_inlet_flow_config
                resolved = resolve_inlet_flow_config(config_from_window(self, strict=True))
                for side in 'AB':
                    if mass_flow_active(self, side):
                        getattr(self, 'le_u' + side).setText(format(getattr(resolved, 'fluid_' + side).u_mps, '.17g'))
            T_K = self._temp_to_K(le_Tin)
            r = tpms_compute(
                self.combo_tpms.currentText(),
                float(self.le_Lcell.text()), float(self.le_t.text()),
                float(le_u.text()), T_K,
                float(le_Pin.text()), float(self.le_ks.text()),
                fluid_type=_ftype, sco2_nu=sco2_nu_from_window(self),
                co2_geometry='co2' in fluid_types.values(), df_mode=df_mode_from_window(self))
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

        self.dialogs.notify(
            f"Fluid {fluid} filled.  Re={Re:.0f}{re_tag}  Nu={r['Nu']:.2f}  dP/L={r['dP_per_L']:.1f} Pa/m",
            kind="info",
            duration_ms=TOAST_MS_MED,
        )
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
        T_val = convert_temp_decimal(Decimal(str(defaults['T'])), 'K', self._temp_unit)
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
        self.dialogs.notify(
            f"流体 {side} → {name}：u={defaults['u']:.3g} m/s · "
            f"T={defaults['T']:.1f} K · P={defaults['P']:.0f} Pa",
            kind="info",
            duration_ms=4000,
        )

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
        return float(temp_text_to_kelvin(le.text(), self._temp_unit))

    def _set_temp_K(self, le, kelvin_value):
        """Write the selected temperature unit without rounding the input."""
        le.setText(_format_decimal_exact(
            convert_temp_decimal(Decimal(str(kelvin_value)), 'K', self._temp_unit)))

    def _sync_temp_unit_labels(self):
        """Match inlet and outlet row units to the current temperature display.

        Called after a menu toggle, preset load, or session restore.
        """
        unit_display = "°C" if getattr(self, '_temp_unit', 'K') == 'C' else "K"
        for field_name in ('le_TinA', 'le_TinB'):
            le = getattr(self, field_name, None)
            if le is not None and hasattr(le, 'set_unit'):
                le.set_unit(unit_display)
        for attr in ('_lbl_TinA_unit', '_lbl_TinB_unit'):
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

    def _discard_temperature_history(self):
        """Recent values are display text, so they cannot cross unit changes."""
        history = getattr(self, '_field_history', {})
        for name in ('le_TinA', 'le_TinB'):
            history.pop(name, None)

    def _toggle_temp_unit(self):
        """Flip between Kelvin and Celsius display for the inlet
        temperature fields. Converts the displayed text AND rewrites the
        label suffixes (`[K]` ↔ `[°C]`) so the UI is self-consistent.
        """
        from sjtu_tpmshx.applications.gui.ui.expr_eval import eval_expr, is_expression
        self._refresh_field_validation()
        cur = self._temp_unit
        new_unit = 'C' if cur == 'K' else 'K'
        for name in ('le_TinA', 'le_TinB'):
            field = getattr(self, name, None)
            if field is None:
                continue
            text = field.text().strip()
            try:
                value = Decimal(text)
                if not value.is_finite():
                    continue
            except InvalidOperation:
                # A rejected expression still uses its original display unit.
                expr_val = eval_expr(text) if is_expression(text) else None
                if expr_val is None or not math.isfinite(expr_val):
                    continue
                value = Decimal(str(expr_val))
            field.setText(_format_decimal_exact(convert_temp_decimal(value, cur, new_unit)))
        self._temp_unit = new_unit
        self._sync_temp_unit_labels()
        self._refresh_field_validation()
        self._discard_temperature_history()
        self.case_files.resync_undo_baseline()
        self.results.refresh_summary()
        from sjtu_tpmshx.applications.gui.ui.layout_drawer import refresh_last_2d_thumbnail
        from sjtu_tpmshx.applications.gui.ui.plot_2d_results import redraw_result_fields
        redraw_result_fields(self)
        refresh_last_2d_thumbnail(self)
        self.dialogs.notify(
            f"温度显示单位已切换为 {'°C' if self._temp_unit == 'C' else 'K'}。",
            kind="info",
            duration_ms=3000,
        )

    def _update_tout(self, t_idx: int):
        """Render this run's result scalars in the selected temperature unit."""
        self.results.refresh_summary()

    def _on_dir_changed(self):
        """Show the actual transverse axis for each port pair row under Rule A."""
        from sjtu_tpmshx.data_types.validator import cross_axes_for_dir
        for combo, prefix in [(self.combo_dirA, 'pipeA'),
                              (self.combo_dirB, 'pipeB')]:
            try:
                c1, c2 = cross_axes_for_dir(combo.currentIndex())
            except ValueError:
                c1, c2 = 'Y', 'Z'
            for end, port in (('in', '入口'), ('out', '出口')):
                for key, axis in (('', c1), ('z_', c2)):
                    row_lbl = getattr(self, f'_lbl_{prefix}_{end}_{key}row', None)
                    if row_lbl is not None:
                        row_lbl.setText(f'{port} {axis.lower()}')

    def _dir_int(self, combo):
        # 0=+x 1=-x 2=+y 3=-y 4=+z 5=-z (z-dirs: 3D only)
        return combo.currentIndex()

    def _inlet_wall(self, d):
        from sjtu_tpmshx.data_types.validator import wall_for_dir
        return wall_for_dir(d, 'inlet')

    def _outlet_wall(self, d):
        from sjtu_tpmshx.data_types.validator import wall_for_dir
        return wall_for_dir(d, 'outlet')

    def _fluid_config(self, which):
        """Read a preview BC using the compute adapter's transverse pairs."""
        from sjtu_tpmshx.applications.gui.ui.window_config import _read_partial_bc
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
        from sjtu_tpmshx.applications.gui.ui.layout_drawer import draw_layout
        return draw_layout(self)

    def _preview_initial_geometry(self):
        """Show the restored core envelope without opening input dialogs."""
        import math
        if self.workbench.active_tab != 'layout' or self.page_stack.currentWidget() is self.quick_design:
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
