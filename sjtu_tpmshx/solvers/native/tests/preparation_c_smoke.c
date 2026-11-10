#include "tpmshx/preparation_c_api.h"
#include "tpmshx/preparation_flow_c_api.h"
#include "tpmshx/property_c_api.h"
#include <math.h>
#include <string.h>

static int properties(void) {
    const double temperature = 300., pressure = 101325.;
    const double liquid_pressure = 200000., co2_temperature = 330., co2_pressure = 8000000.;
    tpmshx_property_input_v1 t = {&temperature, 1, {0., 64, 0}, 0};
    tpmshx_property_input_v1 p = {&pressure, 1, {0., 64, 0}, 0};
    double value = -123., imaginary = -456., bundle[5], inverse = 0.;
    tpmshx_grid_scalar_v1 kind = {0., 32, 1};
    uint32_t category = 99, events[TPMSHX_PROPERTY_EVENT_COUNT];
    tpmshx_property_output_v1 result = {&value, &imaginary, 1, &kind, &category,
                                      events, TPMSHX_PROPERTY_EVENT_COUNT};
    tpmshx_property_failure_v1 failure;
    char version[128], revision[128], error[2048];
    if (tpmshx_preparation_property_backend_v1(version, sizeof(version), revision, sizeof(revision),
            error, sizeof(error)) || !version[0] || !revision[0] || error[0]) return 10;
    if (tpmshx_preparation_empirical_v1(2, t, p, result, &failure, error, sizeof(error))) return 11;
    if (value != pressure*.028966/(8.314*temperature) || imaginary != 0. || category || kind.precision != 64) return 12;
    value = -123.; imaginary = -456.; kind.precision = 32; category = 99;
    memset(events, 0x55, sizeof(events));
    if (tpmshx_preparation_empirical_v1(99, t, p, result, &failure, error, sizeof(error))
            != TPMSHX_PREPARATION_INVALID) return 13;
    if (value != -123. || imaginary != -456. || kind.precision != 32 || category != 99) return 14;
    {
        size_t index;
        for (index = 0; index < TPMSHX_PROPERTY_EVENT_COUNT; ++index)
            if (events[index] != 0x55555555u) return 15;
    }
    if (tpmshx_preparation_water_pt_v1(&temperature, &liquid_pressure, 1, &failure,
                                     error, sizeof(error))) return 16;
    if (tpmshx_preparation_co2_scalar_bundle_v1(co2_temperature, co2_pressure, bundle, 5,
                                             &failure, error, sizeof(error))) return 17;
    {
        size_t index;
        for (index = 0; index < 5; ++index) if (!isfinite(bundle[index])) return 18;
        for (index = 0; index < 4; ++index) if (bundle[index] <= 0.) return 19;
    }
    if (tpmshx_preparation_sco2_hp_scalar_v1(bundle[4], co2_pressure, &inverse, 1,
                                          &failure, error, sizeof(error))) return 20;
    if (fabs(inverse-co2_temperature) > 2e-8) return 21;
    return 0;
}

int main(void) {
    const double epsilon[] = {.5}, opening[] = {1.}, widths[] = {4.};
    tpmshx_preparation_flow_values_v1 eps = {epsilon, 1, 64, 1};
    tpmshx_preparation_flow_values_v1 op = {opening, 1, 64, 1};
    tpmshx_preparation_flow_values_v1 dx = {widths, 1, 64, 1};
    tpmshx_grid_scalar_v1 density = {2., 64, 0}, depth = {.5, 64, 0};
    tpmshx_grid_scalar_v1 result = {-123., 32, 1}, before;
    char error[256];
    if (tpmshx_preparation_abi_version_v1() != TPMSHX_PREPARATION_ABI_VERSION) return 1;
    if (tpmshx_preparation_inlet_capacity_2d_v1(eps, op, op, dx, density, depth,
            &result, 1, error, sizeof(error)) != TPMSHX_PREPARATION_OK) return 2;
    if (result.value != 1. || error[0]) return 3;
    before = result;
    if (tpmshx_preparation_inlet_capacity_2d_v1(eps, op, op, dx, density, depth,
            &result, 0, error, sizeof(error)) != TPMSHX_PREPARATION_INVALID) return 4;
    if (memcmp(&before, &result, sizeof(result)) || !error[0]) return 5;
    return properties();
}
