#pragma once
#include "tpmshx/recorded_report.hpp"
#include "tpmshx/stage_run_c_api.h"

namespace tpmshx::stages {
using result::stage::Report;
Report::Object execution_report(const tpmshx_stage_execution_v1&, const tpmshx_result_evidence_v1&);
Report plane_balance(const tpmshx_model_h_result_v1&, size_t cells, double area);
Report volume_balance(const tpmshx_model_h_result_v1&, size_t cells);
}
