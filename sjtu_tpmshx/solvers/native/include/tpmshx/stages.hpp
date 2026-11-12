#pragma once
#include "tpmshx/stage_run_c_api.h"
#include "tpmshx/stage_run_3d_c_api.h"
#include "tpmshx/preparation_case_3d_c_api.h"
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
using PreparedCase3D=detail::Owned<tpmshx_preparation_case_3d_v1,tpmshx_preparation_case_3d_release_v1>;
using InletFlow3D=detail::Owned<tpmshx_preparation_flow_3d_v2,tpmshx_preparation_flow_3d_release_v2>;
using PreparedFlowCase3D=detail::Owned<tpmshx_preparation_flow_case_3d_v2,tpmshx_preparation_flow_case_3d_release_v2>;
using ContinuousInletFlow3D=detail::Owned<tpmshx_preparation_continuous_flow_3d_v3,tpmshx_preparation_continuous_flow_3d_release_v3>;
using PreparedContinuousCase3D=detail::Owned<tpmshx_preparation_continuous_case_3d_v3,tpmshx_preparation_continuous_case_3d_release_v3>;
using SpatialInletFlow3D=detail::Owned<tpmshx_preparation_spatial_flow_3d_v4,tpmshx_preparation_spatial_flow_3d_release_v4>;
using PreparedSpatialCase3D=detail::Owned<tpmshx_preparation_spatial_case_3d_v4,tpmshx_preparation_spatial_case_3d_release_v4>;
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
using RunResult2D=detail::Owned<tpmshx_stage_run_result_2d_v1,tpmshx_stage_run_2d_release_v1>;
using RunResult3D=detail::Owned<tpmshx_stage_run_result_3d_v1,tpmshx_stage_run_3d_release_v1>;
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
struct CaseInput3D : tpmshx_preparation_case_input_3d_v1 {
    CaseInput3D():tpmshx_preparation_case_input_3d_v1{} {
        abi_version=TPMSHX_PREPARATION_CASE_3D_ABI_VERSION;struct_size=sizeof(tpmshx_preparation_case_input_3d_v1);
        max_cells=2000000;
        for (auto& length:lengths_m) length={0.,64,0};
        kinds.cell_length=kinds.wall_thickness=kinds.solid_conductivity={64,0,0};
        for (auto& side:kinds.sides) side.velocity=side.temperature=side.pressure={64,0,0};
        for (auto& side:sides) side.port.active=1;
    }
};
struct FlowInput3D : tpmshx_preparation_flow_input_3d_v2 {
    FlowInput3D():tpmshx_preparation_flow_input_3d_v2{} {
        abi_version=TPMSHX_PREPARATION_FLOW_3D_ABI_VERSION;struct_size=sizeof(tpmshx_preparation_flow_input_3d_v2);
        input=CaseInput3D{};target_kinds[0]=target_kinds[1]={64,0,0};
    }
};
struct ContinuousInput3D : tpmshx_preparation_continuous_input_3d_v3 {
    ContinuousInput3D():tpmshx_preparation_continuous_input_3d_v3{} {
        abi_version=TPMSHX_PREPARATION_CONTINUOUS_3D_ABI_VERSION;struct_size=sizeof(tpmshx_preparation_continuous_input_3d_v3);
        values=FlowInput3D{};values.input.geometry_mode=1;
    }
};
struct SpatialInput3D : tpmshx_preparation_spatial_input_3d_v4 {
    SpatialInput3D():tpmshx_preparation_spatial_input_3d_v4{} {
        abi_version=TPMSHX_PREPARATION_SPATIAL_3D_ABI_VERSION;struct_size=sizeof(tpmshx_preparation_spatial_input_3d_v4);
        values=FlowInput3D{};
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
inline tpmshx_stage_capture_2d_v1 capture_summary(const RunResult2D& result,
    const tpmshx_stage_application_2d_v1& application) {
    tpmshx_stage_capture_2d_v1 output{};
    detail::check(tpmshx_stage_run_2d_get_capture_v1(&result.view(),&application,&output),
        "native 2D capture summary failed");
    return output;
}

inline tpmshx_stage_capture_3d_v1 capture_summary(const RunResult3D& result,bool include_audit=false) {
    tpmshx_stage_capture_3d_v1 output{};
    detail::check(tpmshx_stage_run_3d_get_capture_v1(&result.view(),include_audit?1u:0u,&output),
        "native 3D capture summary failed");
    return output;
}

struct SavedCase3D : tpmshx_stage_saved_case_3d_v1 {
    SavedCase3D():tpmshx_stage_saved_case_3d_v1{} {
        abi_version=TPMSHX_STAGE_RUN_3D_ABI_VERSION;struct_size=sizeof(tpmshx_stage_saved_case_3d_v1);
        inlet_recorded=1;
    }
};
struct RunRequest3D : tpmshx_stage_run_request_3d_v1 {
    RunRequest3D():tpmshx_stage_run_request_3d_v1{} {
        abi_version=TPMSHX_STAGE_RUN_3D_ABI_VERSION;struct_size=sizeof(tpmshx_stage_run_request_3d_v1);
    }
};
struct RunControl3D : tpmshx_stage_run_control_3d_v1 {
    RunControl3D():tpmshx_stage_run_control_3d_v1{} {
        result_id="native-3d";cpu_threads=std::max(1u,std::thread::hardware_concurrency());
    }
};
// Keep the prepared owner alive and unchanged until take_result or release.
class Run3D {
public:
    Run3D(const PreparedCase3D& prepared,const RunControl3D& control,const RunRequest3D& request={},
        const RunState* state=nullptr):Run3D(&prepared.view(),nullptr,nullptr,control,request,state) {}
    Run3D(const PreparedFlowCase3D& prepared,const RunControl3D& control,const RunRequest3D& request={},
        const RunState* state=nullptr):Run3D(&prepared.view().prepared,nullptr,nullptr,control,request,state) {}
    Run3D(const PreparedContinuousCase3D& prepared,const RunControl3D& control,const RunRequest3D& request={},
        const RunState* state=nullptr):Run3D(nullptr,&prepared.view(),nullptr,control,request,state) {}
    Run3D(const PreparedSpatialCase3D& prepared,const RunControl3D& control,const RunRequest3D& request={},
        const RunState* state=nullptr):Run3D(nullptr,nullptr,&prepared.view(),control,request,state) {}
    Run3D(const tpmshx_stage_saved_case_3d_v1& saved,const RunControl3D& control,const RunRequest3D& request={},
        const RunState* state=nullptr) {
        char error[4096]{};
        const auto status=state?tpmshx_stage_run_3d_restore_saved_v1(&saved,&request,&control,
            state->view().fields,state->view().count,&run_,error,sizeof(error)):
            tpmshx_stage_run_3d_create_saved_v1(&saved,&request,&control,&run_,error,sizeof(error));
        detail::check(status,error);
    }
    ~Run3D() {tpmshx_stage_run_3d_release_run_v1(&run_);}
    Run3D(const Run3D&)=delete;
    Run3D& operator=(const Run3D&)=delete;
    Run3D(Run3D&& other) noexcept:run_(std::exchange(other.run_,nullptr)) {}
    Run3D& operator=(Run3D&& other) noexcept {
        if(this!=&other) {tpmshx_stage_run_3d_release_run_v1(&run_);run_=std::exchange(other.run_,nullptr);}
        return *this;
    }
    uint32_t phase() const {
        uint32_t value=0;
        detail::check(tpmshx_stage_run_3d_phase_v1(run_,&value),"invalid 3D stage run");return value;
    }
    uint32_t advance_step() {
        uint32_t value=0;char error[4096]{};
        detail::check(tpmshx_stage_run_3d_advance_step_v1(run_,&value,error,sizeof(error)),error);return value;
    }
    RunState snapshot() const {
        tpmshx_run_state_v1 value{};char error[4096]{};
        detail::check(tpmshx_stage_run_3d_snapshot_v1(run_,&value,error,sizeof(error)),error);return RunState(value);
    }
    RunResult3D take_result() {
        tpmshx_stage_run_result_3d_v1 value{};char error[4096]{};
        value.abi_version=TPMSHX_STAGE_RUN_3D_ABI_VERSION;value.struct_size=sizeof(value);
        detail::check(tpmshx_stage_run_3d_take_result_v1(run_,&value,error,sizeof(error)),error);return RunResult3D(value);
    }
private:
    Run3D(const tpmshx_preparation_case_3d_v1* uniform,const tpmshx_preparation_continuous_case_3d_v3* continuous,
        const tpmshx_preparation_spatial_case_3d_v4* spatial,const RunControl3D& control,const RunRequest3D& request,
        const RunState* state) {
        char error[4096]{};
        const auto status=state?tpmshx_stage_run_3d_restore_v1(uniform,continuous,spatial,&request,&control,
            state->view().fields,state->view().count,&run_,error,sizeof(error)):
            tpmshx_stage_run_3d_create_v1(uniform,continuous,spatial,&request,&control,&run_,error,sizeof(error));
        detail::check(status,error);
    }
    void* run_=nullptr;
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
    Run2D(const tpmshx_stage_saved_case_2d_v1& saved,const RunControl& control,const RunRequest2Dv3& request={},
        const RunState* state=nullptr) {
        char error[4096]{};
        const auto status=state?tpmshx_stage_run_2d_restore_saved_v1(&saved,&request,&control,
            state->view().fields,state->view().count,&run_,error,sizeof(error)):
            tpmshx_stage_run_2d_create_saved_v1(&saved,&request,&control,&run_,error,sizeof(error));
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
inline PreparedCase3D prepare_case(const CaseInput3D& input,const PreparationOptions& options={}) {
    tpmshx_preparation_case_3d_v1 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_CASE_3D_ABI_VERSION;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_prepare_case_3d_v1(&input,&options,nullptr,&output,&failure,error,sizeof(error)),error);
    return PreparedCase3D(output);
}
inline InletFlow3D prepare_inlet_mass_capacities(const FlowInput3D& input,const PreparationOptions& options={}) {
    tpmshx_preparation_flow_3d_v2 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_FLOW_3D_ABI_VERSION;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_prepare_inlet_mass_capacities_3d_v2(&input,&options,nullptr,&output,&failure,error,sizeof(error)),error);
    return InletFlow3D(output);
}
inline InletFlow3D resolve_inlet_flow(const FlowInput3D& input,const PreparationOptions& options={}) {
    tpmshx_preparation_flow_3d_v2 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_FLOW_3D_ABI_VERSION;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_resolve_inlet_flow_3d_v2(&input,&options,nullptr,&output,&failure,error,sizeof(error)),error);
    return InletFlow3D(output);
}
inline PreparedFlowCase3D prepare_case(const FlowInput3D& input,const PreparationOptions& options={}) {
    tpmshx_preparation_flow_case_3d_v2 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_FLOW_3D_ABI_VERSION;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_prepare_flow_case_3d_v2(&input,&options,nullptr,&output,&failure,error,sizeof(error)),error);
    return PreparedFlowCase3D(output);
}
inline ContinuousInletFlow3D prepare_inlet_mass_capacities(const ContinuousInput3D& input,const PreparationOptions& options={}) {
    tpmshx_preparation_continuous_flow_3d_v3 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_CONTINUOUS_3D_ABI_VERSION;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_prepare_inlet_mass_capacities_3d_v3(&input,&options,nullptr,&output,&failure,error,sizeof(error)),error);
    return ContinuousInletFlow3D(output);
}
inline ContinuousInletFlow3D resolve_inlet_flow(const ContinuousInput3D& input,const PreparationOptions& options={}) {
    tpmshx_preparation_continuous_flow_3d_v3 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_CONTINUOUS_3D_ABI_VERSION;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_resolve_inlet_flow_3d_v3(&input,&options,nullptr,&output,&failure,error,sizeof(error)),error);
    return ContinuousInletFlow3D(output);
}
inline PreparedContinuousCase3D prepare_case(const ContinuousInput3D& input,const PreparationOptions& options={}) {
    tpmshx_preparation_continuous_case_3d_v3 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_CONTINUOUS_3D_ABI_VERSION;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_prepare_flow_case_3d_v3(&input,&options,nullptr,&output,&failure,error,sizeof(error)),error);
    return PreparedContinuousCase3D(output);
}
inline SpatialInletFlow3D prepare_inlet_mass_capacities(const SpatialInput3D& input,const PreparationOptions& options={}) {
    tpmshx_preparation_spatial_flow_3d_v4 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_SPATIAL_3D_ABI_VERSION;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_prepare_inlet_mass_capacities_3d_v4(&input,&options,nullptr,&output,&failure,error,sizeof(error)),error);
    return SpatialInletFlow3D(output);
}
inline SpatialInletFlow3D resolve_inlet_flow(const SpatialInput3D& input,const PreparationOptions& options={}) {
    tpmshx_preparation_spatial_flow_3d_v4 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_SPATIAL_3D_ABI_VERSION;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_resolve_inlet_flow_3d_v4(&input,&options,nullptr,&output,&failure,error,sizeof(error)),error);
    return SpatialInletFlow3D(output);
}
inline PreparedSpatialCase3D prepare_case(const SpatialInput3D& input,const PreparationOptions& options={}) {
    tpmshx_preparation_spatial_case_3d_v4 output{};tpmshx_preparation_case_failure_v2 failure{};
    output.abi_version=TPMSHX_PREPARATION_SPATIAL_3D_ABI_VERSION;output.struct_size=sizeof(output);
    failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure.struct_size=sizeof(failure);
    char error[4096]{};
    detail::check(tpmshx_prepare_flow_case_3d_v4(&input,&options,nullptr,&output,&failure,error,sizeof(error)),error);
    return PreparedSpatialCase3D(output);
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
namespace detail {
inline RunResult3D run_3d(const tpmshx_preparation_case_3d_v1* uniform,
    const tpmshx_preparation_continuous_case_3d_v3* continuous,const tpmshx_preparation_spatial_case_3d_v4* spatial,
    const RunControl3D& control,const RunRequest3D& request) {
    tpmshx_stage_run_result_3d_v1 output{};char error[4096]{};
    output.abi_version=TPMSHX_STAGE_RUN_3D_ABI_VERSION;output.struct_size=sizeof(output);
    check(tpmshx_run_case_3d_v1(uniform,continuous,spatial,&request,&control,&output,error,sizeof(error)),error);
    return RunResult3D(output);
}
}
inline RunResult3D run_case(const PreparedCase3D& prepared,const RunControl3D& control,const RunRequest3D& request={}) {
    return detail::run_3d(&prepared.view(),nullptr,nullptr,control,request);
}
inline RunResult3D run_case(const PreparedFlowCase3D& prepared,const RunControl3D& control,const RunRequest3D& request={}) {
    return detail::run_3d(&prepared.view().prepared,nullptr,nullptr,control,request);
}
inline RunResult3D run_case(const PreparedContinuousCase3D& prepared,const RunControl3D& control,const RunRequest3D& request={}) {
    return detail::run_3d(nullptr,&prepared.view(),nullptr,control,request);
}
inline RunResult3D run_case(const PreparedSpatialCase3D& prepared,const RunControl3D& control,const RunRequest3D& request={}) {
    return detail::run_3d(nullptr,nullptr,&prepared.view(),control,request);
}
inline Evaluation evaluate(const RunResult3D& result,const tpmshx_stage_metric_spec_v1* metric=nullptr) {
    tpmshx_stage_output_v1 output{};output.struct_size=sizeof(output);char error[4096]{};
    tpmshx_result_diagnostics_v1 diagnostics{};uint64_t token=0;
    detail::check(tpmshx_result_stage_query_v2(&result.view().evaluation,0,metric,nullptr,0,
        &output,&diagnostics,&token,error,sizeof(error)),error);
    return Evaluation(output);
}
inline Evaluation evaluate(const RunResult2D& result,const tpmshx_stage_metric_spec_v1* metric=nullptr) {
    tpmshx_stage_output_v1 output{};output.struct_size=sizeof(output);
    char error[4096]{};
    detail::check(tpmshx_result_stage_evaluate_v1(&result.view().evidence,metric,&output,error,sizeof(error)),error);
    return Evaluation(output);
}
}  // namespace tpmshx::stages
