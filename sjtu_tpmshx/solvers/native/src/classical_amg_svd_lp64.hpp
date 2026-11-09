#pragma once

#include <Eigen/Core>

namespace tpmshx::classical_detail {

// Private macOS boundary for the locked SciPy coarse-grid SVD.
// Outputs retain their caller-provided sizes; LAPACK integer types stay local.
void coarse_svd_lp64(Eigen::MatrixXd& dense, Eigen::MatrixXd& u,
                     Eigen::VectorXd& singular, Eigen::MatrixXd& vt);

} // namespace tpmshx::classical_detail
