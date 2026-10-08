#include "tpmshx/enthalpy_driver_c_api.h"

extern "C" uint32_t TPMSHX_THERMAL_CALL tpmshx_energy_algorithm_version_v1(uint32_t algorithm) {
    switch (algorithm) {
    case TPMSHX_ENERGY_TEMPERATURE_FOU:
        return 1;
    case TPMSHX_ENERGY_TEMPERATURE_SOU:
        return 2;
    default:
        return 0;
    }
}
