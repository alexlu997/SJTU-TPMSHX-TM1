/* This C-only caller links against both the static library and the shared ABI. */
#include "tpmshx/thermal_c_api.h"

#include <math.h>
#include <stdio.h>
#include <string.h>

int main(void) {
    const size_t shape[3] = {1, 1, 1};
    double storage[23][2] = {{0.0}};
    double* arrays[23];
    size_t sizes[23];
    double scalars[7] = {400000.0, 300000.0, 0.0, 500000.0, 0.0, 500000.0, 1.0};
    uint64_t clips[2] = {99, 99};
    char error[128] = "old error";
    size_t i;
    for (i = 0; i < 23; ++i) {
        arrays[i] = storage[i];
        sizes[i] = (i >= 11 && i <= 13) || (i >= 19 && i <= 21) ? 2 : 1;
    }
    storage[0][0] = storage[1][0] = storage[2][0] = 0.01;
    storage[3][0] = 350000.0;
    storage[4][0] = 280000.0;
    storage[5][0] = 340.0;
    storage[7][0] = storage[15][0] = 1000.0;
    storage[8][0] = 400.0;
    storage[9][0] = 400000.0;
    storage[16][0] = 300.0;
    storage[17][0] = 300000.0;
    storage[11][0] = storage[11][1] = 0.01;
    storage[19][0] = storage[19][1] = 0.01;

    if (tpmshx_thermal_abi_version() != TPMSHX_THERMAL_ABI_VERSION) return 1;
    if (tpmshx_enthalpy_sweeps_v1(shape, arrays, sizes, scalars, 1, clips,
                                 error, sizeof(error)) != 0) return 2;
    if (error[0] || clips[0] || clips[1]) return 3;
    if (fabs(storage[3][0] - 400000.0) > 1e-8 ||
        fabs(storage[4][0] - 300000.0) > 1e-8 || storage[5][0] != 340.0) return 4;

    scalars[6] = 2.0;
    clips[0] = clips[1] = 99;
    if (tpmshx_enthalpy_sweeps_v1(shape, arrays, sizes, scalars, 1, clips,
                                 error, sizeof(error)) != 1) return 5;
    if (strcmp(error, "omega must be in (0, 1]") || clips[0] != 99 || clips[1] != 99)
        return 6;
    if (fabs(storage[3][0] - 400000.0) > 1e-8 ||
        fabs(storage[4][0] - 300000.0) > 1e-8 || storage[5][0] != 340.0) return 7;
    puts("C ABI: transport and invalid-input semantics passed");
    return 0;
}
