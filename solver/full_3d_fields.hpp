#pragma once

#include "tpmshx/full_3d.hpp"

namespace tpmshx::detail {

void update_real(const GridView& real,const Full3DSide& side,Full3DFlowState& state);
void balance_outflow(const GridView& grid,int direction,
    std::array<std::vector<double>,3>& velocity,const std::vector<double>& coefficient);

}  // namespace tpmshx::detail
