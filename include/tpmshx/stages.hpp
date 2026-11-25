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
#include <type_traits>
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

constexpr unsigned default_cpu_threads(unsigned reported = std::thread::hardware_concurrency()) noexcept {
    return std::clamp(reported, 1u, 8u);
}
}
using InletFlow2D=detail::Owned<tpmshx_preparation_2d_uniform_flow_v1,tpmshx_preparation_2d_uniform_flow_release_v1>;
using ContinuousInletFlow2D=detail::Owned<tpmshx_preparation_2d_continuous_flow_v1,tpmshx_preparation_2d_continuous_flow_release_v1>;
using SigmoidLUT2D=detail::Owned<tpmshx_preparation_sigmoid_lut_v7,tpmshx_preparation_sigmoid_lut_release_v7>;
using ZonedInletFlow2D=detail::Owned<tpmshx_preparation_2d_zoned_flow_v1,tpmshx_preparation_2d_zoned_flow_release_v1>;
using SigmoidInletFlow2D=detail::Owned<tpmshx_preparation_2d_sigmoid_flow_v1,tpmshx_preparation_2d_sigmoid_flow_release_v1>;
using PreparedUniformCase2D=detail::Owned<tpmshx_preparation_2d_uniform_case_v1,tpmshx_preparation_2d_uniform_case_release_v1>;
using PreparedZonedFlowCase2D=detail::Owned<tpmshx_preparation_2d_zoned_case_v1,tpmshx_preparation_2d_zoned_case_release_v1>;
using PreparedSigmoidFlowCase2D=detail::Owned<tpmshx_preparation_2d_sigmoid_case_v1,tpmshx_preparation_2d_sigmoid_case_release_v1>;
using PreparedContinuousCase2D=detail::Owned<tpmshx_preparation_2d_continuous_case_v1,tpmshx_preparation_2d_continuous_case_release_v1>;
using PreparedStripeCase2D=detail::Owned<tpmshx_preparation_2d_stripe_case_v1,tpmshx_preparation_2d_stripe_case_release_v1>;
using ContinuousInletFlow3D=detail::Owned<tpmshx_preparation_3d_continuous_flow_v1,tpmshx_preparation_3d_continuous_flow_release_v1>;
using PreparedContinuousCase3D=detail::Owned<tpmshx_preparation_3d_continuous_case_v1,tpmshx_preparation_3d_continuous_case_release_v1>;
using SpatialInletFlow3D=detail::Owned<tpmshx_preparation_3d_spatial_flow_v1,tpmshx_preparation_3d_spatial_flow_release_v1>;
using PreparedSpatialCase3D=detail::Owned<tpmshx_preparation_3d_spatial_case_v1,tpmshx_preparation_3d_spatial_case_release_v1>;
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
struct PreparationCallbacks : tpmshx_preparation_callbacks_v1 {
    PreparationCallbacks():tpmshx_preparation_callbacks_v1{} {
        abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION;struct_size=sizeof(tpmshx_preparation_callbacks_v1);
    }
};
struct InletPropertyQuery : tpmshx_preparation_inlet_query_input_v1 {
    InletPropertyQuery():tpmshx_preparation_inlet_query_input_v1{} {
        abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION;struct_size=sizeof(tpmshx_preparation_inlet_query_input_v1);
    }
};
struct CaseInput3D : tpmshx_preparation_case_input_3d_v1 {
    CaseInput3D():tpmshx_preparation_case_input_3d_v1{} {
        abi_version=TPMSHX_PREPARATION_CASE_3D_ABI_VERSION;struct_size=sizeof(tpmshx_preparation_case_input_3d_v1);
        max_cells=2000000;
        for (auto& side:sides) side.port.active=1;
    }
};
struct ContinuousInput3D : tpmshx_preparation_3d_continuous_input_v1 {
    ContinuousInput3D():tpmshx_preparation_3d_continuous_input_v1{} {
        abi_version=TPMSHX_PREPARATION_CASE_3D_ABI_VERSION;struct_size=sizeof(tpmshx_preparation_3d_continuous_input_v1);
        input=CaseInput3D{};input.geometry_mode=1;
    }
};
struct SpatialInput3D : tpmshx_preparation_3d_spatial_input_v1 {
    SpatialInput3D():tpmshx_preparation_3d_spatial_input_v1{} {
        abi_version=TPMSHX_PREPARATION_CASE_3D_ABI_VERSION;struct_size=sizeof(tpmshx_preparation_3d_spatial_input_v1);
        input=CaseInput3D{};
    }
};
struct FlowInput2D : tpmshx_preparation_2d_uniform_input_v1 {
    FlowInput2D():tpmshx_preparation_2d_uniform_input_v1{} {
        abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION;struct_size=sizeof(tpmshx_preparation_2d_uniform_input_v1);
        input=CaseInput2D{};
    }
};
struct ContinuousInput2D : tpmshx_preparation_2d_continuous_input_v1 {
    ContinuousInput2D():tpmshx_preparation_2d_continuous_input_v1{} {
        abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION;struct_size=sizeof(tpmshx_preparation_2d_continuous_input_v1);
        input=CaseInput2D{};input.geometry_mode=1;
    }
};
struct ZonedFlowInput2D : tpmshx_preparation_2d_zoned_input_v1 {
    ZonedFlowInput2D():tpmshx_preparation_2d_zoned_input_v1{} {
        abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION;struct_size=sizeof(tpmshx_preparation_2d_zoned_input_v1);
        input=CaseInput2D{};input.geometry_mode=2;axis=1;model.solid_conductivity_W_mK=16.;
    }
};
struct SigmoidFlowInput2D : tpmshx_preparation_2d_sigmoid_input_v1 {
    SigmoidFlowInput2D():tpmshx_preparation_2d_sigmoid_input_v1{} {
        abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION;struct_size=sizeof(tpmshx_preparation_2d_sigmoid_input_v1);
        input=CaseInput2D{};input.geometry_mode=2;kind=1;axis=1;
        controls.inlet_transition=controls.outlet_transition=.2;
        model.solid_conductivity_W_mK=16.;
    }
};
struct RunRequest2D : tpmshx_stage_run_request_2d_v4 {
    RunRequest2D():tpmshx_stage_run_request_2d_v4{} {
        abi_version=TPMSHX_STAGE_RUN_ABI_VERSION_V4;struct_size=sizeof(tpmshx_stage_run_request_2d_v4);
    }
};
struct RunControl : tpmshx_stage_run_control_v1 {
    RunControl():tpmshx_stage_run_control_v1{} {
        cpu_threads = detail::default_cpu_threads();
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
/* Flat saved v5 descriptor for one prepared 2D owner. The descriptor borrows the
 * prepared arrays. It owns a copy of the prepared view without outlet fractions
 * (computed by the saved run) and the reversed stream widths. Keep the prepared
 * owner alive and unchanged until result transfer or run release. The descriptor
 * cannot move because it points into its own storage. */
class SavedCase2D : public tpmshx_stage_saved_case_2d_v5 {
public:
    explicit SavedCase2D(const PreparedUniformCase2D& prepared):tpmshx_stage_saved_case_2d_v5{} {
        const auto& value=prepared.view();
        fill(value.prepared,{},{},nullptr,&value.thermal);
    }
    explicit SavedCase2D(const PreparedZonedFlowCase2D& prepared):tpmshx_stage_saved_case_2d_v5{} {
        const auto& value=prepared.view();
        fill(value.prepared,value.area_density_per_m,value.hydraulic_diameter_m,value.fluid_conductivity,&value.thermal);
    }
    explicit SavedCase2D(const PreparedSigmoidFlowCase2D& prepared):tpmshx_stage_saved_case_2d_v5{} {
        const auto& value=prepared.view();
        fill(value.prepared,value.area_density_per_m,value.hydraulic_diameter_m,value.fluid_conductivity,&value.thermal);
    }
    explicit SavedCase2D(const PreparedStripeCase2D& prepared):tpmshx_stage_saved_case_2d_v5{} {
        const auto& value=prepared.view();
        fill(value.prepared,value.area_density_per_m,value.hydraulic_diameter_m,value.fluid_conductivity,&value.thermal);
    }
    explicit SavedCase2D(const PreparedContinuousCase2D& prepared):tpmshx_stage_saved_case_2d_v5{} {
        const auto& value=prepared.view();
        fill(value.prepared,value.area_density_per_m,value.hydraulic_diameter_m,value.fluid_conductivity,nullptr);
    }
    // A conversion can create a temporary owner or return a reference into a temporary source.
    explicit SavedCase2D(const PreparedUniformCase2D&&)=delete;
    explicit SavedCase2D(const PreparedZonedFlowCase2D&&)=delete;
    explicit SavedCase2D(const PreparedSigmoidFlowCase2D&&)=delete;
    explicit SavedCase2D(const PreparedStripeCase2D&&)=delete;
    explicit SavedCase2D(const PreparedContinuousCase2D&&)=delete;
    template<class Source> explicit SavedCase2D(const Source&&)=delete;
    SavedCase2D(const SavedCase2D&)=delete;
    SavedCase2D& operator=(const SavedCase2D&)=delete;
private:
    void fill(const tpmshx_preparation_case_2d_v1& source,tpmshx_preparation_array_v1 area,
        tpmshx_preparation_array_v1 diameter,const tpmshx_preparation_array_v1* conductivity,
        const tpmshx_preparation_thermal_sides_2d_v10* thermal) {
        prepared_=source;
        for(auto& side:prepared_.sides)side.outlet_u_fraction={};
        abi_version=TPMSHX_STAGE_RUN_ABI_VERSION_V5;struct_size=sizeof(tpmshx_stage_saved_case_2d_v5);
        prepared=&prepared_;
        inlet_recorded=1;
        area_density_per_m=area;hydraulic_diameter_m=diameter;
        if(conductivity)std::copy_n(conductivity,2,fluid_conductivity);
        if(thermal) {
            have_side_geometry=thermal->have_side_geometry;
            for(size_t side=0;side<2;++side)std::copy_n(thermal->side_geometry[side],4,side_geometry[side]);
        }
        lengths_m[0]=source.input.length_m;lengths_m[1]=source.input.height_m;
        for(size_t side=0;side<2;++side) {
            const auto& s=source.sides[side];auto& grid=flow_grid[side];
            const auto direction=s.inlet.port.direction;
            if(direction<0 || direction>3)throw std::invalid_argument("invalid prepared 2D direction");
            const auto cross=direction<2?source.dy:source.dx,stream=direction<2?source.dx:source.dy;
            stream_[side].assign(stream.data,stream.data+stream.size);
            if(direction%2)std::reverse(stream_[side].begin(),stream_[side].end());
            grid.cross=cross;grid.stream={stream_[side].data(),stream_[side].size()};
            grid.direction=static_cast<uint32_t>(direction);
            const double bounds[]{s.inlet_bounds[0],s.inlet_bounds[1],s.outlet_bounds[0],s.outlet_bounds[1]};
            std::copy_n(bounds,4,grid.bounds);
            resource_fluids[side]=detail::fluid_text(s.inlet.fluid);
            resource_nu[side]=source.sco2_nu;
        }
        resource_topology=detail::topology_text(source.input.topology);
        auto& settings=experiment;
        settings.topology=source.input.topology;settings.geometry_mode=source.input.geometry_mode;
        settings.domain_count=source.input.have_physical_depth?3:2;
        settings.domain_m[0]=source.input.length_m;settings.domain_m[1]=source.input.height_m;
        settings.domain_m[2]=source.input.have_physical_depth?source.input.physical_depth_m:0.;
        settings.cell_length_mm=source.input.cell_length_mm;settings.wall_thickness_mm=source.input.wall_thickness_mm;
        settings.delta_levelset=source.input.delta_levelset;
        for(size_t side=0;side<2;++side) {
            settings.fluids[side]=source.sides[side].inlet.fluid;
            settings.velocity_m_s[side]=source.sides[side].inlet.velocity_m_s;
        }
    }
    tpmshx_preparation_case_2d_v1 prepared_{};
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
// A temporary adapter can own the result that supplies the audit spans.
inline tpmshx_stage_capture_3d_v1 capture_summary(const RunResult3D&&,bool)=delete;
template<class Source, std::enable_if_t<!std::is_lvalue_reference_v<Source> &&
    std::is_convertible_v<Source, const RunResult3D&>, int> = 0>
void capture_summary(Source&&,bool)=delete;
namespace detail {
// Prefer the reference if a named adapter can also supply a result by value.
void require_audit_result_lvalue(const RunResult3D&);
template<class = void> void require_audit_result_lvalue(const RunResult3D&&)=delete;
}
template<class... Explicit, class Source, std::enable_if_t<
    sizeof...(Explicit)==0 && std::is_lvalue_reference_v<Source>,int> = 0>
inline auto capture_summary(Source&& source,bool include_audit)
    -> decltype(detail::require_audit_result_lvalue(source),tpmshx_stage_capture_3d_v1{}) {
    const RunResult3D& result=source;
    return capture_summary(result,include_audit);
}

class SavedPreparedCase3D;
struct SavedCase3D : tpmshx_stage_saved_case_3d_v3 {
    SavedCase3D():tpmshx_stage_saved_case_3d_v3{} {
        abi_version=TPMSHX_STAGE_RUN_3D_SAVED_ABI_VERSION;struct_size=sizeof(tpmshx_stage_saved_case_3d_v3);
        inlet_recorded=1;
    }
    // A copy of a prepared descriptor still points into the original descriptor.
    SavedCase3D(const SavedPreparedCase3D&&)=delete;
    SavedCase3D& operator=(const SavedPreparedCase3D&&)=delete;
    template<class Source, std::enable_if_t<!std::is_same_v<Source, SavedCase3D>, int> = 0>
    SavedCase3D(const Source&&)=delete;
    template<class Source, std::enable_if_t<!std::is_same_v<Source, SavedCase3D>, int> = 0>
    SavedCase3D& operator=(const Source&&)=delete;
};
struct RunRequest3D : tpmshx_stage_run_request_3d_v1 {
    RunRequest3D():tpmshx_stage_run_request_3d_v1{} {
        abi_version=TPMSHX_STAGE_RUN_3D_ABI_VERSION;struct_size=sizeof(tpmshx_stage_run_request_3d_v1);
    }
};
struct RunControl3D : tpmshx_stage_run_control_3d_v1 {
    RunControl3D():tpmshx_stage_run_control_3d_v1{} {
        result_id="native-3d";
        cpu_threads = detail::default_cpu_threads();
    }
};
namespace detail {
inline double nominal_mm(double value) {return value;}
inline tpmshx_full3d_array_v1 view(tpmshx_preparation_array_v1 value) {return {value.data,value.size};}
}
/* Flat saved v3 descriptor for one prepared 3D owner. It copies the solver input
 * and borrows all prepared arrays and texts. Keep the prepared owner alive and
 * unchanged until result transfer or run release. The descriptor cannot move
 * because it points into its own storage. */
class SavedPreparedCase3D : public SavedCase3D {
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
    explicit SavedPreparedCase3D(const PreparedSpatialCase3D&&)=delete;
    explicit SavedPreparedCase3D(const PreparedContinuousCase3D&&)=delete;
    template<class Source> explicit SavedPreparedCase3D(const Source&&)=delete;
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
            lengths_m[axis]=p.input.lengths_m[axis];
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
        const auto cell=detail::nominal_mm(p.input.cell_length_mm);
        const auto wall=detail::nominal_mm(p.input.wall_thickness_mm);
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
        input=&in;nominal_cell_length_mm=cell;nominal_wall_thickness_mm=wall;
        nominal_porosity=p.geometry.epsilon;wall_thickness_m=p.wall_thickness;
        preparation=p.evidence;notices=p.notices;notice_count=p.notice_count;
        design_mode=mode;have_z_controls=have_z;
        std::copy_n(p.models,4,models);
        resource_topology=detail::topology_text(p.input.topology);sco2_nu=p.input.sco2_nu;
    }
    tpmshx_full3d_input_v1 input_{};
};
// Keep the saved descriptor and its prepared owner alive and unchanged until take_result or release.
class Run3D {
public:
    Run3D(const tpmshx_stage_saved_case_3d_v3& saved,const RunControl3D& control,const RunRequest3D& request={},
        const RunState* state=nullptr) {
        char error[4096]{};
        const auto status=state?tpmshx_stage_run_3d_restore_saved_v3(&saved,&request,&control,
            state->view().fields,state->view().count,&run_,error,sizeof(error)):
            tpmshx_stage_run_3d_create_saved_v3(&saved,&request,&control,&run_,error,sizeof(error));
        detail::check(status,error);
    }
    Run3D(const tpmshx_stage_saved_case_3d_v3&&,const RunControl3D&,const RunRequest3D& = {},
        const RunState* = nullptr)=delete;
    template<class Source>
    Run3D(const Source&&,const RunControl3D&,const RunRequest3D& = {},const RunState* = nullptr)=delete;
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
    Run2D(const tpmshx_stage_saved_case_2d_v5& saved,const RunControl& control,const RunRequest2D& request={},
        const RunState* state=nullptr) {
        char error[4096]{};
        const auto status=state?tpmshx_stage_run_2d_restore_saved_v5(&saved,&request,&control,
            state->view().fields,state->view().count,&run_,error,sizeof(error)):
            tpmshx_stage_run_2d_create_saved_v5(&saved,&request,&control,&run_,error,sizeof(error));
        detail::check(status,error);
    }
    Run2D(const tpmshx_stage_saved_case_2d_v5&&,const RunControl&,const RunRequest2D& = {},
        const RunState* = nullptr)=delete;
    template<class Source>
    Run2D(const Source&&,const RunControl&,const RunRequest2D& = {},const RunState* = nullptr)=delete;
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
    const InletPropertyQuery& input,const tpmshx_preparation_callbacks_v1* callbacks=nullptr) {
    tpmshx_preparation_inlet_query_result_v1 output{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION;output.struct_size=sizeof(output);
    tpmshx_preparation_case_failure_v2 failure{};
    failure.abi_version=TPMSHX_PREPARATION_FAILURE_ABI_VERSION;failure.struct_size=sizeof(failure);char error[4096]{};
    detail::check(tpmshx_query_inlet_properties_v2(&input,callbacks,&output,&failure,error,sizeof(error)),error);
    return output;
}
inline SigmoidLUT2D build_sigmoid_lut(std::uint32_t topology,std::size_t cell_nodes=41,
    std::size_t wall_nodes=31,std::size_t resolution=256) {
    tpmshx_preparation_sigmoid_lut_v7 output{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION;output.struct_size=sizeof(output);
    char error[4096]{};
    detail::check(tpmshx_preparation_sigmoid_lut_create_v7(topology,cell_nodes,wall_nodes,resolution,
        &output,error,sizeof(error)),error);
    return SigmoidLUT2D(output);
}
namespace detail {
template<class Output> Output versioned(uint32_t version) {
    Output output{};output.abi_version=version;output.struct_size=sizeof(output);return output;
}
inline tpmshx_preparation_case_failure_v2 failure() {
    return versioned<tpmshx_preparation_case_failure_v2>(TPMSHX_PREPARATION_FAILURE_ABI_VERSION);
}
}
inline InletFlow2D prepare_inlet_mass_capacities(const FlowInput2D& input,
    const PreparationOptions& options={},const tpmshx_preparation_callbacks_v1* callbacks=nullptr) {
    auto output=detail::versioned<tpmshx_preparation_2d_uniform_flow_v1>(TPMSHX_PREPARATION_CASE_ABI_VERSION);
    auto failure=detail::failure();char error[4096]{};
    detail::check(tpmshx_preparation_2d_uniform_capacities_v1(&input,&options,callbacks,&output,&failure,error,sizeof(error)),error);
    return InletFlow2D(output);
}
inline InletFlow2D resolve_inlet_flow(const FlowInput2D& input,
    const PreparationOptions& options={},const tpmshx_preparation_callbacks_v1* callbacks=nullptr) {
    auto output=detail::versioned<tpmshx_preparation_2d_uniform_flow_v1>(TPMSHX_PREPARATION_CASE_ABI_VERSION);
    auto failure=detail::failure();char error[4096]{};
    detail::check(tpmshx_preparation_2d_uniform_resolve_flow_v1(&input,&options,callbacks,&output,&failure,error,sizeof(error)),error);
    return InletFlow2D(output);
}
inline PreparedUniformCase2D prepare_case(const FlowInput2D& input,
    const PreparationOptions& options={},const tpmshx_preparation_callbacks_v1* callbacks=nullptr) {
    auto output=detail::versioned<tpmshx_preparation_2d_uniform_case_v1>(TPMSHX_PREPARATION_CASE_ABI_VERSION);
    auto failure=detail::failure();char error[4096]{};
    detail::check(tpmshx_preparation_2d_uniform_prepare_case_v1(&input,&options,callbacks,&output,&failure,error,sizeof(error)),error);
    return PreparedUniformCase2D(output);
}
inline PreparedUniformCase2D prepare_case(const CaseInput2D& input,const PreparationOptions& options={}) {
    FlowInput2D flow;flow.input=input;return prepare_case(flow,options);
}
inline ContinuousInletFlow2D prepare_inlet_mass_capacities(const ContinuousInput2D& input,
    const PreparationOptions& options={},const tpmshx_preparation_callbacks_v1* callbacks=nullptr) {
    auto output=detail::versioned<tpmshx_preparation_2d_continuous_flow_v1>(TPMSHX_PREPARATION_CASE_ABI_VERSION);
    auto failure=detail::failure();char error[4096]{};
    detail::check(tpmshx_preparation_2d_continuous_capacities_v1(&input,&options,callbacks,&output,&failure,error,sizeof(error)),error);
    return ContinuousInletFlow2D(output);
}
inline ContinuousInletFlow2D resolve_inlet_flow(const ContinuousInput2D& input,
    const PreparationOptions& options={},const tpmshx_preparation_callbacks_v1* callbacks=nullptr) {
    auto output=detail::versioned<tpmshx_preparation_2d_continuous_flow_v1>(TPMSHX_PREPARATION_CASE_ABI_VERSION);
    auto failure=detail::failure();char error[4096]{};
    detail::check(tpmshx_preparation_2d_continuous_resolve_flow_v1(&input,&options,callbacks,&output,&failure,error,sizeof(error)),error);
    return ContinuousInletFlow2D(output);
}
inline PreparedContinuousCase2D prepare_case(const ContinuousInput2D& input,
    const PreparationOptions& options={},const tpmshx_preparation_callbacks_v1* callbacks=nullptr) {
    auto output=detail::versioned<tpmshx_preparation_2d_continuous_case_v1>(TPMSHX_PREPARATION_CASE_ABI_VERSION);
    auto failure=detail::failure();char error[4096]{};
    detail::check(tpmshx_preparation_2d_continuous_prepare_case_v1(&input,&options,callbacks,&output,&failure,error,sizeof(error)),error);
    return PreparedContinuousCase2D(output);
}
inline ZonedInletFlow2D prepare_inlet_mass_capacities(const ZonedFlowInput2D& input,
    const PreparationOptions& options={},const tpmshx_preparation_callbacks_v1* callbacks=nullptr) {
    auto output=detail::versioned<tpmshx_preparation_2d_zoned_flow_v1>(TPMSHX_PREPARATION_CASE_ABI_VERSION);
    auto failure=detail::failure();char error[4096]{};
    detail::check(tpmshx_preparation_2d_zoned_capacities_v1(&input,&options,callbacks,&output,&failure,error,sizeof(error)),error);
    return ZonedInletFlow2D(output);
}
inline ZonedInletFlow2D resolve_inlet_flow(const ZonedFlowInput2D& input,
    const PreparationOptions& options={},const tpmshx_preparation_callbacks_v1* callbacks=nullptr) {
    auto output=detail::versioned<tpmshx_preparation_2d_zoned_flow_v1>(TPMSHX_PREPARATION_CASE_ABI_VERSION);
    auto failure=detail::failure();char error[4096]{};
    detail::check(tpmshx_preparation_2d_zoned_resolve_flow_v1(&input,&options,callbacks,&output,&failure,error,sizeof(error)),error);
    return ZonedInletFlow2D(output);
}
inline PreparedZonedFlowCase2D prepare_case(const ZonedFlowInput2D& input,
    const PreparationOptions& options={},const tpmshx_preparation_callbacks_v1* callbacks=nullptr) {
    auto output=detail::versioned<tpmshx_preparation_2d_zoned_case_v1>(TPMSHX_PREPARATION_CASE_ABI_VERSION);
    auto failure=detail::failure();char error[4096]{};
    detail::check(tpmshx_preparation_2d_zoned_prepare_case_v1(&input,&options,callbacks,&output,&failure,error,sizeof(error)),error);
    return PreparedZonedFlowCase2D(output);
}
inline SigmoidInletFlow2D prepare_inlet_mass_capacities(const SigmoidFlowInput2D& input,
    const PreparationOptions& options={},const tpmshx_preparation_callbacks_v1* callbacks=nullptr) {
    auto output=detail::versioned<tpmshx_preparation_2d_sigmoid_flow_v1>(TPMSHX_PREPARATION_CASE_ABI_VERSION);
    auto failure=detail::failure();char error[4096]{};
    detail::check(tpmshx_preparation_2d_sigmoid_capacities_v1(&input,&options,callbacks,&output,&failure,error,sizeof(error)),error);
    return SigmoidInletFlow2D(output);
}
inline SigmoidInletFlow2D resolve_inlet_flow(const SigmoidFlowInput2D& input,
    const PreparationOptions& options={},const tpmshx_preparation_callbacks_v1* callbacks=nullptr) {
    auto output=detail::versioned<tpmshx_preparation_2d_sigmoid_flow_v1>(TPMSHX_PREPARATION_CASE_ABI_VERSION);
    auto failure=detail::failure();char error[4096]{};
    detail::check(tpmshx_preparation_2d_sigmoid_resolve_flow_v1(&input,&options,callbacks,&output,&failure,error,sizeof(error)),error);
    return SigmoidInletFlow2D(output);
}
inline PreparedSigmoidFlowCase2D prepare_case(const SigmoidFlowInput2D& input,
    const PreparationOptions& options={},const tpmshx_preparation_callbacks_v1* callbacks=nullptr) {
    auto output=detail::versioned<tpmshx_preparation_2d_sigmoid_case_v1>(TPMSHX_PREPARATION_CASE_ABI_VERSION);
    auto failure=detail::failure();char error[4096]{};
    detail::check(tpmshx_preparation_2d_sigmoid_prepare_case_v1(&input,&options,callbacks,&output,&failure,error,sizeof(error)),error);
    return PreparedSigmoidFlowCase2D(output);
}
inline PreparedStripeCase2D prepare_stripe_case(const ZonedFlowInput2D& input,
    const PreparationOptions& options={},const tpmshx_preparation_callbacks_v1* callbacks=nullptr) {
    auto output=detail::versioned<tpmshx_preparation_2d_stripe_case_v1>(TPMSHX_PREPARATION_CASE_ABI_VERSION);
    auto failure=detail::failure();char error[4096]{};
    detail::check(tpmshx_preparation_2d_stripe_prepare_case_v1(&input,&options,callbacks,&output,&failure,error,sizeof(error)),error);
    return PreparedStripeCase2D(output);
}
inline ContinuousInletFlow3D prepare_inlet_mass_capacities(const ContinuousInput3D& input,
    const PreparationOptions& options={},const tpmshx_preparation_callbacks_v1* callbacks=nullptr) {
    auto output=detail::versioned<tpmshx_preparation_3d_continuous_flow_v1>(TPMSHX_PREPARATION_CASE_3D_ABI_VERSION);
    auto failure=detail::failure();char error[4096]{};
    detail::check(tpmshx_preparation_3d_continuous_capacities_v1(&input,&options,callbacks,&output,&failure,error,sizeof(error)),error);
    return ContinuousInletFlow3D(output);
}
inline ContinuousInletFlow3D resolve_inlet_flow(const ContinuousInput3D& input,
    const PreparationOptions& options={},const tpmshx_preparation_callbacks_v1* callbacks=nullptr) {
    auto output=detail::versioned<tpmshx_preparation_3d_continuous_flow_v1>(TPMSHX_PREPARATION_CASE_3D_ABI_VERSION);
    auto failure=detail::failure();char error[4096]{};
    detail::check(tpmshx_preparation_3d_continuous_resolve_flow_v1(&input,&options,callbacks,&output,&failure,error,sizeof(error)),error);
    return ContinuousInletFlow3D(output);
}
inline PreparedContinuousCase3D prepare_case(const ContinuousInput3D& input,
    const PreparationOptions& options={},const tpmshx_preparation_callbacks_v1* callbacks=nullptr) {
    auto output=detail::versioned<tpmshx_preparation_3d_continuous_case_v1>(TPMSHX_PREPARATION_CASE_3D_ABI_VERSION);
    auto failure=detail::failure();char error[4096]{};
    detail::check(tpmshx_preparation_3d_continuous_prepare_case_v1(&input,&options,callbacks,&output,&failure,error,sizeof(error)),error);
    return PreparedContinuousCase3D(output);
}
inline SpatialInletFlow3D prepare_inlet_mass_capacities(const SpatialInput3D& input,
    const PreparationOptions& options={},const tpmshx_preparation_callbacks_v1* callbacks=nullptr) {
    auto output=detail::versioned<tpmshx_preparation_3d_spatial_flow_v1>(TPMSHX_PREPARATION_CASE_3D_ABI_VERSION);
    auto failure=detail::failure();char error[4096]{};
    detail::check(tpmshx_preparation_3d_spatial_capacities_v1(&input,&options,callbacks,&output,&failure,error,sizeof(error)),error);
    return SpatialInletFlow3D(output);
}
inline SpatialInletFlow3D resolve_inlet_flow(const SpatialInput3D& input,
    const PreparationOptions& options={},const tpmshx_preparation_callbacks_v1* callbacks=nullptr) {
    auto output=detail::versioned<tpmshx_preparation_3d_spatial_flow_v1>(TPMSHX_PREPARATION_CASE_3D_ABI_VERSION);
    auto failure=detail::failure();char error[4096]{};
    detail::check(tpmshx_preparation_3d_spatial_resolve_flow_v1(&input,&options,callbacks,&output,&failure,error,sizeof(error)),error);
    return SpatialInletFlow3D(output);
}
inline PreparedSpatialCase3D prepare_case(const SpatialInput3D& input,
    const PreparationOptions& options={},const tpmshx_preparation_callbacks_v1* callbacks=nullptr) {
    auto output=detail::versioned<tpmshx_preparation_3d_spatial_case_v1>(TPMSHX_PREPARATION_CASE_3D_ABI_VERSION);
    auto failure=detail::failure();char error[4096]{};
    detail::check(tpmshx_preparation_3d_spatial_prepare_case_v1(&input,&options,callbacks,&output,&failure,error,sizeof(error)),error);
    return PreparedSpatialCase3D(output);
}
inline PreparedSpatialCase3D prepare_case(const CaseInput3D& input,const PreparationOptions& options={}) {
    SpatialInput3D spatial;spatial.input=input;return prepare_case(spatial,options);
}
// Build the saved descriptor for one prepared owner. Keep both unchanged until result transfer.
inline SavedCase2D saved_case(const PreparedUniformCase2D& prepared) {return SavedCase2D(prepared);}
inline SavedCase2D saved_case(const PreparedZonedFlowCase2D& prepared) {return SavedCase2D(prepared);}
inline SavedCase2D saved_case(const PreparedSigmoidFlowCase2D& prepared) {return SavedCase2D(prepared);}
inline SavedCase2D saved_case(const PreparedContinuousCase2D& prepared) {return SavedCase2D(prepared);}
inline SavedCase2D saved_case(const PreparedStripeCase2D& prepared) {return SavedCase2D(prepared);}
inline SavedPreparedCase3D saved_case(const PreparedSpatialCase3D& prepared) {return SavedPreparedCase3D(prepared);}
inline SavedPreparedCase3D saved_case(const PreparedContinuousCase3D& prepared) {return SavedPreparedCase3D(prepared);}
inline SavedCase2D saved_case(const PreparedUniformCase2D&&)=delete;
inline SavedCase2D saved_case(const PreparedZonedFlowCase2D&&)=delete;
inline SavedCase2D saved_case(const PreparedSigmoidFlowCase2D&&)=delete;
inline SavedCase2D saved_case(const PreparedContinuousCase2D&&)=delete;
inline SavedCase2D saved_case(const PreparedStripeCase2D&&)=delete;
inline SavedPreparedCase3D saved_case(const PreparedSpatialCase3D&&)=delete;
inline SavedPreparedCase3D saved_case(const PreparedContinuousCase3D&&)=delete;
template<class Source> void saved_case(const Source&&)=delete;
// Each result owns its copied storage. The prepared owner can be released afterwards.
inline RunResult2D run_case(const tpmshx_stage_saved_case_2d_v5& saved,const RunControl& control,
    const RunRequest2D& request={}) {
    auto output=detail::versioned<tpmshx_stage_run_result_2d_v1>(TPMSHX_STAGE_RUN_ABI_VERSION);char error[4096]{};
    detail::check(tpmshx_run_saved_case_2d_v5(&saved,&request,&control,&output,error,sizeof(error)),error);
    return RunResult2D(output);
}
inline RunResult2D run_case(const PreparedUniformCase2D& prepared,const RunControl& control,const RunRequest2D& request={}) {
    return run_case(saved_case(prepared),control,request);
}
inline RunResult2D run_case(const PreparedZonedFlowCase2D& prepared,const RunControl& control,const RunRequest2D& request={}) {
    return run_case(saved_case(prepared),control,request);
}
inline RunResult2D run_case(const PreparedSigmoidFlowCase2D& prepared,const RunControl& control,const RunRequest2D& request={}) {
    return run_case(saved_case(prepared),control,request);
}
inline RunResult2D run_case(const PreparedContinuousCase2D& prepared,const RunControl& control,const RunRequest2D& request={}) {
    return run_case(saved_case(prepared),control,request);
}
inline RunResult2D run_case(const PreparedStripeCase2D& prepared,const RunControl& control,const RunRequest2D& request={}) {
    return run_case(saved_case(prepared),control,request);
}
inline RunResult3D run_case(const tpmshx_stage_saved_case_3d_v3& saved,const RunControl3D& control,
    const RunRequest3D& request={}) {
    auto output=detail::versioned<tpmshx_stage_run_result_3d_v1>(TPMSHX_STAGE_RUN_3D_ABI_VERSION);char error[4096]{};
    detail::check(tpmshx_run_saved_case_3d_v3(&saved,&request,&control,&output,error,sizeof(error)),error);
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
