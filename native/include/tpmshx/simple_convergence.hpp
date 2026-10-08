#pragma once

#include "tpmshx/simple_pressure.hpp"

#include <array>
#include <limits>
#include <vector>

namespace tpmshx {

enum class SimpleStop { ongoing, tol, stall, max_iterations, nonfinite, cancelled, pressure_failure, post_closure };

struct SimpleF2Control {
    // Resolved caller settings; the native layer supplies no alternate gates.
    double momentum_tolerance, local_mass_tolerance, global_mass_tolerance;
    double backflow_maximum, velocity_check_tolerance, stall_ratio;
    std::size_t confirmations, momentum_interval, stall_window;
};

struct SimpleMomentumResidual {
    // u,v[,w] raw unrelaxed equations; an unused third component is zero.
    std::array<double, 3> numerator{}, denominator{}, component{};
    double maximum = std::numeric_limits<double>::quiet_NaN();
};

struct SimpleMomentumRecord { std::size_t iteration; SimpleMomentumResidual residual; };
struct SimpleHistory {
    std::vector<double> legacy, local_mass, global_mass;
    std::vector<SimpleMomentumRecord> momentum;
};

// Shared F2 scheduling/confirmation/stall logic. A new monitor starts on each
// solve call; the owning solver separately retains history across warm calls.
class SimpleF2Monitor {
public:
    SimpleF2Monitor(SimpleFacesView<const double> velocity,
                    const SimpleF2Control& control, std::size_t minimum_iterations);
    double velocity_delta(SimpleFacesView<const double> velocity);
    bool should_evaluate_momentum(std::size_t iteration, double velocity_delta) const;
    SimpleStop submit(std::size_t iteration, double momentum, const SimpleMassAudit& mass,
                      double velocity_delta);
    bool gates_hold(double momentum, const SimpleMassAudit& mass) const;
    // 3D post-closure rejection clears only its confirmation streak. Velocity
    // snapshots and the original momentum-stall window retain their history.
    void reset_confirmation() { streak_ = 0; }
private:
    SimpleF2Control control_;
    std::size_t minimum_iterations_, streak_ = 0, window_start_iteration_ = 0;
    double momentum_at_window_start_ = std::numeric_limits<double>::quiet_NaN();
    std::array<std::vector<double>, 3> previous_;
};

// Common denominator floor is 1e-3 * max(component denominators). Invalid
// raw observations remain NaN and cannot be hidden by a finite-only maximum.
void normalize_simple_momentum(SimpleMomentumResidual& residual, std::size_t components);

}  // namespace tpmshx
