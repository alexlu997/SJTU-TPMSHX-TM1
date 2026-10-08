#pragma once

#include <cstddef>
#include <limits>
#include <memory>
#include <string>
#include <vector>

namespace tpmshx {

// Pressure system used by the native SIMPLE drivers. SuperLU is called only
// through the protected C allocation/ABORT boundary; no C++ frame is jumped.
// Canonical, sorted, duplicate-free square CSR, with 32-bit indices.
// pin_mask identifies the original zero-Dirichlet pressure-correction rows;
// these must be unit rows with b=0. No post-solve pin projection is applied.
struct PressureSystem {
    std::vector<int> row_offsets, columns;
    std::vector<double> values, rhs;
    std::vector<unsigned char> pin_mask;
};

struct PressureControl {
    int dimension = 3;  // 2D always LU; 3D uses AMG only for N>2000.
    double relative_tolerance = 1e-7;  // resolved SIMPLE value in [1e-7,1e-3]
    // The SIMPLE caller passes its existing 100-iteration cadence here.
    bool force_rebuild = false;
    double diagonal_drift_threshold = .05;  // zero disables drift rebuilding
};

struct PressureResult {
    bool success = false;
    std::string method, exit, amg_exit, rebuild_reason, detail;
    std::vector<double> x;  // empty on failed solve; never a placeholder result
    std::size_t iterations = 0, rebuild_count = 0, hierarchy_bytes = 0;
    int superlu_info = 0;
    double rhs_scale = 0., relative_residual = std::numeric_limits<double>::quiet_NaN();
    double absolute_residual = std::numeric_limits<double>::quiet_NaN();
    double iterative_relative_residual = std::numeric_limits<double>::quiet_NaN();
    double pin_max_abs = std::numeric_limits<double>::quiet_NaN(), diagonal_drift = 0.;
    double build_seconds = 0., solve_seconds = 0.;
};

// One instance owns one SIMPLE stream's cached AMG hierarchy. Every Krylov
// matvec uses the CURRENT matrix, including when the preconditioner is reused.
// The locked PyAMG 5.3 algorithm uses RS splitting, modified classical
// interpolation, symmetric pre/post GS, one V-cycle, coarse size 200, and SVD
// pseudo-inverse. SciPy 1.17.1 BiCGStab starts from zero, permits 200 iterations
// per attempt and retries a breakdown on an L2-normalized RHS, preserving the
// same hierarchy and tolerance. It is accepted only after the ORIGINAL Ax-b and
// pins pass. Known iterative nonconvergence/breakdown may fall back to LU;
// invalid inputs, unknown backend exceptions and nonfinite arithmetic do not.
class PressureCandidate {
public:
    PressureCandidate();
    ~PressureCandidate();
    PressureCandidate(const PressureCandidate&) = delete;
    PressureCandidate& operator=(const PressureCandidate&) = delete;
    PressureResult solve(const PressureSystem&, const PressureControl& = {});
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace tpmshx
