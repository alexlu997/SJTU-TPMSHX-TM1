"""Common C layout for a Darcy-Forchheimer field summary."""
import ctypes as ct


class DragSummary(ct.Structure):
    _fields_ = [('minimum', ct.c_double), ('maximum', ct.c_double), ('scalar', ct.c_uint32)]
