#pragma once
#include "tpmshx/physical_ledger_c_api.h"
#include "tpmshx/conservative_energy.hpp"

namespace tpmshx {
template<class View>
void physical_ledger_c_fields(View& out,const PhysicalHeatLedger& ledger,uint32_t dimension) {
    out.available=1;out.physical_dimension=dimension;
    out.boundary_complete=ledger.boundary_complete;
    out.prescribed_b_power=ledger.prescribed_b_power;
    for(std::size_t phase=0;phase<3;++phase) {
        out.solved[phase]=ledger.solved[phase];
        out.source_integral[phase]=ledger.source_integral[phase];
        const auto& residual=ledger.residual[phase];
        out.residual[phase]={residual.data(),residual.size()};
        for(std::size_t face=0;face<6;++face) {
            const auto& advective=ledger.advective_out[phase][face];
            const auto& diffusive=ledger.diffusive_out[phase][face];
            out.advective_out[phase][face]={advective.data(),advective.size()};
            out.diffusive_out[phase][face]={diffusive.data(),diffusive.size()};
        }
    }
}
inline tpmshx_physical_heat_ledger_v1 physical_ledger_c_view(
        const PhysicalHeatLedger& ledger,uint32_t dimension) {
    tpmshx_physical_heat_ledger_v1 out{};
    physical_ledger_c_fields(out,ledger,dimension);
    return out;
}
} // namespace tpmshx
