#include <tpmshx/result_stage_c_api.h>
#include <tpmshx/result_checks_c_api.h>
#include <cstring>

#include <iostream>

int main() {
    if (tpmshx_result_abi_version_v1() != TPMSHX_RESULT_ABI_VERSION) return 1;
    const double values[] = {1., 2.};
    const std::size_t shape[] = {2};
    const std::ptrdiff_t strides[] = {sizeof(double)};
    const tpmshx_result_array_v1 input{values, sizeof(values), 0, TPMSHX_RESULT_F64,
        TPMSHX_RESULT_NUMPY_ARRAY, TPMSHX_RESULT_NATIVE_ENDIAN, 0, 1, shape, strides};
    tpmshx_result_array_check_values_v1 checks{};
    tpmshx_result_diagnostics_v1 diagnostics{};
    char error[256]{};
    if (tpmshx_result_array_checks_v1(input, &checks, &diagnostics, error, sizeof(error))) {
        std::cerr << error << '\n';
        return 2;
    }
    if (!checks.all_finite || checks.all_zero) return 3;
    tpmshx_result_evidence_v1 historical{};
    historical.abi_version = TPMSHX_RESULT_STAGE_ABI_VERSION;
    historical.struct_size = sizeof(historical);
    historical.result_id = "independent-historical-result";
    historical.dimension = 2;
    historical.converged = historical.model_active_b = historical.richardson_extrapolated = -1;
    historical.active_fluids[0] = historical.active_fluids[1] = 1;
    tpmshx_stage_output_v1 performance{};
    performance.struct_size = sizeof(performance);
    if (tpmshx_result_stage_evaluate_v1(&historical, nullptr, &performance, error, sizeof(error))) {
        std::cerr << error << '\n';
        return 4;
    }
    const bool valid = performance.metric_count == 17 && std::strstr(performance.json, "unverified");
    tpmshx_result_stage_release_v1(&performance);
    if (!valid) return 5;
    std::cout << "Independent result library: arrays and historical stage evaluation\n";
}
