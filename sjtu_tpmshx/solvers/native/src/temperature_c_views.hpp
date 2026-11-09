#pragma once
#include "tpmshx/temperature_evidence_c_api.h"
#include "physical_ledger_c_views.hpp"

namespace tpmshx {
inline tpmshx_model_enthalpy_evidence_v1 model_enthalpy_c_view(
        const PhysicalHeatLedger& ledger,
        const std::array<std::array<double,5>,2>& cp_coefficients,
        const char* algorithm,
        uint32_t physical_dimension) {
    tpmshx_model_enthalpy_evidence_v1 out{};
    physical_ledger_c_fields(out,ledger,physical_dimension);
    out.algorithm=algorithm;
    for(std::size_t side=0;side<2;++side)
        for(std::size_t coefficient=0;coefficient<5;++coefficient)
            out.cp_coefficients[side][coefficient]=cp_coefficients[side][coefficient];
    return out;
}
} // namespace tpmshx
