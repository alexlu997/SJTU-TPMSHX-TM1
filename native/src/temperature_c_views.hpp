#pragma once
#include "tpmshx/temperature_evidence_c_api.h"
#include "tpmshx/conservative_energy.hpp"

namespace tpmshx {
inline tpmshx_model_enthalpy_array_v1 model_enthalpy_array(const std::vector<double>& v) {
    return {v.data(),v.size()};
}
inline tpmshx_model_enthalpy_evidence_v1 model_enthalpy_c_view(
        const PhysicalHeatLedger& ledger,
        const std::array<std::array<double,5>,2>& cp_coefficients,
        const char* algorithm,
        uint32_t physical_dimension) {
    tpmshx_model_enthalpy_evidence_v1 out{};
    out.available=1;out.physical_dimension=physical_dimension;
    out.boundary_complete=ledger.boundary_complete;
    out.algorithm=algorithm;
    out.prescribed_b_power=ledger.prescribed_b_power;
    for(std::size_t side=0;side<2;++side)
        for(std::size_t coefficient=0;coefficient<5;++coefficient)
            out.cp_coefficients[side][coefficient]=cp_coefficients[side][coefficient];
    for(std::size_t phase=0;phase<3;++phase) {
        out.solved[phase]=ledger.solved[phase];
        out.source_integral[phase]=ledger.source_integral[phase];
        out.residual[phase]=model_enthalpy_array(ledger.residual[phase]);
        for(std::size_t face=0;face<6;++face) {
            out.advective_out[phase][face]=model_enthalpy_array(ledger.advective_out[phase][face]);
            out.diffusive_out[phase][face]=model_enthalpy_array(ledger.diffusive_out[phase][face]);
        }
    }
    return out;
}
} // namespace tpmshx
