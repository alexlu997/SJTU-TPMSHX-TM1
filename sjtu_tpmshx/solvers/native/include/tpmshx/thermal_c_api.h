#ifndef TPMSHX_THERMAL_C_API_H
#define TPMSHX_THERMAL_C_API_H

#include <stddef.h>
#include <stdint.h>

/* Define BUILD_SHARED when producing the DLL, USE_SHARED when consuming it.
 * Leave both undefined for static linkage. The C ABI uses cdecl on Windows.
 */
#if defined(_WIN32)
#  if defined(TPMSHX_THERMAL_BUILD_SHARED)
#    define TPMSHX_THERMAL_API __declspec(dllexport)
#  elif defined(TPMSHX_THERMAL_USE_SHARED)
#    define TPMSHX_THERMAL_API __declspec(dllimport)
#  else
#    define TPMSHX_THERMAL_API
#  endif
#  define TPMSHX_THERMAL_CALL __cdecl
#else
#  define TPMSHX_THERMAL_API
#  define TPMSHX_THERMAL_CALL
#endif

#endif
