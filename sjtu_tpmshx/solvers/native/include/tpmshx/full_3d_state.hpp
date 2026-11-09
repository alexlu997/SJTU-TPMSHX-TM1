#pragma once

#include "tpmshx/full_3d.hpp"
#include "tpmshx/run_state.hpp"

namespace tpmshx {

// Format and build identity precede the exact prepared input and controls.
// Host paths and callback addresses are not numerical identity fields.
RunStateRecord export_full_3d_state(const Full3DInput&,const Full3DControl&,const Full3DRunState&);
Full3DRunState import_full_3d_state(const Full3DInput&,const Full3DControl&,const RunStateRecord&);

} // namespace tpmshx
