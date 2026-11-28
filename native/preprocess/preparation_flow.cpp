#include "tpmshx/preparation_flow.hpp"
#include "tpmshx/grid.hpp"
#include "tpmshx/ports.hpp"
#include "../numerics/contiguous_sum.hpp"
#include <cmath>
#include <stdexcept>
#include <vector>

namespace tpmshx::preparation {
namespace {
namespace g=grid;
double sum(const std::vector<double>& values) {
    return 0.+detail::contiguous_sum({values.data(),values.size()});
}
double products_sum(FlowValues first,FlowValues second) {
    std::vector<double> products(first.size);
    for (std::size_t i=0;i<products.size();++i) products[i]=first[i]*second[i];
    return sum(products);
}
bool target_required(double denominator) {return std::abs(denominator)>1e-9;}
}  // namespace

double inlet_capacity_2d(FlowValues epsilon,FlowValues opening,FlowValues geometric,
    FlowValues widths,double rho,double depth) {
    bool tapered=false;
    for (std::size_t i=0;i<opening.size;++i)
        tapered=tapered || opening[i]!=geometric[i];
    double scale=1.;
    if (tapered) {
        const double geometric_area=products_sum(geometric,widths);
        const double profile_area=products_sum(opening,widths);
        scale=tpmshx::inlet_profile_scale(tapered,geometric_area,profile_area);
    }
    std::vector<double> products(epsilon.size);
    for (std::size_t i=0;i<products.size();++i) products[i]=epsilon[i]*.5*opening[i]*widths[i];
    return rho*sum(products)*depth*scale;
}

double inlet_capacity_3d(FlowValues epsilon,const std::array<std::size_t,3>& shape,
    std::int32_t direction,FlowValues widths1,FlowValues widths2,FlowValues opening,double rho) {
    const auto axes=g::axis_map(direction);
    const auto cross1=static_cast<std::size_t>(axes[0]),stream=static_cast<std::size_t>(axes[1]);
    const auto cross2=static_cast<std::size_t>(axes[2]);
    std::vector<double> products(opening.size);
    std::array<std::size_t,3> coordinate{};
    coordinate[stream]=axes[6]?shape[stream]-1:0;
    for (std::size_t i=0;i<widths1.size;++i) {
        coordinate[cross1]=i;
        for (std::size_t j=0;j<widths2.size;++j) {
            coordinate[cross2]=j;
            const auto flat=(coordinate[0]*shape[1]+coordinate[1])*shape[2]+coordinate[2];
            const auto face=i*widths2.size+j;
            products[face]=epsilon[flat]*opening[face]*(widths1[i]*widths2[j]);
        }
    }
    return rho*sum(products);
}

double inlet_speed(double target,double capacity) {return g::divide(target,capacity);}

std::array<double,4> quick_design_sections(double epsilon,double width,double length,double height,bool cross) {
    const double area_hot=epsilon*width*height;
    const double area_cold=epsilon*(cross?length:width)*height;
    return {area_hot,length,area_cold,cross?width:length};
}

std::array<double,2> quick_design_flow(double mass_flow,double area,double density,bool air) {
    const double flux=g::divide(mass_flow,area);
    return {flux,air?0.:g::divide(flux,density)};
}

double relative_pressure(double pressure_drop,double inlet_pressure) {
    return g::divide(pressure_drop,inlet_pressure);
}

double design_temperature_target(double temperature,bool has_delta,double delta,
    double duty,double mass_flow,double heat_capacity) {
    return temperature-(has_delta?delta:g::divide(duty,mass_flow*heat_capacity));
}

double design_cooling_proxy(double hot,double cold,double target,double mass_flow) {
    const double denominator=hot-cold;
    const double required=target_required(denominator)?g::divide(hot-target,denominator):0.;
    return required*mass_flow;
}

bool cooling_proxy_needs_target(double hot,double cold) {
    return target_required(hot-cold);
}

double design_volume(double width,double height,double length) {
    return width*height*length;
}

std::vector<double> closure_geometry_ratio(FlowValues diameter,FlowValues cell) {
    std::vector<double> result(diameter.size);
    for (std::size_t i=0;i<result.size();++i) result[i]=diameter[i]*1000./cell[i];
    return result;
}
}  // namespace tpmshx::preparation
