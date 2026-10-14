#pragma once

#include "tpmshx/full_2d.hpp"
#include "tpmshx/run_state.hpp"

namespace tpmshx {

// Host paths and callbacks do not change the exact numerical identity.
RunStateRecord export_full_2d_state(const Full2DProblem&,const Full2DControl&,const Full2DRunState&);
Full2DRunState import_full_2d_state(const Full2DProblem&,const Full2DControl&,const RunStateRecord&);

} // namespace tpmshx
