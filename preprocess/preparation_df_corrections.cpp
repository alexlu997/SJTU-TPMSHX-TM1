#include "tpmshx/preparation_df.hpp"
#include "tpmshx/preparation_df_data.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <string>

namespace tpmshx::preparation {
namespace {
namespace data = df_data;
constexpr const char* fluid_names[] = {"air", "water", "sco2"};
bool at_geometry(ArrayView<const double> values, double target) {
    for (std::size_t i = 0; i < values.size; ++i) {
        const double value = values[i];
        if (!(std::abs(value - target) <= data::hx_geometry_absolute_tolerance)) return false;
    }
    return true;
}
double interpolate(double x, const double* values) {
    const auto& nodes = data::air_t_nodes;
    if (std::isnan(x)) return x;
    if (x <= nodes.front()) return values[0];
    if (x >= nodes.back()) return values[nodes.size() - 1];
    const auto index = static_cast<std::size_t>(std::upper_bound(nodes.begin(), nodes.end(), x) - nodes.begin() - 1);
    if (x == nodes[index]) return values[index];
    const double slope = (values[index + 1] - values[index]) / (nodes[index + 1] - nodes[index]);
    double result = slope * (x - nodes[index]) + values[index];
    if (std::isnan(result)) {
        result = slope * (x - nodes[index + 1]) + values[index + 1];
        if (std::isnan(result) && values[index] == values[index + 1]) result = values[index];
    }
    return result;
}
}  // namespace

DfSelection df_select(std::uint32_t topology, std::uint32_t fluid, bool transfer,
    ArrayView<const double> lengths, ArrayView<const double> walls,
    ArrayView<const double> velocity, bool has_velocity) {
    if (transfer && (topology != 1 || fluid > 1))
        throw std::invalid_argument("HX trend extrapolation is limited to Gyroid air/water");
    if (topology > 1) throw std::invalid_argument("experiment correction supports Diamond/Gyroid only");
    if (fluid > 2) throw std::invalid_argument("no approved experiment calibration for fluid");
    const bool geometry = at_geometry(lengths, data::hx_geometry_mm[0])
                       && at_geometry(walls, data::hx_geometry_mm[1]);
    DfSelection selected{};
    selected.scale_K = 1.;
    if (!transfer && fluid == 0 && !geometry) {
        selected.campaign = 0;
        selected.scope = 0;
        return selected;
    }
    if (!geometry)
        throw std::invalid_argument(std::string(fluid_names[fluid])
            + " HX experiment calibration is valid only for the matching D/G-7-6 geometry (L=7 mm, t=0.6 mm)");
    if (!has_velocity)
        throw std::invalid_argument(std::string(fluid_names[fluid])
            + " HX experiment calibration requires inlet velocity");
    for (std::size_t i = 0; i < velocity.size; ++i) {
        const double speed = velocity[i];
        if (!(std::isfinite(speed) && speed > 0.))
            throw std::invalid_argument("HX experiment calibration requires finite positive inlet velocity");
    }
    selected.branch = 1;
    selected.campaign = fluid == 2 ? 3u : (fluid == 0 && topology == 1 ? 2u : 1u);
    selected.scope = 1;
    selected.flags = 1u | (transfer ? 4u : 0u);
    selected.scale_F = data::hx_sf[fluid][topology];
    for (std::size_t i = 0; i < 2; ++i) {
        selected.application_u[i] = data::application_u[fluid][topology][i];
        selected.calibration_u[i] = data::calibration_u[fluid][topology][i];
        selected.runtime_u[i] = data::runtime_u[fluid][topology][i];
    }
    for (std::size_t i = 0; i < velocity.size; ++i) {
        const double speed = velocity[i];
        if (!transfer && (speed < selected.application_u[0] - data::hx_velocity_absolute_tolerance
                       || speed > selected.application_u[1] + data::hx_velocity_absolute_tolerance))
            throw std::invalid_argument("HX velocity outside application window");
        if (speed < selected.runtime_u[0] || speed > selected.runtime_u[1]) selected.flags |= 2u;
    }
    return selected;
}

std::vector<DfPair> df_scales(std::uint32_t topology, const DfSelection& selected,
    ArrayView<const double> lengths, ArrayView<const double> walls) {
    if (topology > 1 || selected.branch > 1 || lengths.size != walls.size)
        throw std::invalid_argument("correction fields or selection are invalid");
    std::vector<DfPair> result(lengths.size);
    if (selected.branch) {
        for (auto& value : result) value = {selected.scale_K, selected.scale_F};
        return result;
    }
    for (std::size_t i = 0; i < lengths.size; ++i)
        if (lengths[i] < data::air_L_nodes.front() || lengths[i] > data::air_L_nodes.back()
            || walls[i] < data::air_t_nodes.front() || walls[i] > data::air_t_nodes.back())
            throw std::invalid_argument("air experiment calibration is valid only for core specimens inside 6<=L<=8 mm and 0.3<=t<=0.5 mm; t=0.6 is not an experiment-supported extrapolation");
    for (std::size_t i = 0; i < lengths.size; ++i) {
        const double low = interpolate(walls[i], data::air_sf[topology][0]);
        const double high = interpolate(walls[i], data::air_sf[topology][1]);
        result[i] = {1., low + (lengths[i] - data::air_L_nodes.front()) * (high - low)
                           / (data::air_L_nodes.back() - data::air_L_nodes.front())};
    }
    return result;
}

std::vector<double> df_apply_scale(ArrayView<const double> base,
    ArrayView<const double> scale, bool prepared_scalar_factor) {
    if (base.size != scale.size) throw std::invalid_argument("correction fields must have matching extents");
    if (prepared_scalar_factor) {
        for (std::size_t i = 0; i < scale.size; ++i) {
            const double value = scale[i];
            if (!(std::isfinite(value) && value > 0.))
                throw std::invalid_argument("prepared experimental correction requires positive finite scalar factors");
        }
    }
    std::vector<double> output(base.size);
    for (std::size_t i = 0; i < base.size; ++i) output[i] = base[i] * scale[i];
    return output;
}

DfSummary df_summary(ArrayView<const double> values, bool scalar) {
    if (!values.size) throw std::invalid_argument("zero-size array to reduction operation minimum which has no identity");
    if (scalar) return {values[0], values[0], 1u};
    double low = values[0], high = values[0];
    for (std::size_t i = 1; i < values.size; ++i) {
        const double value = values[i];
        if (std::isnan(value)) { low = value; high = value; break; }
        low = value <= low ? value : low;
        high = value >= high ? value : high;
    }
    return {low, high, 0u};
}

DfPair df_co2_factors() { return {1. / data::co2_pressure_multiplier, data::co2_pressure_multiplier}; }

}  // namespace tpmshx::preparation
