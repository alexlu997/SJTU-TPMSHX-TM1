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
using PreparedZonedCase2D=detail::Owned<tpmshx_preparation_zoned_case_2d_v5,tpmshx_preparation_zoned_case_2d_release_v5>;
using SigmoidLUT2D=detail::Owned<tpmshx_preparation_sigmoid_lut_v6,tpmshx_preparation_sigmoid_lut_release_v6>;
using PreparedSigmoidCase2D=detail::Owned<tpmshx_preparation_sigmoid_case_2d_v6,tpmshx_preparation_sigmoid_case_2d_release_v6>;
using RunResult2D=detail::Owned<tpmshx_stage_run_result_2d_v1,tpmshx_stage_run_2d_release_v1>;
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
struct RunRequest2D : tpmshx_stage_run_request_2d_v1 {
    RunRequest2D():tpmshx_stage_run_request_2d_v1{} {
        abi_version=TPMSHX_STAGE_RUN_ABI_VERSION;struct_size=sizeof(tpmshx_stage_run_request_2d_v1);
    }
};
struct RunControl : tpmshx_stage_run_control_v1 {
    RunControl():tpmshx_stage_run_control_v1{} {
        const auto logical=std::thread::hardware_concurrency();cpu_threads=std::min(8u,logical?logical:1u);
    }
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
inline RunResult2D run_case(const PreparedCase2D& prepared,const RunControl& control,const RunRequest2D& request={}) {
    tpmshx_stage_run_result_2d_v1 output{};
    output.abi_version=TPMSHX_STAGE_RUN_ABI_VERSION;output.struct_size=sizeof(output);
    char error[4096]{};
    detail::check(tpmshx_run_case_2d_v1(&prepared.view(),&request,&control,&output,error,sizeof(error)),error);
    return RunResult2D(output);
}
inline Evaluation evaluate(const RunResult2D& result,const tpmshx_stage_metric_spec_v1* metric=nullptr) {
    tpmshx_stage_output_v1 output{};output.struct_size=sizeof(output);
    char error[4096]{};
    detail::check(tpmshx_result_stage_evaluate_v1(&result.view().evidence,metric,&output,error,sizeof(error)),error);
    return Evaluation(output);
}
}  // namespace tpmshx::stages
