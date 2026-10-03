#include "tpmshx/simple_convergence.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace tpmshx {
namespace {
bool finite_mass(const SimpleMassAudit& mass) {
    return std::isfinite(mass.local_residual) && std::isfinite(mass.global_residual)
        && std::isfinite(mass.backflow_fraction);
}
}

SimpleF2Monitor::SimpleF2Monitor(SimpleFacesView<const double> velocity,
    const SimpleF2Control& control, std::size_t minimum_iterations)
    : control_(control), minimum_iterations_(minimum_iterations) {
    const double values[] = {control.momentum_tolerance, control.local_mass_tolerance,
        control.global_mass_tolerance, control.backflow_maximum,
        control.velocity_check_tolerance, control.stall_ratio};
    for (double value : values)
        if (!std::isfinite(value) || value < 0.) throw std::invalid_argument("invalid SIMPLE F2 control");
    if (control.confirmations == 0 || control.momentum_interval == 0)
        throw std::invalid_argument("SIMPLE confirmation and momentum intervals must be positive");
    const ArrayView<const double> arrays[] = {velocity.u, velocity.v, velocity.w};
    for (std::size_t c = 0; c < 3; ++c)
        if (arrays[c].size) previous_[c].assign(arrays[c].data, arrays[c].data + arrays[c].size);
}

double SimpleF2Monitor::velocity_delta(SimpleFacesView<const double> velocity) {
    const ArrayView<const double> arrays[] = {velocity.u, velocity.v, velocity.w};
    double maximum = 0., scale = 1e-30;
    for (std::size_t c = 0; c < 3; ++c) {
        if (previous_[c].size() != arrays[c].size)
            throw std::invalid_argument("SIMPLE velocity shape changed inside one solve");
        for (std::size_t i = 0; i < arrays[c].size; ++i) {
            const double value = arrays[c][i], delta = std::abs(value - previous_[c][i]);
            if (!std::isfinite(value) || !std::isfinite(delta))
                return std::numeric_limits<double>::quiet_NaN();
            maximum = std::max(maximum, delta);
            scale = std::max(scale, std::abs(value));
            previous_[c][i] = value;
        }
    }
    return maximum / scale;
}

bool SimpleF2Monitor::should_evaluate_momentum(std::size_t iteration, double delta) const {
    if (iteration < minimum_iterations_) return false;
    return streak_ > 0 || delta < control_.velocity_check_tolerance
        || iteration % control_.momentum_interval == 0;
}

bool SimpleF2Monitor::gates_hold(double momentum, const SimpleMassAudit& mass) const {
    return std::isfinite(momentum) && finite_mass(mass)
        && momentum < control_.momentum_tolerance
        && mass.local_residual < control_.local_mass_tolerance
        && mass.global_residual < control_.global_mass_tolerance
        && mass.backflow_fraction <= control_.backflow_maximum;
}

SimpleStop SimpleF2Monitor::submit(std::size_t iteration, double momentum,
    const SimpleMassAudit& mass, double delta) {
    if (!std::isfinite(momentum) || !finite_mass(mass) || !std::isfinite(delta)) {
        streak_ = 0;
        return SimpleStop::nonfinite;
    }
    if (iteration < minimum_iterations_) return SimpleStop::ongoing;
    if (gates_hold(momentum, mass)) {
        ++streak_;
        return streak_ >= control_.confirmations ? SimpleStop::tol : SimpleStop::ongoing;
    }
    streak_ = 0;
    if (std::isnan(momentum_at_window_start_)
        || iteration - window_start_iteration_ >= control_.stall_window) {
        if (!std::isnan(momentum_at_window_start_)
            && delta < 10. * control_.velocity_check_tolerance
            && momentum > momentum_at_window_start_ * (1. - control_.stall_ratio))
            return SimpleStop::stall;
        momentum_at_window_start_ = momentum;
        window_start_iteration_ = iteration;
    }
    return SimpleStop::ongoing;
}

void normalize_simple_momentum(SimpleMomentumResidual& residual, std::size_t components) {
    if (components != 2 && components != 3)
        throw std::invalid_argument("SIMPLE momentum has two or three components");
    double floor = 0.;
    for (std::size_t c = 0; c < components; ++c) {
        if (!std::isfinite(residual.numerator[c]) || !std::isfinite(residual.denominator[c])) {
            residual.component.fill(std::numeric_limits<double>::quiet_NaN());
            residual.maximum = std::numeric_limits<double>::quiet_NaN();
            return;
        }
        floor = std::max(floor, residual.denominator[c]);
    }
    floor *= 1e-3;
    residual.maximum = 0.;
    for (std::size_t c = 0; c < components; ++c) {
        const double denominator = std::max(residual.denominator[c], floor);
        residual.component[c] = denominator > 0. ? residual.numerator[c] / denominator : 0.;
        residual.maximum = std::max(residual.maximum, residual.component[c]);
    }
}

}  // namespace tpmshx
