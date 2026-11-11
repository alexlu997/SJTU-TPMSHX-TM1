#pragma once

#include "tpmshx/geometry.hpp"
#include "tpmshx/preparation_df.hpp"
#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace tpmshx::preparation {

struct PortInput2D {
    std::int32_t direction=0;
    double inlet_center_m=0.,inlet_width_m=0.,outlet_center_m=0.,outlet_width_m=0.;
    bool uniform_inlet=false;
};
struct InletInput2D {
    Fluid fluid=Fluid::air;
    double velocity_m_s,temperature_K,pressure_Pa;
    PortInput2D port;
    std::optional<double> mass_flow_kg_s;
};
struct GridInput2D {
    double length_m,height_m;
    std::size_t requested_nx,requested_ny;
    bool port_wall_refine=false;
};
struct UniformGeometryInput {
    Topology topology;
    double cell_length_mm,wall_thickness_mm,solid_conductivity_W_mK;
    double delta_levelset=0.;
};
struct CaseInput2D {
    GridInput2D grid;
    UniformGeometryInput geometry;
    std::array<InletInput2D,2> sides;
    std::optional<double> physical_depth_m;
    // Only the current uniform and CFD-smooth selections are implemented here.
    std::uint32_t geometry_mode=0,df_mode=0;
};
struct PreparationOptions {
    std::optional<double> chi_override;
    bool allow_extrapolation=false;
};

struct PhysicalGrid2D {
    std::size_t nx=0,ny=0;
    std::vector<double> dx,dy,x_edges,y_edges,x_breaks,y_breaks;
};
struct UniformInletProperties {
    double rho,mu,k_f,cp,pr,re,nu;
    double permeability_m2,forchheimer_per_m,pressure_gradient_Pa_m;
    double surface_transfer_W_m2K,fluid_conductivity_W_mK,solid_conductivity_W_mK;
};
struct PreparationDragEvidence {
    DfSummary base_permeability,base_forchheimer,applied_permeability,applied_forchheimer;
    double scale_permeability=1.,scale_forchheimer=1.;
    std::string campaign,scope;
};
struct PreparedSide2D {
    InletInput2D inlet;
    UniformInletProperties properties;
    double seed_permeability_m2=0.,seed_forchheimer_per_m=0.;
    std::vector<double> cross_widths,stream_widths,row_permeability,row_forchheimer;
    std::vector<double> permeability,forchheimer;
    std::vector<double> inlet_geometry,outlet_geometry,inlet_profile,outlet_profile,outlet_u_fraction;
    std::array<double,2> inlet_bounds{},outlet_bounds{};
    PreparationDragEvidence drag_evidence;
};
struct PreparationRangeSample {
    bool have_finite=false;
    double minimum=0.,maximum=0.;
    std::size_t minimum_index=0,maximum_index=0,low=0,high=0,size=0,nonfinite=0;
};
struct PreparationRange {
    std::vector<std::string> source;
    std::string side,stage,layout,label,quantity,unit;
    std::array<double,2> bounds;
    std::vector<std::size_t> shape;
    PreparationRangeSample sample,last;
};
enum class PreparationEventKind : std::uint32_t {log=0,warning=1,floating_point=2};
struct PreparationEvent {
    PreparationEventKind kind;
    std::string logger,message;
    std::uint32_t floating_event=0;
};
struct PreparationCallbacks {
    // The event is borrowed until this call returns. The callback may throw.
    void (*event)(void*,const PreparationEvent&)=nullptr;
    void* context=nullptr;
};
struct PreparationModelRef {
    std::string name,version,side;
};
struct PreparationEvidence {
    std::array<PreparationModelRef,4> models;
    std::vector<PreparationRange> ranges;
    std::vector<std::string> warnings;
    std::vector<PreparationEvent> events;
};
struct PreparedCase2D {
    CaseInput2D input;
    PreparationOptions options;
    PhysicalGrid2D grid;
    geometry::MaterialGeometry uniform_geometry;
    double hydraulic_radius_m=0.,cell_length_m=0.,wall_thickness_m=0.,split_a=.5;
    std::vector<double> cell_length,wall_thickness,total_porosity,solid_conductivity,hydraulic_radius;
    std::array<PreparedSide2D,2> sides;
    PreparationEvidence evidence;
};

// No input or callback storage is retained. All returned arrays are owned.
// Physical cell fields use C order (x,y). Flow fields use (cross,stream).
// This entry supports uniform symmetric air/air and prescribed velocity.
PreparedCase2D prepare_case_2d(const CaseInput2D&,const PreparationOptions& = {},
                              const PreparationCallbacks& = {});

}  // namespace tpmshx::preparation
