#include "enthalpy_c_views.hpp"

extern "C" int TPMSHX_THERMAL_CALL tpmshx_full_enthalpy_defaults_v1(
    uint32_t dimension,uint32_t algorithm,uint32_t has_water,tpmshx_energy_effective_settings_v1* out) {
    if ((dimension != 2 && dimension != 3) || algorithm != TPMSHX_ENERGY_TEMPERATURE_SOU
        || has_water > 1 || !out) return 1;
    *out = tpmshx::energy_settings_c_view(tpmshx::full_enthalpy_control(
        dimension,static_cast<tpmshx::EnthalpyAlgorithm>(algorithm),has_water != 0),false);
    return 0;
}

extern "C" uint32_t TPMSHX_THERMAL_CALL tpmshx_energy_algorithm_version_v1(uint32_t algorithm) {
    switch (algorithm) {
    case TPMSHX_ENERGY_TEMPERATURE_SOU:
        return 2;
    default:
        return 0;
    }
}
