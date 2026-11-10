#include "tpmshx/preparation_flow_c_api.h"
#include "tpmshx/preparation_flow.hpp"
#include "preparation_c_boundary.hpp"
#include <algorithm>
#include <array>
#include <vector>

namespace {
namespace p=tpmshx::preparation;
namespace g=tpmshx::grid;
using namespace p::c_api;
using Scalar=tpmshx_grid_scalar_v1;
using Values=tpmshx_preparation_flow_values_v1;
g::Scalar scalar(Scalar value) {return g::checked({value.value,value.precision,value.strong});}
Scalar scalar(g::Scalar value) {return {value.value,value.precision,value.strong};}
void flag(std::uint32_t value) {
    if (value>1) throw std::invalid_argument("preparation flag must be zero or one");
}
template<class T> bool error_disjoint(char* error,size_t size,const T* data,size_t count) noexcept {
    if (!tpmshx::fields::c_api::error_buffer_valid(error,size)) return false;
    try {require_disjoint(error,size,data,count);return true;}
    catch (...) {return false;}
}
template<class Function> int result_boundary(char* error,size_t size,Scalar* output,
    size_t output_count,size_t expected,Function function) noexcept {
    if (!tpmshx::fields::c_api::error_buffer_valid(error,size)) return TPMSHX_PREPARATION_INVALID;
    try {require_disjoint(error,size,output,output_count);}
    catch (...) {return TPMSHX_PREPARATION_INVALID;}
    return boundary(error,size,[&] {
        require_output(output,output_count,expected);
        const auto result=function();
        for (size_t i=0;i<expected;++i) output[i]=scalar(result[i]);
    });
}
template<class T> void input(const T* data,size_t count,Scalar* output,size_t output_count,
                            char* error,size_t size) {
    require_buffer(data,count);
    require_disjoint(data,count,output,output_count);
    require_disjoint(data,count,error,size);
}
p::FlowValues input(Values value,Scalar* output,size_t output_count,char* error,size_t size) {
    input(value.data,value.count,output,output_count,error,size);
    g::checked({0.,value.precision,value.strong});
    return {{value.data,value.count},value.precision,value.strong};
}
}  // namespace

extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_inlet_capacity_2d_v1(
    Values epsilon,Values opening,Values geometric,Values widths,Scalar density,Scalar depth,
    Scalar* output,size_t output_count,char* error,size_t size) {
    for (const auto view : {epsilon,opening,geometric,widths})
        if (!error_disjoint(error,size,view.data,view.count)) return TPMSHX_PREPARATION_INVALID;
    return result_boundary(error,size,output,output_count,1,[&] {
        if (epsilon.count!=opening.count || epsilon.count!=geometric.count || epsilon.count!=widths.count)
            throw std::invalid_argument("2D inlet buffer extents differ");
        const auto e=input(epsilon,output,output_count,error,size);
        const auto o=input(opening,output,output_count,error,size);
        const auto a=input(geometric,output,output_count,error,size);
        const auto w=input(widths,output,output_count,error,size);
        return std::array<g::Scalar,1>{p::inlet_capacity_2d(e,o,a,w,scalar(density),scalar(depth))};
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_inlet_capacity_3d_v1(
    Values epsilon,const size_t* shape,size_t shape_count,int32_t direction,Values widths1,
    Values widths2,Values opening,Scalar density,Scalar* output,size_t output_count,char* error,size_t size) {
    if (!error_disjoint(error,size,shape,shape_count)) return TPMSHX_PREPARATION_INVALID;
    for (const auto view : {epsilon,widths1,widths2,opening})
        if (!error_disjoint(error,size,view.data,view.count)) return TPMSHX_PREPARATION_INVALID;
    return result_boundary(error,size,output,output_count,1,[&] {
        if (shape_count!=3) throw std::invalid_argument("3D inlet shape needs three extents");
        input(shape,shape_count,output,output_count,error,size);
        if (direction<0 || direction>5) throw std::invalid_argument("3D inlet direction must be in 0..5");
        const auto axes=g::axis_map(direction);
        if (!shape[0] || !shape[1] || !shape[2]) throw std::invalid_argument("3D inlet shape is empty");
        if (epsilon.count!=product(product(shape[0],shape[1]),shape[2])
            || widths1.count!=shape[static_cast<size_t>(axes[0])]
            || widths2.count!=shape[static_cast<size_t>(axes[2])]
            || opening.count!=product(widths1.count,widths2.count))
            throw std::invalid_argument("3D inlet buffer extents differ from the physical shape");
        const auto e=input(epsilon,output,output_count,error,size);
        const auto w1=input(widths1,output,output_count,error,size);
        const auto w2=input(widths2,output,output_count,error,size);
        const auto o=input(opening,output,output_count,error,size);
        return std::array<g::Scalar,1>{p::inlet_capacity_3d(e,{shape[0],shape[1],shape[2]},direction,w1,w2,o,scalar(density))};
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_inlet_speeds_v1(
    const Scalar* targets,const Scalar* capacities,size_t count,Scalar* output,size_t output_count,
    char* error,size_t size) {
    if (!error_disjoint(error,size,targets,count) || !error_disjoint(error,size,capacities,count))
        return TPMSHX_PREPARATION_INVALID;
    return result_boundary(error,size,output,output_count,count,[&] {
        input(targets,count,output,output_count,error,size);
        input(capacities,count,output,output_count,error,size);
        std::vector<g::Scalar> result;
        result.reserve(count);
        for (size_t i=0;i<count;++i) result.push_back(p::inlet_speed(scalar(targets[i]),scalar(capacities[i])));
        return result;
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_quick_design_sections_v1(
    Scalar epsilon,Scalar width,Scalar length,Scalar height,uint32_t cross,
    Scalar* output,size_t output_count,char* error,size_t size) {
    return result_boundary(error,size,output,output_count,4,[&] {
        flag(cross);
        return p::quick_design_sections(scalar(epsilon),scalar(width),scalar(length),scalar(height),cross!=0);
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_quick_design_flow_v1(
    Scalar mass_flow,Scalar area,Scalar density,uint32_t air,
    Scalar* output,size_t output_count,char* error,size_t size) {
    return result_boundary(error,size,output,output_count,2,[&] {
        flag(air);
        return p::quick_design_flow(scalar(mass_flow),scalar(area),scalar(density),air!=0);
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_relative_pressure_v1(
    Scalar pressure_drop,Scalar inlet_pressure,Scalar* output,size_t output_count,char* error,size_t size) {
    return result_boundary(error,size,output,output_count,1,[&] {
        return std::array<g::Scalar,1>{p::relative_pressure(scalar(pressure_drop),scalar(inlet_pressure))};
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_design_temperature_target_v1(
    Scalar temperature,uint32_t has_delta,Scalar delta,Scalar duty,Scalar mass_flow,Scalar heat_capacity,
    Scalar* output,size_t output_count,char* error,size_t size) {
    return result_boundary(error,size,output,output_count,1,[&] {
        flag(has_delta);
        return std::array<g::Scalar,1>{p::design_temperature_target(scalar(temperature),has_delta!=0,
            scalar(delta),scalar(duty),scalar(mass_flow),scalar(heat_capacity))};
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_design_cooling_proxy_v1(
    Scalar hot,Scalar cold,Scalar target,Scalar mass_flow,Scalar* output,size_t output_count,char* error,size_t size) {
    return result_boundary(error,size,output,output_count,2,[&] {
        return std::array<g::Scalar,2>{p::design_cooling_proxy(scalar(hot),scalar(cold),scalar(target),scalar(mass_flow)),
            g::weak(p::cooling_proxy_needs_target(scalar(hot),scalar(cold))?1.:0.)};
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_design_volume_v1(
    Scalar width,Scalar height,Scalar length,Scalar* output,size_t output_count,char* error,size_t size) {
    return result_boundary(error,size,output,output_count,1,[&] {
        return std::array<g::Scalar,1>{p::design_volume(scalar(width),scalar(height),scalar(length))};
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_closure_geometry_ratio_v1(
    Values diameter,Values cell,double* output,size_t output_count,Scalar* kind,char* error,size_t size) {
    if (!error_disjoint(error,size,diameter.data,diameter.count)
        || !error_disjoint(error,size,cell.data,cell.count)) return TPMSHX_PREPARATION_INVALID;
    try {
        require_disjoint(error,size,output,output_count);
        require_disjoint(error,size,kind,1);
    } catch (...) {return TPMSHX_PREPARATION_INVALID;}
    return boundary(error,size,[&] {
        if (diameter.count!=cell.count) throw std::invalid_argument("closure ratio input extents differ");
        require_output(output,output_count,diameter.count);
        require_buffer(kind,1);
        require_disjoint(output,output_count,kind,1);
        const auto d=input(diameter,kind,1,error,size);
        const auto l=input(cell,kind,1,error,size);
        require_disjoint(diameter.data,diameter.count,output,output_count);
        require_disjoint(cell.data,cell.count,output,output_count);
        const auto result=p::closure_geometry_ratio(d,l);
        if (!result.values.empty()) std::copy(result.values.begin(),result.values.end(),output);
        *kind=scalar(result.kind);
    });
}
