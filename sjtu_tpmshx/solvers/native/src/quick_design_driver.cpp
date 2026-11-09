#include "tpmshx/quick_design_driver.hpp"

#include <cmath>
#include <limits>
#include <numeric>
#include <sstream>
#include <string>
#include <vector>

namespace tpmshx {
namespace {

std::size_t count(const GridView& grid) {
    const auto maximum = std::numeric_limits<std::size_t>::max();
    if (!grid.nx || !grid.ny || !grid.nz || grid.nx > maximum/grid.ny
        || grid.nx*grid.ny > maximum/grid.nz)
        throw std::invalid_argument("invalid quick-design grid extent");
    return grid.nx*grid.ny*grid.nz;
}

void extent(ArrayView<const double> widths, std::size_t size, double length) {
    if (!widths.data || widths.size != size || !std::isfinite(length) || length <= 0.)
        throw std::invalid_argument("invalid quick-design physical extent");
    double sum = 0.;
    for (std::size_t i = 0; i < size; ++i) {
        if (!std::isfinite(widths[i]) || widths[i] <= 0.)
            throw std::invalid_argument("invalid quick-design grid width");
        sum += widths[i];
    }
    if (std::abs(sum-length) > 1e-12*std::abs(length))
        throw std::invalid_argument("prepared grid disagrees with physical extent");
}

double uniform(ArrayView<const double> field, std::size_t n) {
    if (!field.data || field.size != n || !std::isfinite(field[0]))
        throw std::invalid_argument("invalid quick-design prepared field");
    for (std::size_t i = 1; i < n; ++i)
        if (field[i] != field[0])
            throw std::invalid_argument("quick-design requires finite uniform fields");
    return field[0];
}

std::string location(const GridView& grid, std::size_t p, double temperature,
                     double pressure, const std::string& where) {
    std::ostringstream text;
    text << where << ": water index=(" << p/(grid.ny*grid.nz) << ", "
         << (p/grid.nz)%grid.ny << ", " << p%grid.nz << "), T=" << temperature
         << " K, P_abs=" << pressure << " Pa: ";
    return text.str();
}

void finite_fields(const GridView& grid, TemperatureStateView state, const std::string& where) {
    const std::array<ArrayView<double>,3> fields{state.a,state.b,state.solid};
    const std::array<const char*,3> names{"A","B","solid"};
    for (std::size_t side = 0; side < fields.size(); ++side)
        for (std::size_t p = 0; p < fields[side].size; ++p)
            if (!std::isfinite(fields[side][p])) {
                std::ostringstream text;
                text << where << ": " << names[side] << " temperature index=("
                     << p/(grid.ny*grid.nz) << ", " << (p/grid.nz)%grid.ny << ", "
                     << p%grid.nz << ") is non-finite";
                throw std::invalid_argument(text.str());
            }
}

void water_fields(PropertyEvaluator& evaluator, const GridView& grid,
                  const std::array<QuickDesignSide,2>& sides, TemperatureStateView state,
                  const std::string& where) {
    const std::array<ArrayView<double>,2> fields{state.a,state.b};
    for (std::size_t side = 0; side < 2; ++side) {
        if (sides[side].fluid != Fluid::water) continue;
        for (std::size_t p = 0; p < fields[side].size; ++p)
            try { evaluator.check_water(fields[side][p],sides[side].inlet_pressure); }
            catch (const WaterStateError& error) {
                throw QuickDesignWaterFieldError(location(grid,p,fields[side][p],
                    sides[side].inlet_pressure,where+(side == 0 ? " A" : " B"))+error.what());
            }
    }
}

double outlet_mean(ArrayView<double> field, const GridView& grid, int direction) {
    double total = 0.;
    std::size_t n = 0;
    for (std::size_t i = 0; i < grid.nx; ++i)
        for (std::size_t j = 0; j < grid.ny; ++j)
            if ((direction == 0 && i+1 == grid.nx) || (direction == 1 && i == 0)
                || (direction == 2 && j+1 == grid.ny))
                for (std::size_t k = 0; k < grid.nz; ++k) {
                    total += field[(i*grid.ny+j)*grid.nz+k];
                    ++n;
                }
    return total/static_cast<double>(n);
}

struct PassControl {
    const QuickDesignControl& outer;
    std::size_t index, total;
};

bool cancelled(void* pointer) {
    const auto& pass = *static_cast<PassControl*>(pointer);
    return pass.outer.cancel && pass.outer.cancel(pass.outer.context);
}

void progress(void* pointer, std::size_t done, std::size_t budget) {
    const auto& pass = *static_cast<PassControl*>(pointer);
    if (pass.outer.progress)
        pass.outer.progress(pass.outer.context,static_cast<unsigned>(
            (static_cast<double>(pass.index)+static_cast<double>(done)/static_cast<double>(budget))
            *100./static_cast<double>(pass.total)));
}

ArrayView<const double> view(const std::vector<double>& x) { return {x.data(),x.size()}; }
}  // namespace

QuickDesignResult solve_quick_design(
    const GridView& grid, const QuickDesignGeometry& geometry,
    Topology topology, QuickDesignArrangement arrangement,
    QuickDesignProperties property_mode, const QuickDesignSide& a,
    const QuickDesignSide& b, TemperatureStateView state,
    const QuickDesignControl& control) {
    QuickDesignResult result{};
    result.stop = TemperatureStop::cancelled;
    if (control.cancel && control.cancel(control.context)) return result;
    const auto n = count(grid);
    if ((arrangement != QuickDesignArrangement::cross && arrangement != QuickDesignArrangement::counter)
        || (property_mode != QuickDesignProperties::constant && property_mode != QuickDesignProperties::mean))
        throw std::invalid_argument("unsupported quick-design arrangement or property model");
    extent(grid.dx,grid.nx,geometry.length);
    extent(grid.dy,grid.ny,geometry.span);
    extent(grid.dz,grid.nz,geometry.height);
    const double eps = uniform(geometry.epsilon,n), eps_a = uniform(geometry.epsilon_a,n);
    const double ks = uniform(geometry.k_ss,n);
    if (eps <= 0. || eps >= 1. || std::abs(eps_a-eps/2.) > 1e-12*std::abs(eps/2.) || ks <= 0.)
        throw std::invalid_argument("quick-design requires positive symmetric porosity and solid conduction");
    for (const double value : {geometry.cell_length,geometry.area_density,geometry.hydraulic_diameter})
        if (!std::isfinite(value) || value <= 0.)
            throw std::invalid_argument("quick-design geometry scalar must be finite and positive");
    if (!control.max_iterations || !control.chunk_iterations || !std::isfinite(control.alpha)
        || control.alpha <= 0. || control.alpha > 1. || !std::isfinite(control.q_relative_tolerance)
        || control.q_relative_tolerance <= 0. || (grid.nz == 1 && control.alpha != .7))
        throw std::invalid_argument("invalid quick-design numerical controls");
    for (const auto field : {state.a,state.b,state.solid})
        if (!field.data || field.size != n)
            throw std::invalid_argument("quick-design state disagrees with prepared grid");
    const std::array<QuickDesignSide,2> sides{a,b};
    PropertyEvaluator evaluator;
    for (std::size_t side = 0; side < 2; ++side) {
        const auto& f = sides[side];
        if (!std::isfinite(f.inlet_pressure_fraction) || f.inlet_pressure_fraction < 0.)
            throw std::invalid_argument("quick-design requires prepared nonnegative inlet pressure fractions");
        if (!std::isfinite(f.mass_flow) || f.mass_flow <= 0.)
            throw std::invalid_argument("quick-design requires finite positive mass flow");
        if (f.fluid == Fluid::water)
            try { evaluator.check_water(f.inlet_temperature,f.inlet_pressure); }
            catch (const WaterStateError& error) {
                throw WaterStateError(std::string("design inlet ")+(side == 0 ? "A: " : "B: ")+error.what());
            }
        result.pressure[side] = {f.inlet_pressure,f.inlet_pressure*(1.-f.inlet_pressure_fraction),
                                f.inlet_pressure_fraction >= 1.};
    }
    if (control.warm_start) {
        finite_fields(grid,state,"design external warm start");
        water_fields(evaluator,grid,sides,state,"design external warm start");
    }
    const std::size_t passes = property_mode == QuickDesignProperties::mean ? 2 : 1;
    const bool cross = arrangement == QuickDesignArrangement::cross;
    std::array<double,2> evaluation{a.inlet_temperature,b.inlet_temperature};
    const std::vector<double> zero(n,0.);
    std::array<std::vector<double>,2> conductivity, hv, capacity, speed;
    for (std::size_t index = 0; index < passes; ++index) {
        if (control.cancel && control.cancel(control.context)) return result;
        const std::string stage = index == 0 ? "design-inlet-pass" : "design-mean-pass";
        auto& pass = result.passes[index];
        for (std::size_t side = 0; side < 2; ++side) {
            auto& output = pass.sides[side];
            output.evaluation_temperature = evaluation[side];
            try { output.properties = evaluator.evaluate(sides[side].fluid,evaluation[side],sides[side].inlet_pressure); }
            catch (const WaterStateError& error) {
                throw WaterStateError(stage+(side == 0 ? " A properties: " : " B properties: ")+error.what());
            }
            const auto& props = output.properties;
            const double span = side == 1 && cross ? geometry.length : geometry.span;
            output.speed = sides[side].mass_flow/(props.rho*(eps_a*span*geometry.height));
            output.reynolds = props.rho*std::abs(output.speed)*geometry.hydraulic_diameter/props.mu;
            const double nu = evaluator.quick_design_nu(sides[side].fluid,topology,output.reynolds,
                                                        geometry.cell_length,geometry.hydraulic_diameter);
            output.hv = geometry.area_density*nu*props.k/geometry.hydraulic_diameter;
            output.conductivity = eps_a*props.k;
            conductivity[side].assign(n,output.conductivity);
            hv[side].assign(n,output.hv);
            capacity[side].assign(n,props.rho*props.cp);
            speed[side].assign(n,side == 1 && !cross ? -output.speed : output.speed);
        }
        TemperatureFluidView fa{view(conductivity[0]),view(hv[0]),geometry.epsilon_a,view(capacity[0]),
            view(speed[0]),view(zero),view(zero),{0,a.inlet_temperature}};
        TemperatureFluidView fb{view(conductivity[1]),view(hv[1]),geometry.epsilon_a,view(capacity[1]),
            cross ? view(zero) : view(speed[1]),cross ? view(speed[1]) : view(zero),view(zero),
            {cross ? 2 : 1,b.inlet_temperature}};
        PassControl pass_control{control,index,passes};
        const bool plane = grid.nz == 1;
        TemperatureControl thermal{control.max_iterations,control.chunk_iterations,control.q_relative_tolerance,
            control.alpha,plane ? 1. : control.alpha,plane ? 1. : control.alpha,
            control.warm_start || index > 0,!plane,cancelled,progress,&pass_control};
        pass.thermal = solve_temperature(plane ? TemperatureScheme::cell_centered_2d : TemperatureScheme::cell_centered_3d,
                                        grid,fa,fb,geometry.k_ss,state,thermal);
        if (pass.thermal.stop == TemperatureStop::cancelled) return result;
        finite_fields(grid,state,"design thermal return");
        water_fields(evaluator,grid,sides,state,stage+" thermal return");
        ++result.completed_passes;
        evaluation = {.5*(a.inlet_temperature+outlet_mean(state.a,grid,0)),
                      .5*(b.inlet_temperature+outlet_mean(state.b,grid,cross ? 2 : 1))};
    }
    if (control.cancel && control.cancel(control.context)) return result;
    if (control.progress) control.progress(control.context,100);
    if (control.cancel && control.cancel(control.context)) return result;
    result.stop = result.passes[result.completed_passes-1].thermal.stop;
    return result;
}

}  // namespace tpmshx
