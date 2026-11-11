#pragma once
#include "tpmshx/stage_run_c_api.h"
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
// Keep the prepared owner alive and unchanged until take_result or release.
class Run2D {
public:
    Run2D(const PreparedCase2Dv2& prepared,const RunControl& control,const RunRequest2Dv3& request={},
        const RunState* state=nullptr):Run2D(&prepared.view(),nullptr,control,request,state) {}
    Run2D(const PreparedFlowCase2D& prepared,const RunControl& control,const RunRequest2Dv3& request={},
        const RunState* state=nullptr):Run2D(&prepared.view().prepared,nullptr,control,request,state) {}
    Run2D(const PreparedContinuousCase2D& prepared,const RunControl& control,const RunRequest2Dv3& request={},
        const RunState* state=nullptr):Run2D(nullptr,&prepared.view(),control,request,state) {}
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
}  // namespace tpmshx::stages
