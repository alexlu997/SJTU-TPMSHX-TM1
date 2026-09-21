#ifndef TPMSHX_THERMAL_C_API_H
#define TPMSHX_THERMAL_C_API_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define TPMSHX_THERMAL_ABI_VERSION 1u

uint32_t tpmshx_thermal_abi_version(void);

/* Borrowed arrays; the caller retains valid storage throughout the call.
 * shape has 3 size_t entries (nx, ny, nz), sizes has 23 element counts,
 * arrays has 23 pointers to contiguous doubles in C order:
 *   0..2: dx, dy, dz; 3..5: mutable h_A, h_B, T_s;
 *   6..13: A's dh, cp, T_star, h_star, hv, mass_x, mass_y, mass_z;
 *   14..21: the same eight fields for B; 22: K_ss.
 * scalars has 7 doubles: h_in_A, h_in_B, h_lo_A, h_hi_A, h_lo_B,
 * h_hi_B, omega. clips points to 2 uint64_t outputs, written only on success.
 * Array layouts and nonaliasing requirements are those of enthalpy_sweeps.hpp.
 * The caller must supply all fixed-size argument tables and their storage;
 * this boundary cannot detect a pointer to an undersized argument table.
 * clips and error must not overlap the argument tables or array storage.
 *
 * error must point to at least error_capacity bytes, with capacity > 0.
 * Success clears error[0]. Failure copies the exception's original message,
 * truncated if necessary and NUL terminated whenever the buffer is valid.
 * Status: 0 success, 1 invalid argument, 2 arithmetic domain error,
 * 3 other native exception. Status 1 rejects input before state updates;
 * after statuses 2 or 3 the state may be partially updated and is unusable.
 * No exception is allowed to cross the C boundary.
 */
int tpmshx_enthalpy_sweeps_v1(const size_t* shape, double* const* arrays,
                            const size_t* sizes, const double* scalars,
                            size_t sweeps, uint64_t* clips,
                            char* error, size_t error_capacity);

#ifdef __cplusplus
}
#endif

#endif
