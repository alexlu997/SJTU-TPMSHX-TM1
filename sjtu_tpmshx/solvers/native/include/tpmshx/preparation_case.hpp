#pragma once

#include "tpmshx/geometry.hpp"
#include "tpmshx/grid.hpp"
#include "tpmshx/preparation_df.hpp"
#include "tpmshx/property_c_api.h"
#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

namespace tpmshx::preparation {

// These tags have the same meaning as the existing property input tags.
struct ScalarKind {
    std::uint32_t precision=64,strong=0,layout=0;
};
struct InletScalarKinds {
    ScalarKind velocity,temperature,pressure;
};
struct CaseScalarKinds {
    ScalarKind cell_length,wall_thickness,solid_conductivity;
    std::array<InletScalarKinds,2> sides;
};
struct Sco2NuSelection {
    std::uint32_t mode=0;
    std::array<std::optional<double>,2> alpha;
    std::string parameter_version,source,applicability;
};

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
struct ContinuousControls2D {
    std::size_t nx=0,ny=0;
    std::uint32_t order=3;
    bool symmetric_y=true;
    std::array<double,2> cell_bounds_mm{},wall_bounds_mm{};
    std::vector<double> decision_mm;
};
struct CaseInput2D {
    GridInput2D grid;
    UniformGeometryInput geometry;
    std::array<InletInput2D,2> sides;
    std::optional<double> physical_depth_m;
    // Geometry mode 1 requires continuous controls. DF 0/1 selects CFD/experiments.
    std::uint32_t geometry_mode=0,df_mode=0;
    Sco2NuSelection sco2_nu;
    CaseScalarKinds kinds;
    std::optional<ContinuousControls2D> continuous;
};
struct PreparationOptions {
    std::optional<double> chi_override;
    bool allow_extrapolation=false;
};
// Keep each C interface's scope checks in the shared validation order.
enum class CaseScope { air_cfd_v1, uniform_fluids_v2, uniform_mass_v3, continuous_v4 };

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
    std::optional<DfSelection> selection;
    std::string application_scope,fluid;
    std::string transfer_policy,geometry_application;
    std::optional<std::array<double,2>> reference_geometry_mm;
    std::vector<std::array<std::string,2>> calibration;
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
    std::array<ScalarKind,13> property_kinds;
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
    bool bounds_list=false;
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
    std::vector<std::string> notices;
    std::string sco2_nu_model_version;
    std::array<std::array<double,3>,2> sco2_nu_coefficients{};
    bool co2_geometry=false;
    std::string co2_version,co2_application_version;
    double co2_pressure_multiplier=1.,co2_nu_multiplier=1.;
    DfPair co2_drag_factors{1.,1.};
    std::array<double,2> co2_re_range{},co2_pr_range{};
};
struct PreparedCase2D {
    CaseInput2D input;
    PreparationOptions options;
    PhysicalGrid2D grid;
    geometry::MaterialGeometry uniform_geometry;
    double hydraulic_radius_m=0.,cell_length_m=0.,wall_thickness_m=0.,split_a=.5;
    std::vector<double> cell_length,wall_thickness,total_porosity,solid_conductivity,hydraulic_radius;
    std::array<PreparedSide2D,2> sides;
    std::vector<double> area_density,hydraulic_diameter;
    std::array<std::vector<double>,2> fluid_conductivity;
    PreparationEvidence evidence;
    std::array<ScalarKind,5> field_kinds;
};

struct InletFlowRequest2D {
    CaseInput2D input;
    ScalarKind physical_depth_kind;
    std::array<ScalarKind,2> target_kinds;
    // Explicit batch targets replace both stored targets in the resolved input.
    std::optional<std::array<double,2>> explicit_targets;
};
struct InletFlow2D {
    CaseInput2D input;
    bool have_capacities=false;
    std::array<grid::Scalar,2> capacities{},speeds{};
    PreparationEvidence evidence;
};
struct PreparedFlowCase2D {
    PreparedCase2D prepared;
    InletFlow2D flow;
};

struct PreparationFailureCause {std::uint32_t kind;std::string message;};
class PreparationError : public std::runtime_error {
public:
    PreparationError(int status,std::string message,std::uint32_t kind=1,
                     std::uint32_t side=2,std::vector<PreparationFailureCause> causes={});
    int status;
    std::uint32_t kind,side;
    std::vector<PreparationFailureCause> causes;
    tpmshx_property_failure_v1 property{};
    bool have_property=false;
};

// No input or callback storage is retained. All returned arrays are owned.
// Physical cell fields use C order (x,y). Flow fields use (cross,stream).
// This entry supports uniform symmetric fluids at prescribed velocity.
PreparedCase2D prepare_case_2d(const CaseInput2D&,const PreparationOptions& = {},
                              const PreparationCallbacks& = {},
                              CaseScope = CaseScope::uniform_fluids_v2);

// These queries do not evaluate Nu or create a complete prepared case.
InletFlow2D prepare_inlet_mass_capacities_2d(const CaseInput2D&,ScalarKind physical_depth_kind={},
    const PreparationOptions& = {},const PreparationCallbacks& = {});
InletFlow2D resolve_inlet_flow_2d(const InletFlowRequest2D&,
    const PreparationOptions& = {},const PreparationCallbacks& = {});
// Preliminary flow evidence stays separate from final preparation evidence.
PreparedFlowCase2D prepare_flow_case_2d(const InletFlowRequest2D&,
    const PreparationOptions& = {},const PreparationCallbacks& = {});

}  // namespace tpmshx::preparation
