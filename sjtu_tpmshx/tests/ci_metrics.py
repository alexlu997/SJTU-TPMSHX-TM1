"""Session-end diagnostics only: no imports of models or additional compilation."""
import os
import sys


def collect_process_metrics():
    """Return this pytest process's lifetime peak and loaded dispatcher counters."""
    if sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD),
                        ('PeakWorkingSetSize', ctypes.c_size_t),
                        ('WorkingSetSize', ctypes.c_size_t),
                        ('QuotaPeakPagedPoolUsage', ctypes.c_size_t),
                        ('QuotaPagedPoolUsage', ctypes.c_size_t),
                        ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t),
                        ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                        ('PagefileUsage', ctypes.c_size_t),
                        ('PeakPagefileUsage', ctypes.c_size_t)]

        current = ctypes.WinDLL('kernel32', use_last_error=True).GetCurrentProcess
        current.restype = wintypes.HANDLE
        query = ctypes.WinDLL('psapi', use_last_error=True).GetProcessMemoryInfo
        query.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessMemoryCounters), wintypes.DWORD]
        query.restype = wintypes.BOOL
        memory = ProcessMemoryCounters()
        memory.cb = ctypes.sizeof(memory)
        if not query(current(), ctypes.byref(memory), memory.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        peak = int(memory.PeakWorkingSetSize)
        source = 'GetProcessMemoryInfo.PeakWorkingSetSize (bytes)'
    else:
        import resource

        peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        if sys.platform != 'darwin':
            peak *= 1024  # Linux ru_maxrss is KiB; macOS is already bytes.
        source = 'resource.getrusage(RUSAGE_SELF).ru_maxrss'
    dispatcher_type = getattr(sys.modules.get('numba.core.registry'), 'CPUDispatcher', None)
    dispatchers = {}
    if dispatcher_type is not None:
        for name, module in tuple(sys.modules.items()):
            if module is not None and name.startswith('sjtu_tpmshx.'):
                for value in tuple(vars(module).values()):
                    if isinstance(value, dispatcher_type):
                        dispatchers[id(value)] = value
    return dict(pid=os.getpid(), peak_rss_bytes=peak, peak_rss_source=source,
                peak_rss_scope='self process lifetime peak; excludes children; not additive across processes',
                numba_dispatchers=len(dispatchers),
                numba_cache_hits=sum(sum(d.stats.cache_hits.values()) for d in dispatchers.values()),
                numba_cache_misses=sum(sum(d.stats.cache_misses.values()) for d in dispatchers.values()))
