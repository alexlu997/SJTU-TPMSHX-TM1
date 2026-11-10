#include "tpmshx/preparation_flow.hpp"
#include "tpmshx/scalar_precision.hpp"
#include "tpmshx/ports.hpp"
#include "contiguous_sum.hpp"
#include <cmath>
#include <stdexcept>
#include <vector>

namespace tpmshx::preparation {
namespace {
namespace g=grid;
namespace p=geometry::detail;
g::Scalar item(FlowValues input,std::size_t index) {
    return {input.values[index],input.precision,input.strong};
}
g::Scalar product_scalar(g::Scalar left,g::Scalar right) {
    // shortcut: integer tags assume no overflow. Add modular arithmetic for a confirmed consumer.
    if (left.strong==2 && right.strong==2)
        return {left.value*right.value,std::max(left.precision,right.precision),2};
    return g::multiply(left,right);
}
double sum(const std::vector<double>& values,g::Scalar kind) {
    if (kind.strong!=2 && (kind.precision==16 || kind.precision==32)) {
        std::vector<float> narrow(values.size());
        std::transform(values.begin(),values.end(),narrow.begin(),
            [](double value) { return static_cast<float>(value); });
        const float total=0.f+detail::contiguous_sum<float>({narrow.data(),narrow.size()});
        return p::round_scalar(total,kind.precision);
    }
    return 0.+detail::contiguous_sum({values.data(),values.size()});
}
double products_sum(FlowValues first,FlowValues second) {
    std::vector<double> products(first.values.size);
    auto kind=product_scalar({0.,first.precision,first.strong},{0.,second.precision,second.strong});
    for (std::size_t i=0;i<products.size();++i)
        products[i]=product_scalar(item(first,i),item(second,i)).value;
    return sum(products,kind);
}
bool target_required(g::Scalar denominator) {return std::abs(denominator.value)>1e-9;}
}  // namespace

grid::Scalar inlet_capacity_2d(FlowValues epsilon,FlowValues opening,FlowValues geometric,
    FlowValues widths,grid::Scalar rho,grid::Scalar depth) {
    bool tapered=false;
    for (std::size_t i=0;i<opening.values.size;++i)
        tapered=tapered || opening.values[i]!=geometric.values[i];
    double scale=1.;
    if (tapered) {
        const double geometric_area=products_sum(geometric,widths);
        const double profile_area=products_sum(opening,widths);
        scale=tpmshx::inlet_profile_scale(tapered,geometric_area,profile_area);
    }
    std::vector<double> products(epsilon.values.size);
    const auto epsilon_kind=g::multiply({0.,64,1},g::weak(.5));
    auto kind=product_scalar(product_scalar(epsilon_kind,{0.,opening.precision,opening.strong}),
                       {0.,widths.precision,widths.strong});
    for (std::size_t i=0;i<products.size();++i) {
        const auto side=g::multiply({epsilon.values[i],64,1},g::weak(.5));
        products[i]=product_scalar(product_scalar(side,item(opening,i)),item(widths,i)).value;
    }
    return g::multiply(g::multiply(g::multiply(rho,g::weak(sum(products,kind))),depth),g::weak(scale));
}

grid::Scalar inlet_capacity_3d(FlowValues epsilon,const std::array<std::size_t,3>& shape,
    std::int32_t direction,FlowValues widths1,FlowValues widths2,FlowValues opening,grid::Scalar rho) {
    const auto axes=g::axis_map(direction);
    const auto cross1=static_cast<std::size_t>(axes[0]),stream=static_cast<std::size_t>(axes[1]);
    const auto cross2=static_cast<std::size_t>(axes[2]);
    std::vector<double> products(opening.values.size);
    const auto area_kind=product_scalar({0.,widths1.precision,widths1.strong},{0.,widths2.precision,widths2.strong});
    const auto kind=product_scalar(product_scalar({0.,epsilon.precision,epsilon.strong},
                                     {0.,opening.precision,opening.strong}),area_kind);
    std::array<std::size_t,3> coordinate{};
    coordinate[stream]=axes[6]?shape[stream]-1:0;
    for (std::size_t i=0;i<widths1.values.size;++i) {
        coordinate[cross1]=i;
        for (std::size_t j=0;j<widths2.values.size;++j) {
            coordinate[cross2]=j;
            const auto flat=(coordinate[0]*shape[1]+coordinate[1])*shape[2]+coordinate[2];
            const auto face=i*widths2.values.size+j;
            const auto area=product_scalar(item(widths1,i),item(widths2,j));
            products[face]=product_scalar(product_scalar(item(epsilon,flat),item(opening,face)),area).value;
        }
    }
    return g::multiply(rho,g::weak(sum(products,kind)));
}

grid::Scalar inlet_speed(grid::Scalar target,grid::Scalar capacity) {return g::divide(target,capacity);}

std::array<grid::Scalar,4> quick_design_sections(grid::Scalar epsilon,grid::Scalar width,
    grid::Scalar length,grid::Scalar height,bool cross) {
    const auto area_hot=g::multiply(g::multiply(epsilon,width),height);
    const auto area_cold=g::multiply(g::multiply(epsilon,cross?length:width),height);
    return {area_hot,length,area_cold,cross?width:length};
}

std::array<grid::Scalar,2> quick_design_flow(grid::Scalar mass_flow,grid::Scalar area,
    grid::Scalar density,bool air) {
    const auto flux=g::divide(mass_flow,area);
    return {flux,air?g::weak(0.):g::divide(flux,density)};
}

grid::Scalar relative_pressure(grid::Scalar pressure_drop,grid::Scalar inlet_pressure) {
    return g::divide(pressure_drop,inlet_pressure);
}

grid::Scalar design_temperature_target(grid::Scalar temperature,bool has_delta,grid::Scalar delta,
    grid::Scalar duty,grid::Scalar mass_flow,grid::Scalar heat_capacity) {
    return g::subtract(temperature,has_delta?delta:g::divide(duty,g::multiply(mass_flow,heat_capacity)));
}

grid::Scalar design_cooling_proxy(grid::Scalar hot,grid::Scalar cold,grid::Scalar target,grid::Scalar mass_flow) {
    const auto denominator=g::subtract(hot,cold);
    const auto required=target_required(denominator)?
        g::divide(g::subtract(hot,target),denominator):g::weak(0.);
    return g::multiply(required,mass_flow);
}

bool cooling_proxy_needs_target(grid::Scalar hot,grid::Scalar cold) {
    return target_required(g::subtract(hot,cold));
}

grid::Scalar design_volume(grid::Scalar width,grid::Scalar height,grid::Scalar length) {
    return g::multiply(g::multiply(width,height),length);
}

ClosureRatio closure_geometry_ratio(FlowValues diameter,FlowValues cell) {
    const auto kind=g::divide(g::multiply({0.,diameter.precision,diameter.strong},g::weak(1000.)),
                              {1.,cell.precision,cell.strong});
    ClosureRatio result{std::vector<double>(diameter.values.size),kind};
    for (std::size_t i=0;i<result.values.size();++i)
        result.values[i]=g::divide(g::multiply(item(diameter,i),g::weak(1000.)),item(cell,i)).value;
    return result;
}
}  // namespace tpmshx::preparation
