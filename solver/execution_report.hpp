#pragma once
#include <cstdio>
#include <mutex>
#include "tpmshx/recorded_report.hpp"
#include "tpmshx/stage_run_c_api.h"

namespace tpmshx::stages {
using result::stage::Report;
class ExecutionReport {
    std::once_flag once_;
    std::string json_;
public:
    template<class Build>
    const char* read(Build build, char* error, size_t capacity) {
        if (!error || !capacity) return nullptr;
        try {
            std::call_once(once_, [&] { json_ = result::stage::json(build()); });
            error[0] = 0;
            return json_.c_str();
        } catch (const std::exception& reason) {
            std::snprintf(error, capacity, "%s", reason.what());
            return nullptr;
        }
    }
};
Report::Object execution_report(const tpmshx_stage_execution_v1&, const tpmshx_result_evidence_v1&);
Report plane_balance(const tpmshx_model_h_result_v1&, size_t cells, double area);
Report volume_balance(const tpmshx_model_h_result_v1&, size_t cells);
}
