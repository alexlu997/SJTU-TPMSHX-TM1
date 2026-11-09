"""Small widget stand-ins shared by window configuration tests."""


class _StubLineEdit:
    """Tiny stand-in for QLineEdit that returns a fixed text value."""

    def __init__(self, text: str, hidden: bool = False):
        self._text = text
        self._hidden = hidden

    def text(self) -> str:
        return self._text

    def isHidden(self) -> bool:
        return self._hidden


class _StubComboBox:
    def __init__(self, text: str, index: int = 0):
        self._text = text
        self._index = index

    def currentText(self) -> str:
        return self._text

    def currentIndex(self) -> int:
        return self._index


class _StubCheckBox:
    def __init__(self, checked: bool = False):
        self._checked = checked

    def isChecked(self) -> bool:
        return self._checked


class _StubWindow:
    """Build only the attributes that ``config_from_window`` reads."""

    def __init__(self, **fields):
        # geometry
        self.combo_tpms = _StubComboBox(fields.get('tpms', 'Diamond'))
        self.le_Lcell = _StubLineEdit(fields.get('Lcell', '8.0'))
        self.le_t = _StubLineEdit(fields.get('t', '0.5'))
        self.le_ks = _StubLineEdit(fields.get('ks', '20.0'))
        self.le_L = _StubLineEdit(fields.get('L', '0.20'))
        self.le_H = _StubLineEdit(fields.get('H', '0.05'))
        # le_Lz defaults to a numeric value so strict mode passes for
        # 3D runs unless the test explicitly drops it.
        self.le_Lz = _StubLineEdit(fields.get('Lz', '0.05'))
        # solver
        self.le_Nx = _StubLineEdit(fields.get('Nx', '40'))
        self.le_Ny = _StubLineEdit(fields.get('Ny', '80'))
        self.le_Nz = _StubLineEdit(fields.get('Nz', '5'))
        # fluids
        self.combo_fluidA = _StubComboBox(fields.get('fluidA', 'Air'))
        if 'fluidB' in fields:
            self.combo_fluidB = _StubComboBox(fields['fluidB'])
        self.le_uA = _StubLineEdit(fields.get('uA', '10.0'))
        self.le_uB = _StubLineEdit(fields.get('uB', '2.0'))
        self.le_TinA = _StubLineEdit(fields.get('TinA', '400.0'))
        self.le_TinB = _StubLineEdit(fields.get('TinB', '300.0'))
        self.le_PinA = _StubLineEdit(fields.get('PinA', '200000.0'))
        self.le_PinB = _StubLineEdit(fields.get('PinB', '101325.0'))
