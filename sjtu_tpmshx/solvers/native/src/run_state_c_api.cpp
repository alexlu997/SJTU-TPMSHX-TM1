#include "run_state_c_views.hpp"

extern "C" void TPMSHX_THERMAL_CALL tpmshx_run_state_release_v1(tpmshx_run_state_v1* state) {
    if(state) {delete static_cast<tpmshx::run_state_c_views::SnapshotOwner*>(state->owner);*state={};}
}
