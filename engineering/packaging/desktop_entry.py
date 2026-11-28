"""Standalone bootloader target; source users run tm1.desktop."""
from tm1.desktop import main

if __name__ == '__main__':
    raise SystemExit(main())
