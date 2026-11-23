#pragma once
#include "tpmshx/stage_run_c_api.h"
#include "tpmshx/stage_run_3d_c_api.h"
#include "tpmshx/preparation_case_3d_c_api.h"
#include "tpmshx/quick_design_stage_c_api.h"
#include <algorithm>
#include <array>
#include <cstring>
#include <stdexcept>
#include <thread>
#include <utility>
#include <vector>

namespace tpmshx::stages {

class NativeError : public std::runtime_error {
public:
    NativeError(int status,const char* message):std::runtime_error(message),status_(status) {}
    int status() const noexcept {return status_;}
private:
    int status_;
};
namespace detail {
// Every owner is released by the same ABI that created it.
template<class State,void (*Release)(State*)> class Owned {
public:
    explicit Owned(State state):state_(state) {}
    ~Owned() {Release(&state_);}
    Owned(const Owned&)=delete;
    Owned& operator=(const Owned&)=delete;
    Owned(Owned&& other) noexcept:state_(std::exchange(other.state_,{})) {}
    Owned& operator=(Owned&& other) noexcept {
        if(this!=&other) {Release(&state_);state_=std::exchange(other.state_,{});}
        return *this;
    }
    const State& view() const noexcept {return state_;}
private:
    State state_;
};
inline void check(int status,const char* error) {if(status)throw NativeError(status,error);}
}
using InletFlow2D=detail::Owned<tpmshx_preparation_flow_2d_v3,tpmshx_preparation_flow_2d_release_v3>;
using ContinuousInletFlow2D=detail::Owned<tpmshx_preparation_continuous_flow_2d_v4,tpmshx_preparation_continuous_flow_2d_release_v4>;
using SigmoidLUT2D=detail::Owned<tpmshx_preparation_sigmoid_lut_v6,tpmshx_preparation_sigmoid_lut_release_v6>;
using ZonedInletFlow2Dv9=detail::Owned<tpmshx_preparation_zoned_flow_2d_v9,tpmshx_preparation_zoned_flow_2d_release_v9>;
using SigmoidInletFlow2Dv9=detail::Owned<tpmshx_preparation_sigmoid_flow_2d_v9,tpmshx_preparation_sigmoid_flow_2d_release_v9>;
using PreparedFlowCase2Dv10=detail::Owned<tpmshx_preparation_flow_case_2d_v10,tpmshx_preparation_flow_case_2d_release_v10>;
using PreparedZonedFlowCase2Dv10=detail::Owned<tpmshx_preparation_zoned_flow_case_2d_v10,tpmshx_preparation_zoned_flow_case_2d_release_v10>;
using PreparedSigmoidFlowCase2Dv10=detail::Owned<tpmshx_preparation_sigmoid_flow_case_2d_v10,tpmshx_preparation_sigmoid_flow_case_2d_release_v10>;
using PreparedContinuousCase2Dv11=detail::Owned<tpmshx_preparation_continuous_case_2d_v11,tpmshx_preparation_continuous_flow_case_2d_release_v11>;
using PreparedStripeCase2Dv11=detail::Owned<tpmshx_preparation_stripe_flow_case_2d_v11,tpmshx_preparation_stripe_flow_case_2d_release_v11>;
using ContinuousInletFlow3D=detail::Owned<tpmshx_preparation_continuous_flow_3d_v3,tpmshx_preparation_continuous_flow_3d_release_v3>;
using PreparedContinuousCase3D=detail::Owned<tpmshx_preparation_continuous_case_3d_v3,tpmshx_preparation_continuous_case_3d_release_v3>;
using SpatialInletFlow3D=detail::Owned<tpmshx_preparation_spatial_flow_3d_v4,tpmshx_preparation_spatial_flow_3d_release_v4>;
using PreparedSpatialCase3D=detail::Owned<tpmshx_preparation_spatial_case_3d_v4,tpmshx_preparation_spatial_case_3d_release_v4>;
using RunResult2D=detail::Owned<tpmshx_stage_run_result_2d_v1,tpmshx_stage_run_2d_release_v1>;
using RunResult3D=detail::Owned<tpmshx_stage_run_result_3d_v1,tpmshx_stage_run_3d_release_v1>;
using RunState=detail::Owned<tpmshx_run_state_v1,tpmshx_run_state_release_v1>;
using Evaluation=detail::Owned<tpmshx_stage_output_v1,tpmshx_result_stage_release_v1>;

struct CaseInput2D : tpmshx_preparation_case_input_2d_v1 {
    CaseInput2D():tpmshx_preparation_case_input_2d_v1{} {
        abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION;struct_size=sizeof(tpmshx_preparation_case_input_2d_v1);
    }
};
struct PreparationOptions : tpmshx_preparation_case_options_v1 {
    PreparationOptions():tpmshx_preparation_case_options_v1{} {
        abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION;struct_size=sizeof(tpmshx_preparation_case_options_v1);
    }
};
struct CaseInput2Dv2 : tpmshx_preparation_case_input_2d_v2 {
    CaseInput2Dv2():tpmshx_preparation_case_input_2d_v2{} {
        abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;struct_size=sizeof(tpmshx_preparation_case_input_2d_v2);
        values=CaseInput2D{};
        kinds.cell_length=kinds.wall_thickness=kinds.solid_conductivity={64,0,0};
        for (auto& side:kinds.sides) side.velocity=side.temperature=side.pressure={64,0,0};
    }
};
struct InletPropertyQuery : tpmshx_preparation_inlet_query_input_v1 {
    InletPropertyQuery():tpmshx_preparation_inlet_query_input_v1{} {
        abi_version=1;struct_size=sizeof(tpmshx_preparation_inlet_query_input_v1);
        inlet.geometry.cell_kind=inlet.geometry.wall_kind={64,0,0};
        inlet.kinds.velocity=inlet.kinds.temperature=inlet.kinds.pressure={64,0,0};
        diameter_kind=epsilon_kind={64,0,0};
    }
};
struct CaseInput3D : tpmshx_preparation_case_input_3d_v1 {
    CaseInput3D():tpmshx_preparation_case_input_3d_v1{} {
        abi_version=TPMSHX_PREPARATION_CASE_3D_ABI_VERSION;struct_size=sizeof(tpmshx_preparation_case_input_3d_v1);
        max_cells=2000000;
        for (auto& length:lengths_m) length={0.,64,0};
        kinds.cell_length=kinds.wall_thickness=kinds.solid_conductivity={64,0,0};
        for (auto& side:kinds.sides) side.velocity=side.temperature=side.pressure={64,0,0};
        for (auto& side:sides) side.port.active=1;
    }
};
struct FlowInput3D : tpmshx_preparation_flow_input_3d_v2 {
    FlowInput3D():tpmshx_preparation_flow_input_3d_v2{} {
        abi_version=TPMSHX_PREPARATION_FLOW_3D_ABI_VERSION;struct_size=sizeof(tpmshx_preparation_flow_input_3d_v2);
        input=CaseInput3D{};target_kinds[0]=target_kinds[1]={64,0,0};
    }
};
struct ContinuousInput3D : tpmshx_preparation_continuous_input_3d_v3 {
    ContinuousInput3D():tpmshx_preparation_continuous_input_3d_v3{} {
        abi_version=TPMSHX_PREPARATION_CONTINUOUS_3D_ABI_VERSION;struct_size=sizeof(tpmshx_preparation_continuous_input_3d_v3);
        values=FlowInput3D{};values.input.geometry_mode=1;
    }
};
struct SpatialInput3D : tpmshx_preparation_spatial_input_3d_v4 {
    SpatialInput3D():tpmshx_preparation_spatial_input_3d_v4{} {
        abi_version=TPMSHX_PREPARATION_SPATIAL_3D_ABI_VERSION;struct_size=sizeof(tpmshx_preparation_spatial_input_3d_v4);
        values=FlowInput3D{};
    }
};
struct FlowInput2D : tpmshx_preparation_flow_input_2d_v3 {
    FlowInput2D():tpmshx_preparation_flow_input_2d_v3{} {
        abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V3;struct_size=sizeof(tpmshx_preparation_flow_input_2d_v3);
        values=CaseInput2Dv2{};
        physical_depth_kind=target_kinds[0]=target_kinds[1]={64,0,0};
    }
};
struct ContinuousInput2D : tpmshx_preparation_continuous_input_2d_v4 {
    ContinuousInput2D():tpmshx_preparation_continuous_input_2d_v4{} {
        abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V4;struct_size=sizeof(tpmshx_preparation_continuous_input_2d_v4);
        values=FlowInput2D{};values.values.values.geometry_mode=1;
    }
};
struct ZonedInput2D : tpmshx_preparation_zoned_input_2d_v5 {
    ZonedInput2D():tpmshx_preparation_zoned_input_2d_v5{} {
        abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V5;struct_size=sizeof(tpmshx_preparation_zoned_input_2d_v5);
        values=CaseInput2Dv2{};values.values.geometry_mode=2;axis=1;
    }
};
struct SigmoidInput2D : tpmshx_preparation_sigmoid_input_2d_v6 {
    SigmoidInput2D():tpmshx_preparation_sigmoid_input_2d_v6{} {
        abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V6;struct_size=sizeof(tpmshx_preparation_sigmoid_input_2d_v6);
        values=ZonedInput2D{};values.kind=1;
        controls.inlet_transition=controls.outlet_transition={.2,64,0};
    }
};
struct ZonedFlowInput2D : tpmshx_preparation_zoned_flow_input_2d_v8 {
    ZonedFlowInput2D():tpmshx_preparation_zoned_flow_input_2d_v8{} {
        abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V8;struct_size=sizeof(tpmshx_preparation_zoned_flow_input_2d_v8);
        values=ZonedInput2D{};physical_depth_kind=target_kinds[0]=target_kinds[1]={64,0,0};
    }
};
struct SigmoidFlowInput2D : tpmshx_preparation_sigmoid_flow_input_2d_v8 {
    SigmoidFlowInput2D():tpmshx_preparation_sigmoid_flow_input_2d_v8{} {
        abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V8;struct_size=sizeof(tpmshx_preparation_sigmoid_flow_input_2d_v8);
        values=SigmoidInput2D{};physical_depth_kind=target_kinds[0]=target_kinds[1]={64,0,0};
    }
};
struct ZonedFlowInput2Dv9 : tpmshx_preparation_zoned_flow_input_2d_v9 {
    ZonedFlowInput2Dv9():tpmshx_preparation_zoned_flow_input_2d_v9{} {
        abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V9;struct_size=sizeof(tpmshx_preparation_zoned_flow_input_2d_v9);
        values=ZonedFlowInput2D{};model.solid_conductivity_W_mK=16.;model.solid_conductivity_kind={64,0,0};
    }
};
struct SigmoidFlowInput2Dv9 : tpmshx_preparation_sigmoid_flow_input_2d_v9 {
    SigmoidFlowInput2Dv9():tpmshx_preparation_sigmoid_flow_input_2d_v9{} {
        abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V9;struct_size=sizeof(tpmshx_preparation_sigmoid_flow_input_2d_v9);
        values=SigmoidFlowInput2D{};model.solid_conductivity_W_mK=16.;model.solid_conductivity_kind={64,0,0};
    }
};
struct GridKinds2D : tpmshx_preparation_grid_kinds_2d_v7 {
    GridKinds2D():tpmshx_preparation_grid_kinds_2d_v7{} {
        abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V7;struct_size=sizeof(tpmshx_preparation_grid_kinds_2d_v7);
        for (auto& value:lengths) value={64,0,0};
        for (auto& side:ports) for (auto& value:side) value={64,0,0};
    }
};
struct RunRequest2D : tpmshx_stage_run_request_2d_v1 {
    RunRequest2D():tpmshx_stage_run_request_2d_v1{} {
        abi_version=TPMSHX_STAGE_RUN_ABI_VERSION;struct_size=sizeof(tpmshx_stage_run_request_2d_v1);
    }
};
struct RunRequest2Dv2 : tpmshx_stage_run_request_2d_v2 {
    RunRequest2Dv2():tpmshx_stage_run_request_2d_v2{} {
        abi_version=TPMSHX_STAGE_RUN_ABI_VERSION_V2;struct_size=sizeof(tpmshx_stage_run_request_2d_v2);
        values=RunRequest2D{};
    }
};
struct RunControl : tpmshx_stage_run_control_v1 {
    RunControl():tpmshx_stage_run_control_v1{} {
        const auto logical=std::thread::hardware_concurrency();cpu_threads=std::min(8u,logical?logical:1u);
    }
};
struct RunRequest2Dv3 : tpmshx_stage_run_request_2d_v3 {
    RunRequest2Dv3():tpmshx_stage_run_request_2d_v3{} {
        abi_version=TPMSHX_STAGE_RUN_ABI_VERSION_V3;struct_size=sizeof(tpmshx_stage_run_request_2d_v3);
        values=RunRequest2Dv2{};
    }
};
struct SavedCase2D : tpmshx_stage_saved_case_2d_v1 {
    SavedCase2D():tpmshx_stage_saved_case_2d_v1{} {
        reference_cell_kind={64,0,0};cell_field_kind=hydraulic_diameter_kind={64,1,2};
        abi_version=TPMSHX_STAGE_RUN_ABI_VERSION;struct_size=sizeof(tpmshx_stage_saved_case_2d_v1);
        inlet_recorded=1;
    }
};
struct SavedCase2Dv2 : tpmshx_stage_saved_case_2d_v2 {
    SavedCase2Dv2():tpmshx_stage_saved_case_2d_v2{} {
        abi_version=TPMSHX_STAGE_RUN_ABI_VERSION_V2;struct_size=sizeof(tpmshx_stage_saved_case_2d_v2);
        values=SavedCase2D{};
    }
};
struct SavedCase2Dv3 : tpmshx_stage_saved_case_2d_v3 {
    SavedCase2Dv3():tpmshx_stage_saved_case_2d_v3{} {
        abi_version=3;struct_size=sizeof(tpmshx_stage_saved_case_2d_v3);
        values=SavedCase2Dv2{};
        wall_reference_kind=porosity_reference_kind=radius_reference_kind={64,0,0};
    }
};
namespace detail {
inline tpmshx_preparation_text_v1 text(const char* value) {return {value,std::strlen(value)};}
inline tpmshx_preparation_text_v1 fluid_text(uint32_t fluid) {
    static const char* const names[]{"air","water","sco2","co2"};
    if(fluid>3)throw std::invalid_argument("unknown prepared fluid");
    return text(names[fluid]);
}
inline tpmshx_preparation_text_v1 topology_text(uint32_t topology) {
    if(topology>1)throw std::invalid_argument("unknown prepared topology");
    return text(topology?"Gyroid":"Diamond");
}
}
/* Saved v4 descriptor for one prepared 2D owner. The descriptor borrows the
 * prepared arrays. It owns a copy of the prepared view without the outlet
 * fractions, because the saved run computes them, and the reversed stream widths. Keep the prepared owner
 * alive and unchanged until result transfer or run release. The domain and port
 * bounds use weak float64 kinds, as the default GridKinds2D does. Typed port
 * kinds are not supported by this helper. The descriptor cannot move because
 * it points into its own storage. */
class SavedCase2Dv4 : public tpmshx_stage_saved_case_2d_v4 {
public:
    explicit SavedCase2Dv4(const PreparedFlowCase2Dv10& prepared):tpmshx_stage_saved_case_2d_v4{} {
        const auto& value=prepared.view();
        fill(value.values.prepared,{},{},nullptr,&value.thermal);
    }
    explicit SavedCase2Dv4(const PreparedZonedFlowCase2Dv10& prepared):tpmshx_stage_saved_case_2d_v4{} {
        const auto& value=prepared.view();const auto& spatial=value.values.values.prepared;
        fill(spatial.prepared,spatial.area_density_per_m,spatial.hydraulic_diameter_m,spatial.fluid_conductivity,&value.thermal);
    }
    explicit SavedCase2Dv4(const PreparedSigmoidFlowCase2Dv10& prepared):tpmshx_stage_saved_case_2d_v4{} {
        const auto& value=prepared.view();const auto& spatial=value.values.values.prepared.values;
        fill(spatial.prepared,spatial.area_density_per_m,spatial.hydraulic_diameter_m,spatial.fluid_conductivity,&value.thermal);
    }
    explicit SavedCase2Dv4(const PreparedStripeCase2Dv11& prepared):tpmshx_stage_saved_case_2d_v4{} {
        const auto& value=prepared.view().values;const auto& spatial=value.values.values.prepared;
        fill(spatial.prepared,spatial.area_density_per_m,spatial.hydraulic_diameter_m,spatial.fluid_conductivity,&value.thermal);
    }
    explicit SavedCase2Dv4(const PreparedContinuousCase2Dv11& prepared):tpmshx_stage_saved_case_2d_v4{} {
        const auto& value=prepared.view().values;
        fill(value.prepared,value.area_density_per_m,value.hydraulic_diameter_m,value.fluid_conductivity,nullptr);
    }
    SavedCase2Dv4(const SavedCase2Dv4&)=delete;
    SavedCase2Dv4& operator=(const SavedCase2Dv4&)=delete;
private:
    void fill(const tpmshx_preparation_case_2d_v2& prepared,tpmshx_preparation_array_v1 area,
        tpmshx_preparation_array_v1 diameter,const tpmshx_preparation_array_v1* conductivity,
        const tpmshx_preparation_thermal_sides_2d_v10* thermal) {
        prepared_=prepared;
        for(auto& side:prepared_.values.sides)side.outlet_u_fraction={};
        const auto& p=prepared.values;
        abi_version=TPMSHX_STAGE_RUN_ABI_VERSION_V4;struct_size=sizeof(tpmshx_stage_saved_case_2d_v4);
        values=SavedCase2Dv3{};
        auto& v1=values.values.values;
        v1.prepared=&prepared_;v1.reference_cell_kind=prepared.input_kinds.cell_length;
        if(p.input.geometry_mode)v1.cell_field_kind=prepared.field_kinds[0];
        v1.area_density_per_m=area;v1.hydraulic_diameter_m=diameter;
        if(conductivity)std::copy_n(conductivity,2,v1.fluid_conductivity);
        if(thermal) {
            values.values.have_side_geometry=thermal->have_side_geometry;
            for(size_t side=0;side<2;++side)std::copy_n(thermal->side_geometry[side],4,values.values.side_geometry[side]);
        }
        values.wall_reference_kind=prepared.input_kinds.wall_thickness;
        values.lengths_m[0]=p.input.length_m;values.lengths_m[1]=p.input.height_m;
        for(size_t side=0;side<2;++side) {
            const auto& s=p.sides[side];auto& grid=values.flow_grid[side];
            const auto direction=s.inlet.port.direction;
            if(direction<0 || direction>3)throw std::invalid_argument("invalid prepared 2D direction");
            const auto cross=direction<2?p.dy:p.dx,stream=direction<2?p.dx:p.dy;
            stream_[side].assign(stream.data,stream.data+stream.size);
            if(direction%2)std::reverse(stream_[side].begin(),stream_[side].end());
            grid.cross=cross;grid.stream={stream_[side].data(),stream_[side].size()};
            grid.cross_precision=64;grid.direction=static_cast<uint32_t>(direction);
            const double bounds[]{s.inlet_bounds[0],s.inlet_bounds[1],s.outlet_bounds[0],s.outlet_bounds[1]};
            for(size_t i=0;i<4;++i)grid.bounds[i]={bounds[i],64,0};
            values.resource_fluids[side]=detail::fluid_text(s.inlet.fluid);
            values.resource_nu[side]=prepared.sco2_nu;
        }
        values.resource_topology=detail::topology_text(p.input.topology);
        auto& settings=experiment;
        settings.topology=p.input.topology;settings.geometry_mode=p.input.geometry_mode;
        settings.domain_count=p.input.have_physical_depth?3:2;
        settings.domain_m[0]=p.input.length_m;settings.domain_m[1]=p.input.height_m;
        settings.domain_m[2]=p.input.have_physical_depth?p.input.physical_depth_m:0.;
        settings.cell_length_mm=p.input.cell_length_mm;settings.wall_thickness_mm=p.input.wall_thickness_mm;
        settings.delta_levelset=p.input.delta_levelset;
        for(size_t side=0;side<2;++side) {
            settings.fluids[side]=p.sides[side].inlet.fluid;
            settings.velocity_m_s[side]=p.sides[side].inlet.velocity_m_s;
        }
    }
    tpmshx_preparation_case_2d_v2 prepared_{};
    std::array<std::vector<double>,2> stream_;
};
inline tpmshx_stage_capture_2d_v1 capture_summary(const RunResult2D& result,
    const tpmshx_stage_application_2d_v1& application) {
    tpmshx_stage_capture_2d_v1 output{};
    detail::check(tpmshx_stage_run_2d_get_capture_v1(&result.view(),&application,&output),
        "native 2D capture summary failed");
    return output;
}

inline tpmshx_stage_capture_3d_v1 capture_summary(const RunResult3D& result,bool include_audit=false) {
    tpmshx_stage_capture_3d_v1 output{};
    detail::check(tpmshx_stage_run_3d_get_capture_v1(&result.view(),include_audit?1u:0u,&output),
        "native 3D capture summary failed");
    return output;
}

struct SavedCase3D : tpmshx_stage_saved_case_3d_v1 {
    SavedCase3D():tpmshx_stage_saved_case_3d_v1{} {
        abi_version=TPMSHX_STAGE_RUN_3D_ABI_VERSION;struct_size=sizeof(tpmshx_stage_saved_case_3d_v1);
        inlet_recorded=1;
    }
};
struct SavedCase3Dv2 : tpmshx_stage_saved_case_3d_v2 {
    SavedCase3Dv2():tpmshx_stage_saved_case_3d_v2{} {
        abi_version=2;struct_size=sizeof(tpmshx_stage_saved_case_3d_v2);values=SavedCase3D{};
        for(auto& kind:reference_kinds)kind={64,0,0};
        for(auto& kind:field_kinds)kind={64,1,1};
    }
};
struct RunRequest3D : tpmshx_stage_run_request_3d_v1 {
    RunRequest3D():tpmshx_stage_run_request_3d_v1{} {
        abi_version=TPMSHX_STAGE_RUN_3D_ABI_VERSION;struct_size=sizeof(tpmshx_stage_run_request_3d_v1);
    }
};
struct RunControl3D : tpmshx_stage_run_control_3d_v1 {
    RunControl3D():tpmshx_stage_run_control_3d_v1{} {
        result_id="native-3d";cpu_threads=std::max(1u,std::thread::hardware_concurrency());
    }
};
namespace detail {
// The helper restores the nominal millimetre values as float64 SI round trips.
inline double nominal_mm(double value,const tpmshx_preparation_scalar_kind_v2& kind) {
    if(kind.precision!=64 || kind.layout>2)
        throw std::invalid_argument("the 3D saved-case helper supports float64 nominal geometry kinds only");
    return value*1e-3*1e3;
}
inline tpmshx_full3d_array_v1 view(tpmshx_preparation_array_v1 value) {return {value.data,value.size};}
}
/* Saved v2 descriptor for one prepared 3D owner. It copies the solver input
 * and borrows all prepared arrays and texts. Keep the prepared owner alive and
 * unchanged until result transfer or run release. The nominal cell length and
 * wall thickness must use float64 kinds. The descriptor cannot move because
 * it points into its own storage. */
class SavedPreparedCase3D : public SavedCase3Dv2 {
public:
    explicit SavedPreparedCase3D(const PreparedSpatialCase3D& prepared) {
        const auto& value=prepared.view();
        fill(value.prepared,value.side_b_porosity,value.area_density_per_m,value.hydraulic_diameter_m,
            value.have_side_geometry,value.side_geometry,value.prepared.input.geometry_mode?1u:0u,0u);
    }
    explicit SavedPreparedCase3D(const PreparedContinuousCase3D& prepared) {
        const auto& value=prepared.view();
        const double unit[2][4]{{1.,1.,1.,1.},{1.,1.,1.,1.}};
        fill(value.prepared,value.prepared.side_porosity,value.area_density_per_m,value.hydraulic_diameter_m,
            0u,unit,value.controls.have_ctrl_z?2u:1u,value.controls.have_ctrl_z);
    }
    SavedPreparedCase3D(const SavedPreparedCase3D&)=delete;
    SavedPreparedCase3D& operator=(const SavedPreparedCase3D&)=delete;
private:
    void fill(const tpmshx_preparation_case_3d_v1& p,tpmshx_preparation_array_v1 side_b,
        tpmshx_preparation_array_v1 area,tpmshx_preparation_array_v1 diameter,uint32_t have_side_geometry,
        const double (&side_geometry)[2][4],uint32_t mode,uint32_t have_z) {
        if(p.input.topology>1)throw std::invalid_argument("invalid prepared 3D topology");
        auto& in=input_;
        for(size_t axis=0;axis<3;++axis) {
            in.shape[axis]=p.widths[axis].size;in.widths[axis]=detail::view(p.widths[axis]);
            lengths_m[axis]=p.input.lengths_m[axis].value;
        }
        const bool spatial=p.input.geometry_mode!=0;
        in.epsilon=detail::view(p.total_porosity);in.epsilon_a=detail::view(p.side_porosity);
        in.epsilon_b=detail::view(side_b);
        in.permeability=detail::view(p.permeability);in.forchheimer=detail::view(p.forchheimer);
        in.solid_conductivity=detail::view(p.solid_conductivity);in.cell_length=detail::view(p.cell_length);
        if(spatial) {
            in.area_density=detail::view(area);in.hydraulic_diameter=detail::view(diameter);
        } else {
            in.area_density={&p.geometry.area_density_per_m,1};
            in.hydraulic_diameter={&p.geometry.hydraulic_diameter_m,1};
        }
        const auto cell=detail::nominal_mm(p.input.cell_length_mm,p.input.kinds.cell_length);
        const auto wall=detail::nominal_mm(p.input.wall_thickness_mm,p.input.kinds.wall_thickness);
        in.reference_cell_length=cell*1e-3;in.reference_hydraulic_diameter=p.geometry.hydraulic_diameter_m;
        in.topology=p.input.topology;in.spatial=spatial?1:0;in.asymmetric=p.input.delta_levelset!=0.;in.solve_b=1;
        if(in.asymmetric && !have_side_geometry)
            throw std::invalid_argument("asymmetric 3D stage requires prepared side thermal geometry");
        if(p.input.sco2_nu.mode>1)throw std::invalid_argument("invalid prepared 3D Nu mode");
        for(size_t side=0;side<2;++side) {
            const auto& s=p.sides[side];const auto& inlet=p.input.sides[side];auto& target=in.sides[side];
            auto& axes_record=axes[side];
            if(inlet.port.direction<0 || inlet.port.direction>5)throw std::invalid_argument("invalid prepared 3D direction");
            target.fluid=inlet.fluid;target.direction=static_cast<uint32_t>(inlet.port.direction);
            for(size_t i=0;i<3;++i) {
                if(s.axes[i]<0 || s.axes[i]>2)throw std::invalid_argument("invalid prepared 3D axis");
                const auto axis=static_cast<size_t>(s.axes[i]);
                target.solver_axes[i]=static_cast<uint32_t>(axis);
                axes_record.solver_to_real[axis]=static_cast<int32_t>(i);
                axes_record.counts[i]=axes_record.solver_counts[i]=p.widths[axis].size;
                axes_record.lengths[i]=axes_record.solver_lengths[i]=lengths_m[axis];
                axes_record.widths[i]=p.widths[axis];
            }
            axes_record.reverse=inlet.port.direction%2;axes_record.port=inlet.port;
            target.inlet_temperature=inlet.temperature_K;target.inlet_pressure=inlet.pressure_Pa;
            target.inlet_velocity=inlet.velocity_m_s;
            for(size_t i=0;i<4;++i)target.heat_transfer_geometry[i]=in.asymmetric?side_geometry[side][i]:1.;
            target.inlet_opening=detail::view(s.inlet_opening);target.outlet_opening=detail::view(s.outlet_opening);
            target.permeability_scale=s.have_drag_application?s.drag_evidence.scale_permeability:1.;
            target.forchheimer_scale=s.have_drag_application?s.drag_evidence.scale_forchheimer:1.;
            target.sco2_nusselt_multiplier=p.input.sco2_nu.mode?p.input.sco2_nu.alpha[in.topology]:1.;
            resource_fluids[side]=detail::fluid_text(inlet.fluid);resource_nu[side]=p.input.sco2_nu;
        }
        values.input=&in;values.nominal_cell_length_mm=cell;values.nominal_wall_thickness_mm=wall;
        values.nominal_porosity=p.geometry.epsilon;values.wall_thickness_m=p.wall_thickness;
        values.preparation=p.evidence;values.notices=p.notices;values.notice_count=p.notice_count;
        design_mode=mode;have_z_controls=have_z;
        reference_kinds[0]=p.input.kinds.cell_length;reference_kinds[1]=p.input.kinds.wall_thickness;
        std::copy_n(p.models,4,models);
        resource_topology=detail::topology_text(p.input.topology);sco2_nu=p.input.sco2_nu;
    }
    tpmshx_full3d_input_v1 input_{};
};
// Keep the saved descriptor and its prepared owner alive and unchanged until take_result or release.
class Run3D {
public:
    Run3D(const tpmshx_stage_saved_case_3d_v2& saved,const RunControl3D& control,const RunRequest3D& request={},
        const RunState* state=nullptr) {
        char error[4096]{};
        const auto status=state?tpmshx_stage_run_3d_restore_saved_v2(&saved,&request,&control,
            state->view().fields,state->view().count,&run_,error,sizeof(error)):
            tpmshx_stage_run_3d_create_saved_v2(&saved,&request,&control,&run_,error,sizeof(error));
        detail::check(status,error);
    }
    ~Run3D() {tpmshx_stage_run_3d_release_run_v1(&run_);}
    Run3D(const Run3D&)=delete;
    Run3D& operator=(const Run3D&)=delete;
    Run3D(Run3D&& other) noexcept:run_(std::exchange(other.run_,nullptr)) {}
    Run3D& operator=(Run3D&& other) noexcept {
        if(this!=&other) {tpmshx_stage_run_3d_release_run_v1(&run_);run_=std::exchange(other.run_,nullptr);}
        return *this;
    }
    uint32_t phase() const {
        uint32_t value=0;
        detail::check(tpmshx_stage_run_3d_phase_v1(run_,&value),"invalid 3D stage run");return value;
    }
    uint32_t advance_step() {
        uint32_t value=0;char error[4096]{};
        detail::check(tpmshx_stage_run_3d_advance_step_v1(run_,&value,error,sizeof(error)),error);return value;
    }
    void finish() {
        char error[4096]{};
        detail::check(tpmshx_stage_run_3d_finish_v1(run_,error,sizeof(error)),error);
    }
    RunState snapshot() const {
        tpmshx_run_state_v1 value{};char error[4096]{};
        detail::check(tpmshx_stage_run_3d_snapshot_v1(run_,&value,error,sizeof(error)),error);return RunState(value);
    }
    RunResult3D take_result() {
        tpmshx_stage_run_result_3d_v1 value{};char error[4096]{};
        value.abi_version=TPMSHX_STAGE_RUN_3D_ABI_VERSION;value.struct_size=sizeof(value);
        detail::check(tpmshx_stage_run_3d_take_result_v1(run_,&value,error,sizeof(error)),error);return RunResult3D(value);
    }
private:
    void* run_=nullptr;
};

// Keep the saved descriptor and its prepared owner alive and unchanged until take_result or release.
class Run2D {
public:
    Run2D(const tpmshx_stage_saved_case_2d_v4& saved,const RunControl& control,const RunRequest2Dv3& request={},
        const RunState* state=nullptr) {
        char error[4096]{};
        const auto status=state?tpmshx_stage_run_2d_restore_saved_v4(&saved,&request,&control,
            state->view().fields,state->view().count,&run_,error,sizeof(error)):
            tpmshx_stage_run_2d_create_saved_v4(&saved,&request,&control,&run_,error,sizeof(error));
        detail::check(status,error);
    }
    ~Run2D() {tpmshx_stage_run_2d_release_run_v1(&run_);}
    Run2D(const Run2D&)=delete;
    Run2D& operator=(const Run2D&)=delete;
    Run2D(Run2D&& other) noexcept:run_(std::exchange(other.run_,nullptr)) {}
    Run2D& operator=(Run2D&& other) noexcept {
        if(this!=&other) {tpmshx_stage_run_2d_release_run_v1(&run_);run_=std::exchange(other.run_,nullptr);}
        return *this;
    }
    uint32_t phase() const {
        uint32_t value=0;
        detail::check(tpmshx_stage_run_2d_phase_v1(run_,&value),"invalid stage run");return value;
    }
    uint32_t advance_step() {
        uint32_t value=0;char error[4096]{};
        detail::check(tpmshx_stage_run_2d_advance_step_v1(run_,&value,error,sizeof(error)),error);return value;
    }
    void finish() {
        char error[4096]{};
        detail::check(tpmshx_stage_run_2d_finish_v1(run_,error,sizeof(error)),error);
    }
    RunState snapshot() const {
        tpmshx_run_state_v1 value{};char error[4096]{};
        detail::check(tpmshx_stage_run_2d_snapshot_v1(run_,&value,error,sizeof(error)),error);return RunState(value);
    }
    RunResult2D take_result() {
        tpmshx_stage_run_result_2d_v1 value{};char error[4096]{};
        value.abi_version=TPMSHX_STAGE_RUN_ABI_VERSION;value.struct_size=sizeof(value);
        detail::check(tpmshx_stage_run_2d_take_result_v1(run_,&value,error,sizeof(error)),error);return RunResult2D(value);
    }
private:
    void* run_=nullptr;
};
inline tpmshx_preparation_inlet_query_result_v1 query_inlet_properties(
    const InletPropertyQuery& input,const tpmshx_preparation_case_callbacks_v3* callbacks=nullptr) {
    tpmshx_preparation_inlet_query_result_v1 output{};
    output.abi_version=1;output.struct_size=sizeof(output);
    tpmshx_preparation_case_failure_v2 failure{};
    failure.abi_version=2;failure.struct_size=sizeof(failure);char error[4096]{};
    detail::check(tpmshx_query_inlet_properties_v1(&input,callbacks,&output,&failure,error,sizeof(error)),error);
    return output;
}
inline SigmoidLUT2D build_sigmoid_lut(std::uint32_t topology,std::size_t cell_nodes=41,
    std::size_t wall_nodes=31,std::size_t resolution=256) {
    tpmshx_preparation_sigmoid_lut_v6 output{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V6;output.struct_size=sizeof(output);
    char error[4096]{};
    detail::check(tpmshx_preparation_sigmoid_lut_create_v6(topology,cell_nodes,wall_nodes,resolution,
        &output,error,sizeof(error)),error);
    return SigmoidLUT2D(output);
}
namespace detail {
template<class Output> Output versioned(uint32_t version) {
    Output output{};output.abi_version=version;output.struct_size=sizeof(output);return output;
}
inline tpmshx_preparation_case_failure_v2 failure() {
    return versioned<tpmshx_preparation_case_failure_v2>(TPMSHX_PREPARATION_CASE_ABI_VERSION_V2);
}
}
// Uniform 2D preparation uses the v7 capacity queries and the v10 complete preparation.
inline InletFlow2D prepare_inlet_mass_capacities(const FlowInput2D& input,const GridKinds2D& grid,
    const PreparationOptions& options={},const tpmshx_preparation_case_callbacks_v1* callbacks=nullptr) {
    auto output=detail::versioned<tpmshx_preparation_flow_2d_v3>(TPMSHX_PREPARATION_CASE_ABI_VERSION_V3);auto failure=detail::failure();char error[4096]{};
    detail::check(tpmshx_prepare_inlet_mass_capacities_2d_v7(&input,&grid,&options,callbacks,&output,&failure,error,sizeof(error)),error);
    return InletFlow2D(output);
}
inline InletFlow2D prepare_inlet_mass_capacities(const FlowInput2D& input,const PreparationOptions& options={}) {
    return prepare_inlet_mass_capacities(input,GridKinds2D{},options);
}
inline InletFlow2D resolve_inlet_flow(const FlowInput2D& input,const GridKinds2D& grid,
    const PreparationOptions& options={},const tpmshx_preparation_case_callbacks_v1* callbacks=nullptr) {
    auto output=detail::versioned<tpmshx_preparation_flow_2d_v3>(TPMSHX_PREPARATION_CASE_ABI_VERSION_V3);auto failure=detail::failure();char error[4096]{};
    detail::check(tpmshx_resolve_inlet_flow_2d_v7(&input,&grid,&options,callbacks,&output,&failure,error,sizeof(error)),error);
    return InletFlow2D(output);
}
inline InletFlow2D resolve_inlet_flow(const FlowInput2D& input,const PreparationOptions& options={}) {
    return resolve_inlet_flow(input,GridKinds2D{},options);
}
inline PreparedFlowCase2Dv10 prepare_case(const FlowInput2D& input,const GridKinds2D& grid,
    const PreparationOptions& options={},const tpmshx_preparation_case_callbacks_v1* callbacks=nullptr) {
    auto output=detail::versioned<tpmshx_preparation_flow_case_2d_v10>(TPMSHX_PREPARATION_CASE_ABI_VERSION_V10);auto failure=detail::failure();char error[4096]{};
    detail::check(tpmshx_prepare_flow_case_2d_v10(&input,&grid,&options,callbacks,&output,&failure,error,sizeof(error)),error);
    return PreparedFlowCase2Dv10(output);
}
inline PreparedFlowCase2Dv10 prepare_case(const FlowInput2D& input,const PreparationOptions& options={}) {
    return prepare_case(input,GridKinds2D{},options);
}
// Prescribed-velocity inputs use the same complete preparation without mass targets.
inline PreparedFlowCase2Dv10 prepare_case(const CaseInput2Dv2& input,const PreparationOptions& options={}) {
    FlowInput2D flow;flow.values=input;return prepare_case(flow,options);
}
inline PreparedFlowCase2Dv10 prepare_case(const CaseInput2D& input,const PreparationOptions& options={}) {
    FlowInput2D flow;flow.values.values=input;return prepare_case(flow,options);
}
// Continuous 2D preparation uses the v7 capacity queries and the v11 complete preparation.
inline ContinuousInletFlow2D prepare_inlet_mass_capacities(const ContinuousInput2D& input,const GridKinds2D& grid,
    const PreparationOptions& options={},const tpmshx_preparation_case_callbacks_v1* callbacks=nullptr) {
    auto output=detail::versioned<tpmshx_preparation_continuous_flow_2d_v4>(TPMSHX_PREPARATION_CASE_ABI_VERSION_V4);auto failure=detail::failure();char error[4096]{};
    detail::check(tpmshx_prepare_continuous_inlet_mass_capacities_2d_v7(&input,&grid,&options,callbacks,&output,&failure,error,sizeof(error)),error);
    return ContinuousInletFlow2D(output);
}
inline ContinuousInletFlow2D prepare_inlet_mass_capacities(const ContinuousInput2D& input,const PreparationOptions& options={}) {
    return prepare_inlet_mass_capacities(input,GridKinds2D{},options);
}
inline ContinuousInletFlow2D resolve_inlet_flow(const ContinuousInput2D& input,const GridKinds2D& grid,
    const PreparationOptions& options={},const tpmshx_preparation_case_callbacks_v1* callbacks=nullptr) {
    auto output=detail::versioned<tpmshx_preparation_continuous_flow_2d_v4>(TPMSHX_PREPARATION_CASE_ABI_VERSION_V4);auto failure=detail::failure();char error[4096]{};
    detail::check(tpmshx_resolve_continuous_inlet_flow_2d_v7(&input,&grid,&options,callbacks,&output,&failure,error,sizeof(error)),error);
    return ContinuousInletFlow2D(output);
}
inline ContinuousInletFlow2D resolve_inlet_flow(const ContinuousInput2D& input,const PreparationOptions& options={}) {
    return resolve_inlet_flow(input,GridKinds2D{},options);
}
inline PreparedContinuousCase2Dv11 prepare_case(const ContinuousInput2D& input,const GridKinds2D& grid,
    const PreparationOptions& options={},const tpmshx_preparation_case_callbacks_v1* callbacks=nullptr) {
    auto output=detail::versioned<tpmshx_preparation_continuous_case_2d_v11>(TPMSHX_PREPARATION_CASE_ABI_VERSION_V11);auto failure=detail::failure();char error[4096]{};
    detail::check(tpmshx_prepare_continuous_flow_case_2d_v11(&input,&grid,&options,callbacks,&output,&failure,error,sizeof(error)),error);
    return PreparedContinuousCase2Dv11(output);
}
inline PreparedContinuousCase2Dv11 prepare_case(const ContinuousInput2D& input,const PreparationOptions& options={}) {
    return prepare_case(input,GridKinds2D{},options);
}
// Zoned and sigmoid 2D preparation uses the v10 entries. Stripe results can add v11 radii.
inline ZonedInletFlow2Dv9 prepare_inlet_mass_capacities(const ZonedFlowInput2Dv9& input,const GridKinds2D& grid={},
    const PreparationOptions& options={},const tpmshx_preparation_case_callbacks_v1* callbacks=nullptr) {
    auto output=detail::versioned<tpmshx_preparation_zoned_flow_2d_v9>(TPMSHX_PREPARATION_CASE_ABI_VERSION_V9);auto failure=detail::failure();char error[4096]{};
    detail::check(tpmshx_prepare_zoned_inlet_mass_capacities_2d_v10(&input,&grid,&options,callbacks,&output,&failure,error,sizeof(error)),error);
    return ZonedInletFlow2Dv9(output);
}
inline ZonedInletFlow2Dv9 resolve_inlet_flow(const ZonedFlowInput2Dv9& input,const GridKinds2D& grid={},
    const PreparationOptions& options={},const tpmshx_preparation_case_callbacks_v1* callbacks=nullptr) {
    auto output=detail::versioned<tpmshx_preparation_zoned_flow_2d_v9>(TPMSHX_PREPARATION_CASE_ABI_VERSION_V9);auto failure=detail::failure();char error[4096]{};
    detail::check(tpmshx_resolve_zoned_inlet_flow_2d_v10(&input,&grid,&options,callbacks,&output,&failure,error,sizeof(error)),error);
    return ZonedInletFlow2Dv9(output);
}
inline PreparedZonedFlowCase2Dv10 prepare_case(const ZonedFlowInput2Dv9& input,const GridKinds2D& grid={},
    const PreparationOptions& options={},const tpmshx_preparation_case_callbacks_v1* callbacks=nullptr) {
    auto output=detail::versioned<tpmshx_preparation_zoned_flow_case_2d_v10>(TPMSHX_PREPARATION_CASE_ABI_VERSION_V10);auto failure=detail::failure();char error[4096]{};
    detail::check(tpmshx_prepare_zoned_flow_case_2d_v10(&input,&grid,&options,callbacks,&output,&failure,error,sizeof(error)),error);
    return PreparedZonedFlowCase2Dv10(output);
}
inline SigmoidInletFlow2Dv9 prepare_inlet_mass_capacities(const SigmoidFlowInput2Dv9& input,const GridKinds2D& grid={},
    const PreparationOptions& options={},const tpmshx_preparation_case_callbacks_v1* callbacks=nullptr) {
    auto output=detail::versioned<tpmshx_preparation_sigmoid_flow_2d_v9>(TPMSHX_PREPARATION_CASE_ABI_VERSION_V9);auto failure=detail::failure();char error[4096]{};
    detail::check(tpmshx_prepare_sigmoid_inlet_mass_capacities_2d_v10(&input,&grid,&options,callbacks,&output,&failure,error,sizeof(error)),error);
    return SigmoidInletFlow2Dv9(output);
}
inline SigmoidInletFlow2Dv9 resolve_inlet_flow(const SigmoidFlowInput2Dv9& input,const GridKinds2D& grid={},
    const PreparationOptions& options={},const tpmshx_preparation_case_callbacks_v1* callbacks=nullptr) {
    auto output=detail::versioned<tpmshx_preparation_sigmoid_flow_2d_v9>(TPMSHX_PREPARATION_CASE_ABI_VERSION_V9);auto failure=detail::failure();char error[4096]{};
    detail::check(tpmshx_resolve_sigmoid_inlet_flow_2d_v10(&input,&grid,&options,callbacks,&output,&failure,error,sizeof(error)),error);
    return SigmoidInletFlow2Dv9(output);
}
inline PreparedSigmoidFlowCase2Dv10 prepare_case(const SigmoidFlowInput2Dv9& input,const GridKinds2D& grid={},
    const PreparationOptions& options={},const tpmshx_preparation_case_callbacks_v1* callbacks=nullptr) {
    auto output=detail::versioned<tpmshx_preparation_sigmoid_flow_case_2d_v10>(TPMSHX_PREPARATION_CASE_ABI_VERSION_V10);auto failure=detail::failure();char error[4096]{};
    detail::check(tpmshx_prepare_sigmoid_flow_case_2d_v10(&input,&grid,&options,callbacks,&output,&failure,error,sizeof(error)),error);
    return PreparedSigmoidFlowCase2Dv10(output);
}
inline PreparedStripeCase2Dv11 prepare_stripe_case(const ZonedFlowInput2Dv9& input,const GridKinds2D& grid={},
    const PreparationOptions& options={},const tpmshx_preparation_case_callbacks_v1* callbacks=nullptr) {
    auto output=detail::versioned<tpmshx_preparation_stripe_flow_case_2d_v11>(TPMSHX_PREPARATION_CASE_ABI_VERSION_V11);auto failure=detail::failure();char error[4096]{};
    detail::check(tpmshx_prepare_stripe_flow_case_2d_v11(&input,&grid,&options,callbacks,&output,&failure,error,sizeof(error)),error);
    return PreparedStripeCase2Dv11(output);
}
// Prescribed-velocity zoned and sigmoid inputs use the v10 entries with the input conductivity.
inline PreparedZonedFlowCase2Dv10 prepare_case(const ZonedInput2D& input,const PreparationOptions& options={}) {
    ZonedFlowInput2Dv9 flow;flow.values.values=input;
    flow.model.solid_conductivity_W_mK=input.values.values.solid_conductivity_W_mK;
    flow.model.solid_conductivity_kind=input.values.kinds.solid_conductivity;
    return prepare_case(flow,GridKinds2D{},options);
}
inline PreparedSigmoidFlowCase2Dv10 prepare_case(const SigmoidInput2D& input,const PreparationOptions& options={}) {
    SigmoidFlowInput2Dv9 flow;flow.values.values=input;
    flow.model.solid_conductivity_W_mK=input.values.values.values.solid_conductivity_W_mK;
    flow.model.solid_conductivity_kind=input.values.values.kinds.solid_conductivity;
    return prepare_case(flow,GridKinds2D{},options);
}
// 3D preparation uses continuous v3 and spatial v4. Uniform inputs use spatial v4 without cells.
inline ContinuousInletFlow3D prepare_inlet_mass_capacities(const ContinuousInput3D& input,const PreparationOptions& options={}) {
    auto output=detail::versioned<tpmshx_preparation_continuous_flow_3d_v3>(TPMSHX_PREPARATION_CONTINUOUS_3D_ABI_VERSION);auto failure=detail::failure();char error[4096]{};
    detail::check(tpmshx_prepare_inlet_mass_capacities_3d_v3(&input,&options,nullptr,&output,&failure,error,sizeof(error)),error);
    return ContinuousInletFlow3D(output);
}
inline ContinuousInletFlow3D resolve_inlet_flow(const ContinuousInput3D& input,const PreparationOptions& options={}) {
    auto output=detail::versioned<tpmshx_preparation_continuous_flow_3d_v3>(TPMSHX_PREPARATION_CONTINUOUS_3D_ABI_VERSION);auto failure=detail::failure();char error[4096]{};
    detail::check(tpmshx_resolve_inlet_flow_3d_v3(&input,&options,nullptr,&output,&failure,error,sizeof(error)),error);
    return ContinuousInletFlow3D(output);
}
inline PreparedContinuousCase3D prepare_case(const ContinuousInput3D& input,const PreparationOptions& options={}) {
    auto output=detail::versioned<tpmshx_preparation_continuous_case_3d_v3>(TPMSHX_PREPARATION_CONTINUOUS_3D_ABI_VERSION);auto failure=detail::failure();char error[4096]{};
    detail::check(tpmshx_prepare_flow_case_3d_v3(&input,&options,nullptr,&output,&failure,error,sizeof(error)),error);
    return PreparedContinuousCase3D(output);
}
inline SpatialInletFlow3D prepare_inlet_mass_capacities(const SpatialInput3D& input,const PreparationOptions& options={}) {
    auto output=detail::versioned<tpmshx_preparation_spatial_flow_3d_v4>(TPMSHX_PREPARATION_SPATIAL_3D_ABI_VERSION);auto failure=detail::failure();char error[4096]{};
    detail::check(tpmshx_prepare_inlet_mass_capacities_3d_v4(&input,&options,nullptr,&output,&failure,error,sizeof(error)),error);
    return SpatialInletFlow3D(output);
}
inline SpatialInletFlow3D resolve_inlet_flow(const SpatialInput3D& input,const PreparationOptions& options={}) {
    auto output=detail::versioned<tpmshx_preparation_spatial_flow_3d_v4>(TPMSHX_PREPARATION_SPATIAL_3D_ABI_VERSION);auto failure=detail::failure();char error[4096]{};
    detail::check(tpmshx_resolve_inlet_flow_3d_v4(&input,&options,nullptr,&output,&failure,error,sizeof(error)),error);
    return SpatialInletFlow3D(output);
}
inline PreparedSpatialCase3D prepare_case(const SpatialInput3D& input,const PreparationOptions& options={}) {
    auto output=detail::versioned<tpmshx_preparation_spatial_case_3d_v4>(TPMSHX_PREPARATION_SPATIAL_3D_ABI_VERSION);auto failure=detail::failure();char error[4096]{};
    detail::check(tpmshx_prepare_flow_case_3d_v4(&input,&options,nullptr,&output,&failure,error,sizeof(error)),error);
    return PreparedSpatialCase3D(output);
}
inline SpatialInletFlow3D prepare_inlet_mass_capacities(const FlowInput3D& input,const PreparationOptions& options={}) {
    SpatialInput3D spatial;spatial.values=input;return prepare_inlet_mass_capacities(spatial,options);
}
inline SpatialInletFlow3D resolve_inlet_flow(const FlowInput3D& input,const PreparationOptions& options={}) {
    SpatialInput3D spatial;spatial.values=input;return resolve_inlet_flow(spatial,options);
}
inline PreparedSpatialCase3D prepare_case(const FlowInput3D& input,const PreparationOptions& options={}) {
    SpatialInput3D spatial;spatial.values=input;return prepare_case(spatial,options);
}
inline PreparedSpatialCase3D prepare_case(const CaseInput3D& input,const PreparationOptions& options={}) {
    FlowInput3D flow;flow.input=input;return prepare_case(flow,options);
}
// Build the saved descriptor for one prepared owner. Keep both unchanged until result transfer.
inline SavedCase2Dv4 saved_case(const PreparedFlowCase2Dv10& prepared) {return SavedCase2Dv4(prepared);}
inline SavedCase2Dv4 saved_case(const PreparedZonedFlowCase2Dv10& prepared) {return SavedCase2Dv4(prepared);}
inline SavedCase2Dv4 saved_case(const PreparedSigmoidFlowCase2Dv10& prepared) {return SavedCase2Dv4(prepared);}
inline SavedCase2Dv4 saved_case(const PreparedContinuousCase2Dv11& prepared) {return SavedCase2Dv4(prepared);}
inline SavedCase2Dv4 saved_case(const PreparedStripeCase2Dv11& prepared) {return SavedCase2Dv4(prepared);}
inline SavedPreparedCase3D saved_case(const PreparedSpatialCase3D& prepared) {return SavedPreparedCase3D(prepared);}
inline SavedPreparedCase3D saved_case(const PreparedContinuousCase3D& prepared) {return SavedPreparedCase3D(prepared);}
// Each result owns its copied storage. The prepared owner can be released afterwards.
inline RunResult2D run_case(const tpmshx_stage_saved_case_2d_v4& saved,const RunControl& control,
    const RunRequest2Dv3& request={}) {
    auto output=detail::versioned<tpmshx_stage_run_result_2d_v1>(TPMSHX_STAGE_RUN_ABI_VERSION);char error[4096]{};
    detail::check(tpmshx_run_saved_case_2d_v4(&saved,&request,&control,&output,error,sizeof(error)),error);
    return RunResult2D(output);
}
inline RunResult2D run_case(const PreparedFlowCase2Dv10& prepared,const RunControl& control,const RunRequest2Dv3& request={}) {
    return run_case(saved_case(prepared),control,request);
}
inline RunResult2D run_case(const PreparedZonedFlowCase2Dv10& prepared,const RunControl& control,const RunRequest2Dv3& request={}) {
    return run_case(saved_case(prepared),control,request);
}
inline RunResult2D run_case(const PreparedSigmoidFlowCase2Dv10& prepared,const RunControl& control,const RunRequest2Dv3& request={}) {
    return run_case(saved_case(prepared),control,request);
}
inline RunResult2D run_case(const PreparedContinuousCase2Dv11& prepared,const RunControl& control,const RunRequest2Dv3& request={}) {
    return run_case(saved_case(prepared),control,request);
}
inline RunResult2D run_case(const PreparedStripeCase2Dv11& prepared,const RunControl& control,const RunRequest2Dv3& request={}) {
    return run_case(saved_case(prepared),control,request);
}
inline RunResult3D run_case(const tpmshx_stage_saved_case_3d_v2& saved,const RunControl3D& control,
    const RunRequest3D& request={}) {
    auto output=detail::versioned<tpmshx_stage_run_result_3d_v1>(TPMSHX_STAGE_RUN_3D_ABI_VERSION);char error[4096]{};
    detail::check(tpmshx_run_saved_case_3d_v2(&saved,&request,&control,&output,error,sizeof(error)),error);
    return RunResult3D(output);
}
inline RunResult3D run_case(const PreparedSpatialCase3D& prepared,const RunControl3D& control,const RunRequest3D& request={}) {
    return run_case(saved_case(prepared),control,request);
}
inline RunResult3D run_case(const PreparedContinuousCase3D& prepared,const RunControl3D& control,const RunRequest3D& request={}) {
    return run_case(saved_case(prepared),control,request);
}
// Full-result queries pass the captured v3 host input directly.
inline Evaluation evaluate(const RunResult3D& result,const tpmshx_stage_metric_spec_v1* metric=nullptr) {
    tpmshx_stage_output_v1 output{};output.struct_size=sizeof(output);char error[4096]{};
    tpmshx_result_diagnostics_v1 diagnostics{};uint64_t token=0;
    detail::check(tpmshx_result_stage_query_v3(&result.view().evaluation,0,metric,nullptr,0,
        &output,&diagnostics,&token,error,sizeof(error)),error);
    return Evaluation(output);
}
inline Evaluation evaluate(const RunResult2D& result,const tpmshx_stage_metric_spec_v1* metric=nullptr) {
    tpmshx_stage_output_v1 output{};output.struct_size=sizeof(output);
    char error[4096]{};
    detail::check(tpmshx_result_stage_evaluate_v1(&result.view().evidence,metric,&output,error,sizeof(error)),error);
    return Evaluation(output);
}
using RunResultQuickDesign=detail::Owned<tpmshx_quick_run_result_v1,tpmshx_quick_run_release_v1>;
using PreparedQuickDesignV2=detail::Owned<tpmshx_quick_prepared_v2,tpmshx_quick_prepared_release_v2>;
struct QuickDesignInputV2 : tpmshx_quick_input_v2 {
    QuickDesignInputV2():tpmshx_quick_input_v2{} {
        abi_version=2;struct_size=sizeof(tpmshx_quick_input_v2);
        for(auto& value:values)value={0.,64,0};
    }
};
inline PreparedQuickDesignV2 prepare_quick_design(const QuickDesignInputV2& input,
                                                 const tpmshx_quick_callbacks_v2* callbacks=nullptr) {
    tpmshx_quick_prepared_v2 output{};output.abi_version=2;output.struct_size=sizeof(output);
    char error[4096]{};
    detail::check(tpmshx_prepare_quick_design_v2(&input,callbacks,&output,error,sizeof(error)),error);
    return PreparedQuickDesignV2(output);
}
inline tpmshx_quick_pressure_v2 pressure_fractions(const QuickDesignInputV2& input,
                                                 const tpmshx_quick_callbacks_v2* callbacks=nullptr) {
    tpmshx_quick_pressure_v2 output{};output.abi_version=2;output.struct_size=sizeof(output);
    char error[4096]{};
    detail::check(tpmshx_quick_pressure_fractions_v2(&input,callbacks,&output,error,sizeof(error)),error);
    return output;
}
inline RunResultQuickDesign run_case(const QuickDesignInputV2& input,const PreparedQuickDesignV2& prepared,
                                    const tpmshx_quick_run_control_v1& control) {
    tpmshx_quick_run_result_v1 output{};
    output.abi_version=TPMSHX_QUICK_DESIGN_STAGE_ABI_VERSION;output.struct_size=sizeof(output);
    char error[4096]{};
    detail::check(tpmshx_run_quick_design_v2(&input,&prepared.view(),&control,&output,error,sizeof(error)),error);
    return RunResultQuickDesign(output);
}
inline Evaluation evaluate(const RunResultQuickDesign& result,const tpmshx_stage_metric_spec_v1* metric=nullptr) {
    tpmshx_stage_output_v1 output{};output.struct_size=sizeof(output);
    char error[4096]{};
    detail::check(tpmshx_result_stage_evaluate_v1(&result.view().evidence,metric,&output,error,sizeof(error)),error);
    return Evaluation(output);
}
}  // namespace tpmshx::stages
