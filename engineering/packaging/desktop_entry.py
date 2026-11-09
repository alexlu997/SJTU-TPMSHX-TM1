"""Standalone bootloader target; source users run sjtu_tpmshx.desktop."""
from sjtu_tpmshx.desktop import main

if __name__ == '__main__':
    raise SystemExit(main())
