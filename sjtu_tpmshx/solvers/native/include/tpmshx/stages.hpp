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
