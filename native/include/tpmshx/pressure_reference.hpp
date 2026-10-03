#pragma once

#include "tpmshx/enthalpy_sweeps.hpp"

#include <optional>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace tpmshx {

// Existing rectangular-port overlap, including the spatial-ULP wall rule.
// staggered=true returns n+1 fractions on CVs between adjacent cell centres.
std::vector<double> port_overlap_1d(ArrayView<const double> widths,
                                    double lo, double hi, bool staggered = false);
// Geometric overlap and original imposed (optional four-cell tapered) profile.
std::pair<std::vector<double>,std::vector<double>> port_fractions_1d(
    ArrayView<const double> widths, double lo, double hi, bool uniform = false);

struct PressureIteration {
    std::string stage;
    double anchor_Pa;
    std::optional<double> estimate_Pa2, relative_error, target_Pa2, step_fraction;
    std::optional<std::string> method;
};

struct PressurePortState {
    double specified_Pa, realized_Pa, outlet_Pa, outlet_gauge_Pa, minimum_Pa;
    double relative_error, relative_tolerance;
    bool passed;
    std::string definition;
};

// Local SIMPLE coordinates: flow is +y, pressure is C-order (nx,ny,nz),
// geometric fractions are C-order (nx,nz). For 2D use nz=1,dz={1}.
// Extrapolate to physical faces and weight by geometric open area. These
// helpers preserve NaN/Inf pressure evidence; the resulting state then fails
// the finite inlet check or shooting update. Non-ideal-gas callers do not
// call inlet_pressure_state, matching Python's None branch.
PressurePortState inlet_pressure_state(
    const GridView& grid, ArrayView<const double> pressure,
    ArrayView<const double> inlet_fraction, ArrayView<const double> outlet_fraction,
    double reference_Pa, double specified_Pa);
double pressure_shooting_target_sq(const PressurePortState& state);
double pressure_initial_reference(double outlet_squared_Pa, double inlet_Pa,
                                  std::vector<PressureIteration>& history);
double pressure_shooting_reference(const PressurePortState& state,
                                   std::vector<PressureIteration>& history);

double predict_outlet_p_sq(double inlet_Pa, double temperature_K,
                           double drag_estimate, double length_m, double gas_constant);
double predict_outlet_p_sq(double inlet_Pa, double temperature_K,
                           double drag_estimate, double length_m);
double mach(double speed, double temperature_K, double gas_constant, double gamma);
double mach(double speed, double temperature_K);
double mach_field_max(ArrayView<const double> speed, ArrayView<const double> temperature,
                      double gas_constant, double gamma);
double mach_field_max(ArrayView<const double> speed, ArrayView<const double> temperature);

struct EnvelopeAssessment {
    bool valid;
    std::vector<std::string> reasons;
};
class ChokedFlowError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

// Defaults are sourced from the generated authoritative Python constants.
// Optional Ma is the actual local-field maximum, exactly as in Python.
EnvelopeAssessment assess_solution_validity(
    double minimum_Pa, double vmax, double reference_temperature_K,
    double mach_limit = 1.0, std::optional<double> ma_max = std::nullopt);
EnvelopeAssessment gate_solution(
    double minimum_Pa, double vmax, double reference_temperature_K,
    const std::string& mode = "raise", const std::string& dimensions = "3D",
    double mach_limit = 1.0, std::optional<double> ma_max = std::nullopt);
// Explicit R/gamma overloads preserve custom ideal-gas callers.
EnvelopeAssessment assess_solution_validity(
    double minimum_Pa, double vmax, double reference_temperature_K,
    double mach_limit, double gas_constant, double gamma, std::optional<double> ma_max);
EnvelopeAssessment gate_solution(
    double minimum_Pa, double vmax, double reference_temperature_K,
    const std::string& mode, const std::string& dimensions,
    double mach_limit, double gas_constant, double gamma, std::optional<double> ma_max);

}  // namespace tpmshx
