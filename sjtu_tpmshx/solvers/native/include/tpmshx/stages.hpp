#pragma once
#include "tpmshx/stage_run_c_api.h"
#include "tpmshx/quick_design_stage_c_api.h"
#include <algorithm>
#include <stdexcept>
#include <thread>
#include <utility>

namespace tpmshx::stages {

class NativeError : public std::runtime_error {
public:
    NativeError(int status,const char* message):std::runtime_error(message),status_(status) {}
    int status() const noexcept {return status_;}
private:
    int status_;
};
namespace detail {
// Every owner is released by the same ABI that created it.
template<class State,void (*Release)(State*)> class Owned {
public:
    explicit Owned(State state):state_(state) {}
    ~Owned() {Release(&state_);}
    Owned(const Owned&)=delete;
    Owned& operator=(const Owned&)=delete;
    Owned(Owned&& other) noexcept:state_(std::exchange(other.state_,{})) {}
    Owned& operator=(Owned&& other) noexcept {
        if(this!=&other) {Release(&state_);state_=std::exchange(other.state_,{});}
        return *this;
    }
    const State& view() const noexcept {return state_;}
private:
    State state_;
};
inline void check(int status,const char* error) {if(status)throw NativeError(status,error);}
}
using PreparedCase2D=detail::Owned<tpmshx_preparation_case_2d_v1,tpmshx_preparation_case_2d_release_v1>;
using PreparedCase2Dv2=detail::Owned<tpmshx_preparation_case_2d_v2,tpmshx_preparation_case_2d_release_v2>;
using InletFlow2D=detail::Owned<tpmshx_preparation_flow_2d_v3,tpmshx_preparation_flow_2d_release_v3>;
using PreparedFlowCase2D=detail::Owned<tpmshx_preparation_flow_case_2d_v3,tpmshx_preparation_flow_case_2d_release_v3>;
using ContinuousInletFlow2D=detail::Owned<tpmshx_preparation_continuous_flow_2d_v4,tpmshx_preparation_continuous_flow_2d_release_v4>;
using PreparedContinuousCase2D=detail::Owned<tpmshx_preparation_continuous_case_2d_v4,tpmshx_preparation_continuous_case_2d_release_v4>;
using PreparedZonedCase2D=detail::Owned<tpmshx_preparation_zoned_case_2d_v5,tpmshx_preparation_zoned_case_2d_release_v5>;
using SigmoidLUT2D=detail::Owned<tpmshx_preparation_sigmoid_lut_v6,tpmshx_preparation_sigmoid_lut_release_v6>;
using PreparedSigmoidCase2D=detail::Owned<tpmshx_preparation_sigmoid_case_2d_v6,tpmshx_preparation_sigmoid_case_2d_release_v6>;
using ZonedInletFlow2D=detail::Owned<tpmshx_preparation_zoned_flow_2d_v8,tpmshx_preparation_zoned_flow_2d_release_v8>;
using PreparedZonedFlowCase2D=detail::Owned<tpmshx_preparation_zoned_flow_case_2d_v8,tpmshx_preparation_zoned_flow_case_2d_release_v8>;
using SigmoidInletFlow2D=detail::Owned<tpmshx_preparation_sigmoid_flow_2d_v8,tpmshx_preparation_sigmoid_flow_2d_release_v8>;
using PreparedSigmoidFlowCase2D=detail::Owned<tpmshx_preparation_sigmoid_flow_case_2d_v8,tpmshx_preparation_sigmoid_flow_case_2d_release_v8>;
using ZonedInletFlow2Dv9=detail::Owned<tpmshx_preparation_zoned_flow_2d_v9,tpmshx_preparation_zoned_flow_2d_release_v9>;
using PreparedZonedFlowCase2Dv9=detail::Owned<tpmshx_preparation_zoned_flow_case_2d_v9,tpmshx_preparation_zoned_flow_case_2d_release_v9>;
using SigmoidInletFlow2Dv9=detail::Owned<tpmshx_preparation_sigmoid_flow_2d_v9,tpmshx_preparation_sigmoid_flow_2d_release_v9>;
using PreparedSigmoidFlowCase2Dv9=detail::Owned<tpmshx_preparation_sigmoid_flow_case_2d_v9,tpmshx_preparation_sigmoid_flow_case_2d_release_v9>;
using PreparedFlowCase2Dv10=detail::Owned<tpmshx_preparation_flow_case_2d_v10,tpmshx_preparation_flow_case_2d_release_v10>;
using PreparedZonedFlowCase2Dv10=detail::Owned<tpmshx_preparation_zoned_flow_case_2d_v10,tpmshx_preparation_zoned_flow_case_2d_release_v10>;
using PreparedSigmoidFlowCase2Dv10=detail::Owned<tpmshx_preparation_sigmoid_flow_case_2d_v10,tpmshx_preparation_sigmoid_flow_case_2d_release_v10>;
using RunResult2D=detail::Owned<tpmshx_stage_run_result_2d_v1,tpmshx_stage_run_2d_release_v1>;
using RunState=detail::Owned<tpmshx_run_state_v1,tpmshx_run_state_release_v1>;
using Evaluation=detail::Owned<tpmshx_stage_output_v1,tpmshx_result_stage_release_v1>;

struct CaseInput2D : tpmshx_preparation_case_input_2d_v1 {
    CaseInput2D():tpmshx_preparation_case_input_2d_v1{} {
        abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION;struct_size=sizeof(tpmshx_preparation_case_input_2d_v1);
    }
};
struct PreparationOptions : tpmshx_preparation_case_options_v1 {
    PreparationOptions():tpmshx_preparation_case_options_v1{} {
        abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION;struct_size=sizeof(tpmshx_preparation_case_options_v1);
    }
};
struct CaseInput2Dv2 : tpmshx_preparation_case_input_2d_v2 {
    CaseInput2Dv2():tpmshx_preparation_case_input_2d_v2{} {
        abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;struct_size=sizeof(tpmshx_preparation_case_input_2d_v2);
        values=CaseInput2D{};
        kinds.cell_length=kinds.wall_thickness=kinds.solid_conductivity={64,0,0};
        for (auto& side:kinds.sides) side.velocity=side.temperature=side.pressure={64,0,0};
    }
};
struct FlowInput2D : tpmshx_preparation_flow_input_2d_v3 {
    FlowInput2D():tpmshx_preparation_flow_input_2d_v3{} {
        abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V3;struct_size=sizeof(tpmshx_preparation_flow_input_2d_v3);
        values=CaseInput2Dv2{};
        physical_depth_kind=target_kinds[0]=target_kinds[1]={64,0,0};
    }
};
struct ContinuousInput2D : tpmshx_preparation_continuous_input_2d_v4 {
    ContinuousInput2D():tpmshx_preparation_continuous_input_2d_v4{} {
        abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V4;struct_size=sizeof(tpmshx_preparation_continuous_input_2d_v4);
        values=FlowInput2D{};values.values.values.geometry_mode=1;
    }
};
struct ZonedInput2D : tpmshx_preparation_zoned_input_2d_v5 {
    ZonedInput2D():tpmshx_preparation_zoned_input_2d_v5{} {
        abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V5;struct_size=sizeof(tpmshx_preparation_zoned_input_2d_v5);
        values=CaseInput2Dv2{};values.values.geometry_mode=2;axis=1;
    }
};
struct SigmoidInput2D : tpmshx_preparation_sigmoid_input_2d_v6 {
    SigmoidInput2D():tpmshx_preparation_sigmoid_input_2d_v6{} {
        abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V6;struct_size=sizeof(tpmshx_preparation_sigmoid_input_2d_v6);
        values=ZonedInput2D{};values.kind=1;
        controls.inlet_transition=controls.outlet_transition={.2,64,0};
    }
};
struct ZonedFlowInput2D : tpmshx_preparation_zoned_flow_input_2d_v8 {
    ZonedFlowInput2D():tpmshx_preparation_zoned_flow_input_2d_v8{} {
        abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V8;struct_size=sizeof(tpmshx_preparation_zoned_flow_input_2d_v8);
        values=ZonedInput2D{};physical_depth_kind=target_kinds[0]=target_kinds[1]={64,0,0};
    }
};
struct SigmoidFlowInput2D : tpmshx_preparation_sigmoid_flow_input_2d_v8 {
    SigmoidFlowInput2D():tpmshx_preparation_sigmoid_flow_input_2d_v8{} {
        abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V8;struct_size=sizeof(tpmshx_preparation_sigmoid_flow_input_2d_v8);
        values=SigmoidInput2D{};physical_depth_kind=target_kinds[0]=target_kinds[1]={64,0,0};
    }
};
struct ZonedFlowInput2Dv9 : tpmshx_preparation_zoned_flow_input_2d_v9 {
    ZonedFlowInput2Dv9():tpmshx_preparation_zoned_flow_input_2d_v9{} {
        abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V9;struct_size=sizeof(tpmshx_preparation_zoned_flow_input_2d_v9);
        values=ZonedFlowInput2D{};model.solid_conductivity_W_mK=16.;model.solid_conductivity_kind={64,0,0};
    }
};
struct SigmoidFlowInput2Dv9 : tpmshx_preparation_sigmoid_flow_input_2d_v9 {
    SigmoidFlowInput2Dv9():tpmshx_preparation_sigmoid_flow_input_2d_v9{} {
        abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V9;struct_size=sizeof(tpmshx_preparation_sigmoid_flow_input_2d_v9);
        values=SigmoidFlowInput2D{};model.solid_conductivity_W_mK=16.;model.solid_conductivity_kind={64,0,0};
    }
};
struct GridKinds2D : tpmshx_preparation_grid_kinds_2d_v7 {
    GridKinds2D():tpmshx_preparation_grid_kinds_2d_v7{} {
        abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V7;struct_size=sizeof(tpmshx_preparation_grid_kinds_2d_v7);
        for (auto& value:lengths) value={64,0,0};
        for (auto& side:ports) for (auto& value:side) value={64,0,0};
    }
};
struct RunRequest2D : tpmshx_stage_run_request_2d_v1 {
    RunRequest2D():tpmshx_stage_run_request_2d_v1{} {
        abi_version=TPMSHX_STAGE_RUN_ABI_VERSION;struct_size=sizeof(tpmshx_stage_run_request_2d_v1);
    }
};
struct RunRequest2Dv2 : tpmshx_stage_run_request_2d_v2 {
    RunRequest2Dv2():tpmshx_stage_run_request_2d_v2{} {
        abi_version=TPMSHX_STAGE_RUN_ABI_VERSION_V2;struct_size=sizeof(tpmshx_stage_run_request_2d_v2);
        values=RunRequest2D{};
    }
};
struct RunControl : tpmshx_stage_run_control_v1 {
    RunControl():tpmshx_stage_run_control_v1{} {
        const auto logical=std::thread::hardware_concurrency();cpu_threads=std::min(8u,logical?logical:1u);
    }
};
struct RunRequest2Dv3 : tpmshx_stage_run_request_2d_v3 {
    RunRequest2Dv3():tpmshx_stage_run_request_2d_v3{} {
        abi_version=TPMSHX_STAGE_RUN_ABI_VERSION_V3;struct_size=sizeof(tpmshx_stage_run_request_2d_v3);
        values=RunRequest2Dv2{};
    }
};
struct SavedCase2D : tpmshx_stage_saved_case_2d_v1 {
    SavedCase2D():tpmshx_stage_saved_case_2d_v1{} {
        reference_cell_kind={64,0,0};cell_field_kind=hydraulic_diameter_kind={64,1,2};
        abi_version=TPMSHX_STAGE_RUN_ABI_VERSION;struct_size=sizeof(tpmshx_stage_saved_case_2d_v1);
        inlet_recorded=1;
    }
};
struct SavedCase2Dv2 : tpmshx_stage_saved_case_2d_v2 {
    SavedCase2Dv2():tpmshx_stage_saved_case_2d_v2{} {
        abi_version=TPMSHX_STAGE_RUN_ABI_VERSION_V2;struct_size=sizeof(tpmshx_stage_saved_case_2d_v2);
        values=SavedCase2D{};
    }
};
inline tpmshx_stage_capture_2d_v1 capture_summary(const RunResult2D& result,
    const tpmshx_stage_application_2d_v1& application) {
    tpmshx_stage_capture_2d_v1 output{};
    detail::check(tpmshx_stage_run_2d_get_capture_v1(&result.view(),&application,&output),
        "native 2D capture summary failed");
    return output;
}

// Keep the prepared owner alive and unchanged until take_result or release.
class Run2D {
public:
    Run2D(const PreparedCase2Dv2& prepared,const RunControl& control,const RunRequest2Dv3& request={},
        const RunState* state=nullptr):Run2D(&prepared.view(),nullptr,control,request,state) {}
    Run2D(const PreparedFlowCase2D& prepared,const RunControl& control,const RunRequest2Dv3& request={},
        const RunState* state=nullptr):Run2D(&prepared.view().prepared,nullptr,control,request,state) {}
    Run2D(const PreparedContinuousCase2D& prepared,const RunControl& control,const RunRequest2Dv3& request={},
        const RunState* state=nullptr):Run2D(nullptr,&prepared.view(),control,request,state) {}
    Run2D(const tpmshx_stage_saved_case_2d_v1& saved,const RunControl& control,const RunRequest2Dv3& request={},
        const RunState* state=nullptr) {
        char error[4096]{};
        const auto status=state?tpmshx_stage_run_2d_restore_saved_v1(&saved,&request,&control,
            state->view().fields,state->view().count,&run_,error,sizeof(error)):
            tpmshx_stage_run_2d_create_saved_v1(&saved,&request,&control,&run_,error,sizeof(error));
        detail::check(status,error);
    }
    Run2D(const tpmshx_stage_saved_case_2d_v2& saved,const RunControl& control,const RunRequest2Dv3& request={},
        const RunState* state=nullptr) {
        char error[4096]{};
        const auto status=state?tpmshx_stage_run_2d_restore_saved_v2(&saved,&request,&control,
            state->view().fields,state->view().count,&run_,error,sizeof(error)):
            tpmshx_stage_run_2d_create_saved_v2(&saved,&request,&control,&run_,error,sizeof(error));
        detail::check(status,error);
    }
    ~Run2D() {tpmshx_stage_run_2d_release_run_v1(&run_);}
    Run2D(const Run2D&)=delete;
    Run2D& operator=(const Run2D&)=delete;
    Run2D(Run2D&& other) noexcept:run_(std::exchange(other.run_,nullptr)) {}
    Run2D& operator=(Run2D&& other) noexcept {
        if(this!=&other) {tpmshx_stage_run_2d_release_run_v1(&run_);run_=std::exchange(other.run_,nullptr);}
        return *this;
    }
    uint32_t phase() const {
        uint32_t value=0;
        detail::check(tpmshx_stage_run_2d_phase_v1(run_,&value),"invalid stage run");return value;
    }
    uint32_t advance_step() {
        uint32_t value=0;char error[4096]{};
        detail::check(tpmshx_stage_run_2d_advance_step_v1(run_,&value,error,sizeof(error)),error);return value;
    }
    RunState snapshot() const {
        tpmshx_run_state_v1 value{};char error[4096]{};
        detail::check(tpmshx_stage_run_2d_snapshot_v1(run_,&value,error,sizeof(error)),error);return RunState(value);
    }
    RunResult2D take_result() {
        tpmshx_stage_run_result_2d_v1 value{};char error[4096]{};
        value.abi_version=TPMSHX_STAGE_RUN_ABI_VERSION;value.struct_size=sizeof(value);
        detail::check(tpmshx_stage_run_2d_take_result_v1(run_,&value,error,sizeof(error)),error);return RunResult2D(value);
    }
private:
    Run2D(const tpmshx_preparation_case_2d_v2* prepared,const tpmshx_preparation_continuous_case_2d_v4* continuous,
        const RunControl& control,const RunRequest2Dv3& request,const RunState* state) {
        char error[4096]{};
        const auto status=state?tpmshx_stage_run_2d_restore_v1(prepared,continuous,&request,&control,
            state->view().fields,state->view().count,&run_,error,sizeof(error)):
            tpmshx_stage_run_2d_create_v1(prepared,continuous,&request,&control,&run_,error,sizeof(error));
        detail::check(status,error);
    }
    void* run_=nullptr;
};
inline PreparedCase2D prepare_case(const CaseInput2D& input,const PreparationOptions& options={}) {
    tpmshx_preparation_case_2d_v1 output{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION;output.struct_size=sizeof(output);
    char error[4096]{};
    detail::check(tpmshx_prepare_case_2d_v1(&input,&options,nullptr,&output,error,sizeof(error)),error);
    return PreparedCase2D(output);
}
inline PreparedCase2Dv2 prepare_case(const CaseInput2Dv2& input,const PreparationOptions& options={}) {
    tpmshx_preparation_case_2d_v2 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;
    output.struct_size=sizeof(output);failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_prepare_case_2d_v2(&input,&options,nullptr,&output,&failure,error,sizeof(error)),error);
    return PreparedCase2Dv2(output);
}
inline PreparedZonedCase2D prepare_case(const ZonedInput2D& input,const PreparationOptions& options={}) {
    tpmshx_preparation_zoned_case_2d_v5 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V5;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_prepare_zoned_case_2d_v5(&input,&options,nullptr,&output,&failure,error,sizeof(error)),error);
    return PreparedZonedCase2D(output);
}
inline SigmoidLUT2D build_sigmoid_lut(std::uint32_t topology,std::size_t cell_nodes=41,
    std::size_t wall_nodes=31,std::size_t resolution=256) {
    tpmshx_preparation_sigmoid_lut_v6 output{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V6;output.struct_size=sizeof(output);
    char error[4096]{};
    detail::check(tpmshx_preparation_sigmoid_lut_create_v6(topology,cell_nodes,wall_nodes,resolution,
        &output,error,sizeof(error)),error);
    return SigmoidLUT2D(output);
}
inline PreparedSigmoidCase2D prepare_case(const SigmoidInput2D& input,const PreparationOptions& options={}) {
    tpmshx_preparation_sigmoid_case_2d_v6 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V6;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_prepare_sigmoid_case_2d_v6(&input,&options,nullptr,&output,&failure,error,sizeof(error)),error);
    return PreparedSigmoidCase2D(output);
}
inline InletFlow2D prepare_inlet_mass_capacities(const FlowInput2D& input,const PreparationOptions& options={}) {
    tpmshx_preparation_flow_2d_v3 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V3;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_prepare_inlet_mass_capacities_2d_v3(&input,&options,nullptr,&output,&failure,error,sizeof(error)),error);
    return InletFlow2D(output);
}
inline InletFlow2D resolve_inlet_flow(const FlowInput2D& input,const PreparationOptions& options={}) {
    tpmshx_preparation_flow_2d_v3 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V3;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_resolve_inlet_flow_2d_v3(&input,&options,nullptr,&output,&failure,error,sizeof(error)),error);
    return InletFlow2D(output);
}
inline PreparedFlowCase2D prepare_case(const FlowInput2D& input,const PreparationOptions& options={}) {
    tpmshx_preparation_flow_case_2d_v3 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V3;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_prepare_flow_case_2d_v3(&input,&options,nullptr,&output,&failure,error,sizeof(error)),error);
    return PreparedFlowCase2D(output);
}
inline ContinuousInletFlow2D prepare_inlet_mass_capacities(const ContinuousInput2D& input,const PreparationOptions& options={}) {
    tpmshx_preparation_continuous_flow_2d_v4 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V4;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_prepare_inlet_mass_capacities_2d_v4(&input,&options,nullptr,&output,&failure,error,sizeof(error)),error);
    return ContinuousInletFlow2D(output);
}
inline ContinuousInletFlow2D resolve_inlet_flow(const ContinuousInput2D& input,const PreparationOptions& options={}) {
    tpmshx_preparation_continuous_flow_2d_v4 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V4;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_resolve_inlet_flow_2d_v4(&input,&options,nullptr,&output,&failure,error,sizeof(error)),error);
    return ContinuousInletFlow2D(output);
}
inline PreparedContinuousCase2D prepare_case(const ContinuousInput2D& input,const PreparationOptions& options={}) {
    tpmshx_preparation_continuous_case_2d_v4 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V4;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_prepare_flow_case_2d_v4(&input,&options,nullptr,&output,&failure,error,sizeof(error)),error);
    return PreparedContinuousCase2D(output);
}
inline PreparedZonedCase2D prepare_case(const ZonedInput2D& input,const GridKinds2D& grid,
    const PreparationOptions& options) {
    tpmshx_preparation_zoned_case_2d_v5 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V5;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_prepare_zoned_case_2d_v7(&input,&grid,&options,nullptr,&output,&failure,error,sizeof(error)),error);
    return PreparedZonedCase2D(output);
}
inline PreparedSigmoidCase2D prepare_case(const SigmoidInput2D& input,const GridKinds2D& grid,
    const PreparationOptions& options) {
    tpmshx_preparation_sigmoid_case_2d_v6 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V6;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_prepare_sigmoid_case_2d_v7(&input,&grid,&options,nullptr,&output,&failure,error,sizeof(error)),error);
    return PreparedSigmoidCase2D(output);
}
inline InletFlow2D prepare_inlet_mass_capacities(const FlowInput2D& input,const GridKinds2D& grid,
    const PreparationOptions& options) {
    tpmshx_preparation_flow_2d_v3 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V3;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_prepare_inlet_mass_capacities_2d_v7(&input,&grid,&options,nullptr,&output,&failure,error,sizeof(error)),error);
    return InletFlow2D(output);
}
inline InletFlow2D resolve_inlet_flow(const FlowInput2D& input,const GridKinds2D& grid,
    const PreparationOptions& options) {
    tpmshx_preparation_flow_2d_v3 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V3;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_resolve_inlet_flow_2d_v7(&input,&grid,&options,nullptr,&output,&failure,error,sizeof(error)),error);
    return InletFlow2D(output);
}
inline PreparedFlowCase2D prepare_case(const FlowInput2D& input,const GridKinds2D& grid,
    const PreparationOptions& options) {
    tpmshx_preparation_flow_case_2d_v3 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V3;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_prepare_flow_case_2d_v7(&input,&grid,&options,nullptr,&output,&failure,error,sizeof(error)),error);
    return PreparedFlowCase2D(output);
}
inline ContinuousInletFlow2D prepare_inlet_mass_capacities(const ContinuousInput2D& input,const GridKinds2D& grid,
    const PreparationOptions& options) {
    tpmshx_preparation_continuous_flow_2d_v4 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V4;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_prepare_continuous_inlet_mass_capacities_2d_v7(&input,&grid,&options,nullptr,&output,&failure,error,sizeof(error)),error);
    return ContinuousInletFlow2D(output);
}
inline ContinuousInletFlow2D resolve_inlet_flow(const ContinuousInput2D& input,const GridKinds2D& grid,
    const PreparationOptions& options) {
    tpmshx_preparation_continuous_flow_2d_v4 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V4;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_resolve_continuous_inlet_flow_2d_v7(&input,&grid,&options,nullptr,&output,&failure,error,sizeof(error)),error);
    return ContinuousInletFlow2D(output);
}
inline PreparedContinuousCase2D prepare_case(const ContinuousInput2D& input,const GridKinds2D& grid,
    const PreparationOptions& options) {
    tpmshx_preparation_continuous_case_2d_v4 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V4;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_prepare_continuous_flow_case_2d_v7(&input,&grid,&options,nullptr,&output,&failure,error,sizeof(error)),error);
    return PreparedContinuousCase2D(output);
}
inline ZonedInletFlow2D prepare_inlet_mass_capacities(const ZonedFlowInput2D& input,const GridKinds2D& grid={},
    const PreparationOptions& options={}) {
    tpmshx_preparation_zoned_flow_2d_v8 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V8;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_prepare_zoned_inlet_mass_capacities_2d_v8(&input,&grid,&options,nullptr,&output,&failure,error,sizeof(error)),error);
    return ZonedInletFlow2D(output);
}
inline ZonedInletFlow2D resolve_inlet_flow(const ZonedFlowInput2D& input,const GridKinds2D& grid={},
    const PreparationOptions& options={}) {
    tpmshx_preparation_zoned_flow_2d_v8 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V8;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_resolve_zoned_inlet_flow_2d_v8(&input,&grid,&options,nullptr,&output,&failure,error,sizeof(error)),error);
    return ZonedInletFlow2D(output);
}
inline PreparedZonedFlowCase2D prepare_case(const ZonedFlowInput2D& input,const GridKinds2D& grid={},
    const PreparationOptions& options={}) {
    tpmshx_preparation_zoned_flow_case_2d_v8 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V8;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_prepare_zoned_flow_case_2d_v8(&input,&grid,&options,nullptr,&output,&failure,error,sizeof(error)),error);
    return PreparedZonedFlowCase2D(output);
}
inline SigmoidInletFlow2D prepare_inlet_mass_capacities(const SigmoidFlowInput2D& input,const GridKinds2D& grid={},
    const PreparationOptions& options={}) {
    tpmshx_preparation_sigmoid_flow_2d_v8 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V8;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_prepare_sigmoid_inlet_mass_capacities_2d_v8(&input,&grid,&options,nullptr,&output,&failure,error,sizeof(error)),error);
    return SigmoidInletFlow2D(output);
}
inline SigmoidInletFlow2D resolve_inlet_flow(const SigmoidFlowInput2D& input,const GridKinds2D& grid={},
    const PreparationOptions& options={}) {
    tpmshx_preparation_sigmoid_flow_2d_v8 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V8;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_resolve_sigmoid_inlet_flow_2d_v8(&input,&grid,&options,nullptr,&output,&failure,error,sizeof(error)),error);
    return SigmoidInletFlow2D(output);
}
inline PreparedSigmoidFlowCase2D prepare_case(const SigmoidFlowInput2D& input,const GridKinds2D& grid={},
    const PreparationOptions& options={}) {
    tpmshx_preparation_sigmoid_flow_case_2d_v8 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V8;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_prepare_sigmoid_flow_case_2d_v8(&input,&grid,&options,nullptr,&output,&failure,error,sizeof(error)),error);
    return PreparedSigmoidFlowCase2D(output);
}
inline ZonedInletFlow2Dv9 prepare_inlet_mass_capacities(const ZonedFlowInput2Dv9& input,const GridKinds2D& grid={},
    const PreparationOptions& options={},const tpmshx_preparation_case_callbacks_v9* callbacks=nullptr) {
    tpmshx_preparation_zoned_flow_2d_v9 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V9;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_prepare_zoned_inlet_mass_capacities_2d_v9(&input,&grid,&options,
        callbacks?&callbacks->values.values.values:nullptr,&output,&failure,error,sizeof(error)),error);
    return ZonedInletFlow2Dv9(output);
}
inline ZonedInletFlow2Dv9 resolve_inlet_flow(const ZonedFlowInput2Dv9& input,const GridKinds2D& grid={},
    const PreparationOptions& options={},const tpmshx_preparation_case_callbacks_v9* callbacks=nullptr) {
    tpmshx_preparation_zoned_flow_2d_v9 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V9;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_resolve_zoned_inlet_flow_2d_v9(&input,&grid,&options,
        callbacks?&callbacks->values.values.values:nullptr,&output,&failure,error,sizeof(error)),error);
    return ZonedInletFlow2Dv9(output);
}
inline PreparedZonedFlowCase2Dv9 prepare_case(const ZonedFlowInput2Dv9& input,const GridKinds2D& grid={},
    const PreparationOptions& options={},const tpmshx_preparation_case_callbacks_v9* callbacks=nullptr) {
    tpmshx_preparation_zoned_flow_case_2d_v9 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V9;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_prepare_zoned_flow_case_2d_v9(&input,&grid,&options,
        callbacks?&callbacks->values.values.values:nullptr,&output,&failure,error,sizeof(error)),error);
    return PreparedZonedFlowCase2Dv9(output);
}
inline SigmoidInletFlow2Dv9 prepare_inlet_mass_capacities(const SigmoidFlowInput2Dv9& input,const GridKinds2D& grid={},
    const PreparationOptions& options={},const tpmshx_preparation_case_callbacks_v9* callbacks=nullptr) {
    tpmshx_preparation_sigmoid_flow_2d_v9 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V9;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_prepare_sigmoid_inlet_mass_capacities_2d_v9(&input,&grid,&options,
        callbacks?&callbacks->values.values.values:nullptr,&output,&failure,error,sizeof(error)),error);
    return SigmoidInletFlow2Dv9(output);
}
inline SigmoidInletFlow2Dv9 resolve_inlet_flow(const SigmoidFlowInput2Dv9& input,const GridKinds2D& grid={},
    const PreparationOptions& options={},const tpmshx_preparation_case_callbacks_v9* callbacks=nullptr) {
    tpmshx_preparation_sigmoid_flow_2d_v9 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V9;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_resolve_sigmoid_inlet_flow_2d_v9(&input,&grid,&options,
        callbacks?&callbacks->values.values.values:nullptr,&output,&failure,error,sizeof(error)),error);
    return SigmoidInletFlow2Dv9(output);
}
inline PreparedSigmoidFlowCase2Dv9 prepare_case(const SigmoidFlowInput2Dv9& input,const GridKinds2D& grid={},
    const PreparationOptions& options={},const tpmshx_preparation_case_callbacks_v9* callbacks=nullptr) {
    tpmshx_preparation_sigmoid_flow_case_2d_v9 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V9;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_prepare_sigmoid_flow_case_2d_v9(&input,&grid,&options,
        callbacks?&callbacks->values.values.values:nullptr,&output,&failure,error,sizeof(error)),error);
    return PreparedSigmoidFlowCase2Dv9(output);
}
inline PreparedFlowCase2Dv10 prepare_offset_case(const FlowInput2D& input,const GridKinds2D& grid={},
    const PreparationOptions& options={},const tpmshx_preparation_case_callbacks_v1* callbacks=nullptr) {
    tpmshx_preparation_flow_case_2d_v10 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V10;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_prepare_flow_case_2d_v10(&input,&grid,&options,callbacks,
        &output,&failure,error,sizeof(error)),error);
    return PreparedFlowCase2Dv10(output);
}
inline PreparedZonedFlowCase2Dv10 prepare_offset_case(const ZonedFlowInput2Dv9& input,const GridKinds2D& grid={},
    const PreparationOptions& options={},const tpmshx_preparation_case_callbacks_v1* callbacks=nullptr) {
    tpmshx_preparation_zoned_flow_case_2d_v10 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V10;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_prepare_zoned_flow_case_2d_v10(&input,&grid,&options,callbacks,
        &output,&failure,error,sizeof(error)),error);
    return PreparedZonedFlowCase2Dv10(output);
}
inline PreparedSigmoidFlowCase2Dv10 prepare_offset_case(const SigmoidFlowInput2Dv9& input,const GridKinds2D& grid={},
    const PreparationOptions& options={},const tpmshx_preparation_case_callbacks_v1* callbacks=nullptr) {
    tpmshx_preparation_sigmoid_flow_case_2d_v10 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V10;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_prepare_sigmoid_flow_case_2d_v10(&input,&grid,&options,callbacks,
        &output,&failure,error,sizeof(error)),error);
    return PreparedSigmoidFlowCase2Dv10(output);
}
inline ZonedInletFlow2Dv9 prepare_offset_inlet_mass_capacities(const ZonedFlowInput2Dv9& input,const GridKinds2D& grid={},
    const PreparationOptions& options={},const tpmshx_preparation_case_callbacks_v1* callbacks=nullptr) {
    tpmshx_preparation_zoned_flow_2d_v9 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V9;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_prepare_zoned_inlet_mass_capacities_2d_v10(&input,&grid,&options,callbacks,&output,&failure,error,sizeof(error)),error);
    return ZonedInletFlow2Dv9(output);
}
inline ZonedInletFlow2Dv9 resolve_offset_inlet_flow(const ZonedFlowInput2Dv9& input,const GridKinds2D& grid={},
    const PreparationOptions& options={},const tpmshx_preparation_case_callbacks_v1* callbacks=nullptr) {
    tpmshx_preparation_zoned_flow_2d_v9 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V9;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_resolve_zoned_inlet_flow_2d_v10(&input,&grid,&options,callbacks,&output,&failure,error,sizeof(error)),error);
    return ZonedInletFlow2Dv9(output);
}
inline SigmoidInletFlow2Dv9 prepare_offset_inlet_mass_capacities(const SigmoidFlowInput2Dv9& input,const GridKinds2D& grid={},
    const PreparationOptions& options={},const tpmshx_preparation_case_callbacks_v1* callbacks=nullptr) {
    tpmshx_preparation_sigmoid_flow_2d_v9 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V9;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_prepare_sigmoid_inlet_mass_capacities_2d_v10(&input,&grid,&options,callbacks,&output,&failure,error,sizeof(error)),error);
    return SigmoidInletFlow2Dv9(output);
}
inline SigmoidInletFlow2Dv9 resolve_offset_inlet_flow(const SigmoidFlowInput2Dv9& input,const GridKinds2D& grid={},
    const PreparationOptions& options={},const tpmshx_preparation_case_callbacks_v1* callbacks=nullptr) {
    tpmshx_preparation_sigmoid_flow_2d_v9 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V9;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_resolve_sigmoid_inlet_flow_2d_v10(&input,&grid,&options,callbacks,&output,&failure,error,sizeof(error)),error);
    return SigmoidInletFlow2Dv9(output);
}
// Keep the returned descriptor and prepared owner alive through result transfer.
inline SavedCase2Dv2 saved_case(const PreparedFlowCase2Dv10& prepared) {
    SavedCase2Dv2 output;
    const auto& value=prepared.view();output.values.prepared=&value.values.prepared;
    output.values.reference_cell_kind=value.values.prepared.input_kinds.cell_length;
    output.have_side_geometry=value.thermal.have_side_geometry;
    for(size_t side=0;side<2;++side)std::copy_n(value.thermal.side_geometry[side],4,output.side_geometry[side]);
    return output;
}
inline SavedCase2Dv2 saved_case(const PreparedZonedFlowCase2Dv10& prepared) {
    SavedCase2Dv2 output;
    const auto& value=prepared.view();const auto& spatial=value.values.values.prepared;
    output.values.prepared=&spatial.prepared;
    output.values.reference_cell_kind=spatial.prepared.input_kinds.cell_length;
    output.values.cell_field_kind=spatial.prepared.field_kinds[0];
    output.values.area_density_per_m=spatial.area_density_per_m;
    output.values.hydraulic_diameter_m=spatial.hydraulic_diameter_m;
    std::copy_n(spatial.fluid_conductivity,2,output.values.fluid_conductivity);
    output.have_side_geometry=value.thermal.have_side_geometry;
    for(size_t side=0;side<2;++side)std::copy_n(value.thermal.side_geometry[side],4,output.side_geometry[side]);
    return output;
}
inline SavedCase2Dv2 saved_case(const PreparedSigmoidFlowCase2Dv10& prepared) {
    SavedCase2Dv2 output;
    const auto& value=prepared.view();const auto& spatial=value.values.values.prepared.values;
    output.values.prepared=&spatial.prepared;
    output.values.reference_cell_kind=spatial.prepared.input_kinds.cell_length;
    output.values.cell_field_kind=spatial.prepared.field_kinds[0];
    output.values.area_density_per_m=spatial.area_density_per_m;
    output.values.hydraulic_diameter_m=spatial.hydraulic_diameter_m;
    std::copy_n(spatial.fluid_conductivity,2,output.values.fluid_conductivity);
    output.have_side_geometry=value.thermal.have_side_geometry;
    for(size_t side=0;side<2;++side)std::copy_n(value.thermal.side_geometry[side],4,output.side_geometry[side]);
    return output;
}
inline RunResult2D run_case(const PreparedFlowCase2Dv10& prepared,const RunControl& control,
    const RunRequest2Dv3& request={}) {
    auto saved=saved_case(prepared);Run2D run(saved,control,request);
    while(run.phase()!=TPMSHX_FULL2D_COMPLETED)run.advance_step();
    return run.take_result();
}
inline RunResult2D run_case(const PreparedZonedFlowCase2Dv10& prepared,const RunControl& control,
    const RunRequest2Dv3& request={}) {
    auto saved=saved_case(prepared);Run2D run(saved,control,request);
    while(run.phase()!=TPMSHX_FULL2D_COMPLETED)run.advance_step();
    return run.take_result();
}
inline RunResult2D run_case(const PreparedSigmoidFlowCase2Dv10& prepared,const RunControl& control,
    const RunRequest2Dv3& request={}) {
    auto saved=saved_case(prepared);Run2D run(saved,control,request);
    while(run.phase()!=TPMSHX_FULL2D_COMPLETED)run.advance_step();
    return run.take_result();
}
inline RunResult2D run_case(const PreparedCase2D& prepared,const RunControl& control,const RunRequest2D& request={}) {
    tpmshx_stage_run_result_2d_v1 output{};
    output.abi_version=TPMSHX_STAGE_RUN_ABI_VERSION;output.struct_size=sizeof(output);
    char error[4096]{};
    detail::check(tpmshx_run_case_2d_v1(&prepared.view(),&request,&control,&output,error,sizeof(error)),error);
    return RunResult2D(output);
}
inline RunResult2D run_case(const PreparedCase2Dv2& prepared,const RunControl& control,const RunRequest2Dv2& request={}) {
    tpmshx_stage_run_result_2d_v1 output{};
    output.abi_version=TPMSHX_STAGE_RUN_ABI_VERSION;output.struct_size=sizeof(output);
    char error[4096]{};
    detail::check(tpmshx_run_case_2d_v2(&prepared.view(),&request,&control,&output,error,sizeof(error)),error);
    return RunResult2D(output);
}
inline RunResult2D run_case(const PreparedFlowCase2D& prepared,const RunControl& control,const RunRequest2Dv2& request={}) {
    tpmshx_stage_run_result_2d_v1 output{};
    output.abi_version=TPMSHX_STAGE_RUN_ABI_VERSION;output.struct_size=sizeof(output);
    char error[4096]{};
    detail::check(tpmshx_run_case_2d_v2(&prepared.view().prepared,&request,&control,&output,error,sizeof(error)),error);
    return RunResult2D(output);
}
inline RunResult2D run_case(const PreparedContinuousCase2D& prepared,const RunControl& control,const RunRequest2Dv2& request={}) {
    tpmshx_stage_run_result_2d_v1 output{};
    output.abi_version=TPMSHX_STAGE_RUN_ABI_VERSION;output.struct_size=sizeof(output);
    char error[4096]{};
    detail::check(tpmshx_run_case_2d_v3(&prepared.view(),&request,&control,&output,error,sizeof(error)),error);
    return RunResult2D(output);
}
inline Evaluation evaluate(const RunResult2D& result,const tpmshx_stage_metric_spec_v1* metric=nullptr) {
    tpmshx_stage_output_v1 output{};output.struct_size=sizeof(output);
    char error[4096]{};
    detail::check(tpmshx_result_stage_evaluate_v1(&result.view().evidence,metric,&output,error,sizeof(error)),error);
    return Evaluation(output);
}
using PreparedQuickDesign=detail::Owned<tpmshx_quick_prepared_v1,tpmshx_quick_prepared_release_v1>;
using RunResultQuickDesign=detail::Owned<tpmshx_quick_run_result_v1,tpmshx_quick_run_release_v1>;
struct QuickDesignInput : tpmshx_quick_input_v1 {
    QuickDesignInput():tpmshx_quick_input_v1{} {
        abi_version=TPMSHX_QUICK_DESIGN_STAGE_ABI_VERSION;struct_size=sizeof(tpmshx_quick_input_v1);
    }
};
inline PreparedQuickDesign prepare_quick_design(const QuickDesignInput& input) {
    tpmshx_quick_prepared_v1 output{};
    output.abi_version=TPMSHX_QUICK_DESIGN_STAGE_ABI_VERSION;output.struct_size=sizeof(output);
    char error[4096]{};
    detail::check(tpmshx_prepare_quick_design_v1(&input,&output,error,sizeof(error)),error);
    return PreparedQuickDesign(output);
}
inline RunResultQuickDesign run_case(const PreparedQuickDesign& prepared,const tpmshx_quick_run_control_v1& control) {
    tpmshx_quick_run_result_v1 output{};
    output.abi_version=TPMSHX_QUICK_DESIGN_STAGE_ABI_VERSION;output.struct_size=sizeof(output);
    char error[4096]{};
    detail::check(tpmshx_run_quick_design_v1(&prepared.view(),&control,&output,error,sizeof(error)),error);
    return RunResultQuickDesign(output);
}
inline Evaluation evaluate(const RunResultQuickDesign& result,const tpmshx_stage_metric_spec_v1* metric=nullptr) {
    tpmshx_stage_output_v1 output{};output.struct_size=sizeof(output);
    char error[4096]{};
    detail::check(tpmshx_result_stage_evaluate_v1(&result.view().evidence,metric,&output,error,sizeof(error)),error);
    return Evaluation(output);
}
}  // namespace tpmshx::stages
