#include "tpmshx/pressure_candidate.hpp"
#include "tpmshx/superlu_solve.h"
#include "classical_amg.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace tpmshx {
namespace {
using Clock = std::chrono::steady_clock;
constexpr double direct_residual_tolerance = 1e-10;
constexpr double pin_tolerance = 1e-10;
constexpr std::size_t amg_gate = 2000, iteration_limit = 200;

double seconds(Clock::time_point start) {
    return std::chrono::duration<double>(Clock::now()-start).count();
}

double norm(const std::vector<double>& x) {
    double result = 0.;
    for (const auto v : x) result = std::hypot(result,v);
    if (!std::isfinite(result)) throw std::domain_error("nonfinite pressure vector norm");
    return result;
}

std::vector<double> validate(const PressureSystem& a, const PressureControl& control) {
    const auto n = a.rhs.size(), nnz = a.values.size();
    if (!n || n > static_cast<std::size_t>(std::numeric_limits<int>::max())
        || nnz > static_cast<std::size_t>(std::numeric_limits<int>::max())
        || a.row_offsets.size() != n+1 || a.columns.size() != nnz
        || a.pin_mask.size() != n || a.row_offsets.front() != 0
        || a.row_offsets.back() != static_cast<int>(nnz))
        throw std::invalid_argument("invalid pressure CSR extents");
    if ((control.dimension != 2 && control.dimension != 3)
        || !std::isfinite(control.relative_tolerance)
        || control.relative_tolerance < 1e-7 || control.relative_tolerance > 1e-3
        || !std::isfinite(control.diagonal_drift_threshold)
        || control.diagonal_drift_threshold < 0.)
        throw std::invalid_argument("invalid pressure controls");
    std::vector<double> diagonal;
    diagonal.reserve(n);
    bool have_pin = false;
    for (std::size_t row = 0; row < n; ++row) {
        const int begin = a.row_offsets[row], end = a.row_offsets[row+1];
        if (begin < 0 || end <= begin || end > static_cast<int>(nnz)
            || !std::isfinite(a.rhs[row]) || a.pin_mask[row] > 1)
            throw std::invalid_argument("invalid pressure CSR row, rhs or pin mask");
        int previous = -1;
        double d = 0.;
        bool unit = true;
        for (int k = begin; k < end; ++k) {
            const auto col = a.columns[k];
            const auto value = a.values[k];
            if (col <= previous || col < 0 || col >= static_cast<int>(n) || !std::isfinite(value))
                throw std::invalid_argument("pressure CSR must be finite, sorted and duplicate-free");
            previous = col;
            if (col == static_cast<int>(row)) d = value;
            else if (value != 0.) unit = false;
        }
        if (!(d > 0.)) throw std::invalid_argument("pressure diagonal must be positive");
        if (a.pin_mask[row]) {
            have_pin = true;
            if (!unit || d != 1. || a.rhs[row] != 0.)
                throw std::invalid_argument("pressure pin must be an original unit row with zero rhs");
        } else {
            diagonal.push_back(d);
        }
    }
    if (!have_pin) throw std::invalid_argument("pressure correction requires a recorded Dirichlet pin");
    return diagonal;
}

void audit(const PressureSystem& a, const std::vector<double>& x, PressureResult& result) {
    std::vector<double> residual(a.rhs.size());
    result.pin_max_abs = 0.;
    for (std::size_t row = 0; row < a.rhs.size(); ++row) {
        if (!std::isfinite(x[row])) throw std::domain_error("nonfinite pressure solution");
        double product = 0.;
        for (int k = a.row_offsets[row]; k < a.row_offsets[row+1]; ++k)
            product += a.values[k]*x[a.columns[k]];
        residual[row] = product-a.rhs[row];
        if (a.pin_mask[row]) result.pin_max_abs = std::max(result.pin_max_abs,std::abs(x[row]));
    }
    result.absolute_residual = norm(residual);
    const double bnorm = norm(a.rhs);
    result.relative_residual = bnorm == 0. ? result.absolute_residual : result.absolute_residual/bnorm;
    if (!std::isfinite(result.relative_residual)) throw std::domain_error("nonfinite original pressure residual");
}

void direct(const PressureSystem& a, PressureResult& result) {
    const auto started = Clock::now();
    const int n = static_cast<int>(a.rhs.size()), nnz = static_cast<int>(a.values.size());
    std::vector<int> perm_c(n), perm_r(n);
    std::vector<double> values = a.values, x = a.rhs;
    // Every potentially aborting library call is inside one pure C region;
    // errors return normally to this C++ frame, preserving vector lifetimes.
    tpmshx_superlu_result linear{};
    // spsolve receives CSR in the Python SIMPLE owner. Retain SuperLU's
    // SLU_NR/transpose route, whose rounding can affect the SOU branch history.
    const int status = tpmshx_superlu_solve_csr(n,nnz,a.row_offsets.data(),a.columns.data(),values.data(),
        x.data(),perm_c.data(),perm_r.data(),&linear);
    result.solve_seconds += seconds(started);
    const int info = linear.info;
    result.superlu_info = info;
    if (status != TPMSHX_SUPERLU_OK) {
        result.exit = status == TPMSHX_SUPERLU_ALLOCATION
            ? "superlu_allocation_failure" : "superlu_abort";
        result.detail = linear.message;
        return;
    }
    if (info != 0) {
        result.exit = info < 0 ? "superlu_invalid_argument"
            : (info <= n ? "singular" : "superlu_allocation_failure");
        return;
    }
    audit(a,x,result);
    result.success = result.relative_residual <= direct_residual_tolerance && result.pin_max_abs <= pin_tolerance;
    result.exit = result.success ? "solved" : "direct_residual_failure";
    if (result.success) result.x = std::move(x);
}

}  // namespace

struct PressureCandidate::Impl {
    std::unique_ptr<classical_detail::ClassicalAmg> hierarchy;
    std::vector<int> row_offsets, columns;
    std::vector<unsigned char> pins;
    std::vector<double> diagonal;
    std::size_t rebuild_count = 0;
};

PressureCandidate::PressureCandidate() : impl_(std::make_unique<Impl>()) {}
PressureCandidate::~PressureCandidate() = default;

PressureResult PressureCandidate::solve(const PressureSystem& a, const PressureControl& control) {
    const auto current_diagonal = validate(a,control);
    PressureResult result;
    result.rebuild_count = impl_->rebuild_count;
    const auto n = a.rhs.size();
    if (control.dimension == 2 || n <= amg_gate) {
        result.method = "superlu_colamd";
        direct(a,result);
        return result;
    }
    result.method = "pyamg_classical_bicgstab";
    if (!impl_->hierarchy) result.rebuild_reason = "cold";
    else if (impl_->row_offsets != a.row_offsets || impl_->columns != a.columns || impl_->pins != a.pin_mask)
        result.rebuild_reason = "pattern_or_pins_changed";
    else if (control.force_rebuild) result.rebuild_reason = "caller_cadence";
    else if (control.diagonal_drift_threshold > 0.) {
        std::vector<double> difference(current_diagonal.size());
        for (std::size_t i = 0; i < difference.size(); ++i) difference[i] = current_diagonal[i]-impl_->diagonal[i];
        const double previous = norm(impl_->diagonal);
        if (previous > 0.) result.diagonal_drift = norm(difference)/previous;
        if (result.diagonal_drift > control.diagonal_drift_threshold) result.rebuild_reason = "active_diagonal_drift";
    }
    if (!result.rebuild_reason.empty()) {
        const auto started = Clock::now();
        auto hierarchy = std::make_unique<classical_detail::ClassicalAmg>(a);
        impl_->hierarchy = std::move(hierarchy);
        impl_->row_offsets = a.row_offsets;
        impl_->columns = a.columns;
        impl_->pins = a.pin_mask;
        impl_->diagonal = current_diagonal;
        result.rebuild_count = ++impl_->rebuild_count;
        result.build_seconds = seconds(started);
    }
    result.hierarchy_bytes = impl_->hierarchy->bytes();
    const double rhs_norm=norm(a.rhs);
    if (rhs_norm == 0.) {
        result.x.assign(n,0.);
        audit(a,result.x,result);
        result.success = true;
        result.exit = result.amg_exit = "zero_rhs";
        return result;
    }
    const auto started = Clock::now();
    result.rhs_scale=1.;
    auto attempt=impl_->hierarchy->solve(a,a.rhs,control.relative_tolerance,iteration_limit);
    result.iterations=attempt.iterations;
    if(attempt.info<0) {
        // Original owner retries only an actual SciPy eps^2 breakdown, using
        // the same hierarchy and relative tolerance on an L2-normalized RHS.
        result.rhs_scale=rhs_norm;
        std::vector<double> scaled_rhs(n);
        for(std::size_t i=0;i<n;++i)scaled_rhs[i]=a.rhs[i]/rhs_norm;
        attempt=impl_->hierarchy->solve(a,scaled_rhs,control.relative_tolerance,iteration_limit);
        result.iterations+=attempt.iterations;
        for(double& value:attempt.x)value*=rhs_norm;
    }
    audit(a,attempt.x,result);
    result.iterative_relative_residual=result.relative_residual;
    result.success=attempt.info==0 && result.relative_residual<=control.relative_tolerance && result.pin_max_abs<=pin_tolerance;
    result.amg_exit=result.success?"solved":attempt.info<0?"breakdown":attempt.info>0?"max_iterations":"original_residual_failure";
    if(attempt.info<0)result.detail="SciPy-compatible BiCGStab breakdown info="+std::to_string(attempt.info);
    result.hierarchy_bytes=impl_->hierarchy->bytes();
    result.solve_seconds = seconds(started);
    if (result.success) {
        result.exit = "solved";
        result.x = std::move(attempt.x);
    } else {
        result.method = "superlu_after_amg";
        direct(a,result);
    }
    return result;
}
}  // namespace tpmshx
