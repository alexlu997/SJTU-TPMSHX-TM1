#include "tpmshx/preparation_case.hpp"
#include "tpmshx/preparation_flow.hpp"
#include "tpmshx/asym_geometry.hpp"
#include "tpmshx/grid.hpp"
#include "tpmshx/zones.hpp"
#include "tpmshx/model_coefficients.hpp"
#include "tpmshx/preparation_df.hpp"
#include "tpmshx/preparation_df_data.hpp"
#include "preparation_df_fields.hpp"
#include "preparation_properties.hpp"
#include "preparation_nu.hpp"
#include "../geometry/field_continuous.hpp"
#include "../geometry/field_lut.hpp"
#include "../geometry/field_sigmoid.hpp"
#include "../numerics/contiguous_sum.hpp"
#include "../numerics/scalar_range_samples.hpp"

#include <algorithm>
#include <cfenv>
#include <cmath>
#include <iomanip>
#include <limits>
#include <locale>
#include <list>
#include <sstream>
#include <stdexcept>
#include <string_view>
#include <utility>

namespace tpmshx::preparation {
PreparationError::PreparationError(int status,std::string message,std::uint32_t kind,
    std::uint32_t side,std::vector<PreparationFailureCause> causes)
    :std::runtime_error(std::move(message)),status(status),kind(kind),side(side),causes(std::move(causes)) {}

namespace {
namespace g=grid;
namespace data=model_coefficients;
constexpr const char* logger="tpmshx.preprocess.two_d.preparation";

class FloatingEnvironment {
public:
    FloatingEnvironment() {std::fegetenv(&saved_);}
    ~FloatingEnvironment() {std::fesetenv(&saved_);}
private:
    std::fenv_t saved_;
};

std::string fixed(double value,int precision) {
    std::ostringstream stream;stream.imbue(std::locale::classic());
    stream<<std::fixed<<std::setprecision(precision)<<value;
    return stream.str();
}
const char* topology_name(Topology topology) {
    if (topology==Topology::diamond) return "Diamond";
    if (topology==Topology::gyroid) return "Gyroid";
    throw std::invalid_argument("TPMS geometry supports Diamond and Gyroid only");
}
const char* fluid_name(Fluid fluid) {
    switch (fluid) {
    case Fluid::air:return "air";
    case Fluid::water:return "water";
    case Fluid::sco2:return "sco2";
    case Fluid::co2:return "co2";
    }
    throw std::invalid_argument("native 2D preparation fluid must be air, water, sco2 or co2");
}
template<class Input> bool co2_geometry(const Input& input) {
    return input.sides[0].fluid==Fluid::co2 || input.sides[1].fluid==Fluid::co2;
}
template<class Input,class Inlet>
std::pair<DfSelection,DfPair> experiment_selection(const Input& input,const Inlet& inlet,
                                                 std::size_t side,bool continuous=false) {
    const auto topology=static_cast<std::uint32_t>(input.geometry.topology);
    const auto fluid=static_cast<std::uint32_t>(inlet.fluid);
    const auto cell=input.geometry.cell_length_mm,wall=input.geometry.wall_thickness_mm,speed=inlet.velocity_m_s;
    try {
        return df_experiment_side(topology,fluid,cell,wall,speed,continuous);
    } catch (const DfExperimentError& error) {
        std::vector<PreparationFailureCause> causes{{1,error.what()}};
        if (error.velocity_window) causes.push_back({1,"HX velocity outside application window"});
        throw PreparationError(1,"experimental calibration unavailable for active side "+
            std::string(side?"B":"A")+": "+error.what(),1,static_cast<std::uint32_t>(side),std::move(causes));
    }
}
template<class Input,class Inlet>
void validate_experiment_scope(const Input& input,const std::array<Inlet,2>& sides,
    std::uint32_t geometry_mode, ArrayView<const double> domain) {
    const auto& g=input.geometry;
    const auto scope=df_experiment_scope(static_cast<std::uint32_t>(g.topology),
        static_cast<std::uint32_t>(sides[0].fluid),static_cast<std::uint32_t>(sides[1].fluid),
        geometry_mode,g.delta_levelset==0.,g.cell_length_mm,g.wall_thickness_mm,domain);
    if (!(scope & TPMSHX_DF_EXPERIMENT_LAYOUT))
        throw std::invalid_argument(experimental_layout_error);
    for (std::size_t side=0;side<2;++side) if (sides[side].fluid!=Fluid::co2) {
        const auto selected=experiment_selection(input,sides[side],side,scope & TPMSHX_DF_HX_TRANSFER).first;
        if (selected.scope && !(scope & TPMSHX_DF_HX_DOMAIN))
            throw PreparationError(1,experimental_domain_error(side),1,static_cast<std::uint32_t>(side));
    }
}
std::size_t count(std::size_t nx,std::size_t ny) {
    if (ny && nx>std::numeric_limits<std::size_t>::max()/ny)
        throw std::invalid_argument("prepared 2D cell count overflows size_t");
    return nx*ny;
}
void positive(double value,const std::string& field) {
    if (!std::isfinite(value) || value<=0.)
        throw std::invalid_argument("ComputeConfig."+field+"="+decimal(value)+" — must be finite and > 0");
}

std::size_t first_cross_axis(int direction) {
    return direction == 0 || direction == 1 ? 1u : 0u;
}

struct FullFace { double center, width; };

std::optional<FullFace> full_face(double inlet_width, double outlet_width, double cross,
                                  const std::string& prefix) {
    if ((inlet_width <= 0.) != (outlet_width <= 0.))
        throw std::invalid_argument(prefix+".in_w and out_w must both be positive, or both be <= 0 for a full-face port");
    if (!std::isfinite(inlet_width) || !std::isfinite(outlet_width))
        throw std::invalid_argument("port width must be finite before full-face normalization");
    if (inlet_width > 0.) return std::nullopt;
    return FullFace{cross / 2., cross};
}

PortInput2D checked_port(PortInput2D port,const GridInput2D& grid,const std::string& side) {
    const auto prefix="ComputeConfig.bc_"+side;
    const auto axis=first_cross_axis(port.direction);
    const double cross=axis?grid.height_m:grid.length_m;
    if (const auto face=full_face(port.inlet_width_m,port.outlet_width_m,cross,prefix)) {
        port.inlet_center_m=port.outlet_center_m=face->center;
        port.inlet_width_m=port.outlet_width_m=face->width;
    }
    if (port.direction<0 || port.direction>5)
        throw std::invalid_argument(prefix+" is invalid: [error] pipe_bad_dir: pipe direction "+
                                    std::to_string(port.direction)+" not in 0..5");
    if (port.direction>3)
        throw std::invalid_argument(prefix+" is invalid: [error] pipe_bad_dir: 2D pipe direction "+
                                    std::to_string(port.direction)+" must be in 0..3");
    std::string errors;
    for (std::size_t end=0;end<2;++end) {
        const std::string name=end?"out":"in";
        const double center=end?port.outlet_center_m:port.inlet_center_m;
        const double width=end?port.outlet_width_m:port.inlet_width_m;
        std::string error;
        if (!std::isfinite(center) || !std::isfinite(width))
            error="[error] pipe_"+name+"_invalid: "+name+" centre and width must be finite numbers";
        else if (!g::port_window_within(cross,center,width))
            error="[error] pipe_"+name+"_out_of_domain: "+name+"_ctr ± "+name+"_w/2 = ["+
                  significant(center-width/2.,3)+", "+significant(center+width/2.,3)+
                  "] m leaves the cross-axis range [0, "+significant(cross,3)+"].";
        if (!error.empty()) {if (!errors.empty()) errors+="; ";errors+=error;}
    }
    if (!errors.empty()) throw std::invalid_argument(prefix+" is invalid: "+errors);
    return port;
}

template<class Controls> void validate_controls(const Controls& controls,std::size_t nz=1) {
    if (controls.order<1 || controls.order>3)
        throw std::invalid_argument("Continuous field spline_order must be 1..3");
    if (!controls.nx || !controls.ny || !nz)
        throw std::invalid_argument("Continuous field needs >=1 controls per axis");
    for (double value:controls.decision_mm) if (!std::isfinite(value))
        throw std::invalid_argument("Continuous field x_decision must be a list of finite numbers");
    const std::array<std::array<double,2>,2> bounds{controls.cell_bounds_mm,controls.wall_bounds_mm};
    for (std::size_t i=0;i<2;++i) for (double value:bounds[i]) if (!std::isfinite(value))
        throw std::invalid_argument(std::string("Continuous field ")+(i?"t_bounds":"L_bounds")+
            " must be a list of finite numbers");
    for (std::size_t i=0;i<2;++i) {
        const auto& values=bounds[i];
        const double lower=i?df_data::df_t_nodes.front():df_data::df_L_nodes.front();
        const double upper=i?df_data::df_t_nodes.back():df_data::df_L_nodes.back();
        if (!(lower<=values[0] && values[0]<=values[1] && values[1]<=upper))
            throw std::invalid_argument(std::string("Continuous field ")+(i?"t_bounds":"L_bounds")+
                " must be ordered within ("+decimal(lower)+", "+decimal(upper)+") mm");
    }
    const auto columns=controls.symmetric_y?controls.ny/2+controls.ny%2:controls.ny;
    const auto half=count(count(controls.nx,columns),nz),expected=count(half,2);
    if (controls.decision_mm.size()!=expected)
        throw std::invalid_argument("Continuous field x_decision must contain "+std::to_string(expected)+" values");
    for (std::size_t i=0;i<expected;++i) {
        const auto& limits=bounds[i/half];const auto value=controls.decision_mm[i];
        if (!(limits[0]<=value && value<=limits[1]))
            throw std::invalid_argument("Continuous field control values must lie within their L/t bounds");
    }
}
CaseScope flow_scope(const CaseInput2D& input) {
    return input.continuous?CaseScope::continuous_v4:input.offset_scope?CaseScope::offset_v10:CaseScope::uniform_mass_v3;
}
template<class Input> void check_cfd_geometry(const Input& input) {
    const double cell=input.geometry.cell_length_mm,wall=input.geometry.wall_thickness_mm;
    if (cell<df_data::df_L_nodes.front() || df_data::df_L_nodes.back()<cell
        || wall<df_data::df_t_nodes.front() || df_data::df_t_nodes.back()<wall)
        throw std::invalid_argument(std::string("V2 geometry must lie inside the CFD grid: ")+df_data::case_geometry_limits);
}
template<class Inlet> void check_sco2_inlet(const Inlet& inlet,std::size_t side) {
    const std::string prefix=std::string("sCO2 fluid ")+(side?"B":"A");
    if (!(data::sco2_temperature_range[0]<=inlet.temperature_K && inlet.temperature_K<=data::sco2_temperature_range[1]))
        throw PreparationError(1,prefix+" temperature must be "+data::sco2_temperature_limits,1,static_cast<std::uint32_t>(side));
    if (!(data::sco2_pressure_range[0]<=inlet.pressure_Pa && inlet.pressure_Pa<=data::sco2_pressure_range[1]))
        throw PreparationError(1,prefix+" pressure must be "+data::sco2_pressure_limits,1,static_cast<std::uint32_t>(side));
}
void check_sco2_geometry(bool discrete,double offset) {
    if (discrete && data::sco2_reject_discrete_zones) throw std::invalid_argument("sCO2 V2 does not support discrete zones");
    if (offset!=0. && data::sco2_reject_levelset_offset) throw std::invalid_argument("sCO2 V2 requires delta_levelset=0");
}
void check_co2_geometry(bool discrete,double offset) {
    if (discrete && data::co2_reject_discrete_zones) throw std::invalid_argument("CO2 does not support discrete zones");
    if (offset!=0. && data::co2_reject_levelset_offset) throw std::invalid_argument("CO2 requires symmetric delta_levelset=0 geometry");
}
std::array<InletInput2D,2> validate(const CaseInput2D& input,CaseScope scope,bool static_only=false) {
    const bool continuous=scope==CaseScope::continuous_v4;
    const bool mass=continuous || scope==CaseScope::uniform_mass_v3 || scope==CaseScope::offset_v10;
    if (continuous) {
        if (input.geometry_mode!=1 || !input.continuous)
            throw std::invalid_argument("native continuous preparation requires canonical XY controls and geometry_mode=1");
        validate_controls(*input.continuous);
    } else if (input.geometry_mode!=0 || input.continuous)
        throw std::invalid_argument("native 2D preparation currently requires uniform geometry");
    if (scope==CaseScope::air_cfd_v1) {
        if (input.df_mode) throw std::invalid_argument("native 2D preparation currently requires df_mode='cfd_smooth'");
    } else {
        validate_nu(input.sco2_nu);
        if (continuous && input.geometry.delta_levelset!=0.)
            throw std::invalid_argument("Continuous spatial fields require delta_levelset=0");
        if (input.df_mode>1) throw std::invalid_argument("native 2D preparation DF mode must be CFD or experimental");
    }
    if (mass) for (std::size_t i=0;i<2;++i) {
        const auto target=input.sides[i].mass_flow_kg_s;
        if (target) {
            positive(*target,std::string("fluid_")+(i?"B":"A")+".mass_flow_kg_s");
            if (!input.physical_depth_m)
                throw std::invalid_argument("Total mass flow requires an explicit positive geometry.Lz_m");
        }
    }
    const auto& geometry=input.geometry;
    positive(input.grid.length_m,"geometry.L_dom_m");
    positive(input.grid.height_m,"geometry.H_dom_m");
    positive(geometry.cell_length_mm,"geometry.L_cell_mm");
    positive(geometry.wall_thickness_mm,"geometry.t_wall_mm");
    positive(geometry.solid_conductivity_W_mK,"geometry.k_s_W_mK");
    if (input.physical_depth_m) positive(*input.physical_depth_m,"geometry.Lz_m");
    auto sides=input.sides;
    for (std::size_t side=0;side<2;++side) {
        const auto name=std::string(side?"B":"A");
        if (sides[side].mass_flow_kg_s && !mass)
            throw std::invalid_argument("native 2D preparation currently requires prescribed inlet velocity");
        positive(sides[side].temperature_K,"fluid_"+name+".T_in_K");
        positive(sides[side].pressure_Pa,"fluid_"+name+".P_in_Pa");
    }
    for (std::size_t axis=0;axis<2;++axis) {
        const auto n=axis?input.grid.requested_ny:input.grid.requested_nx;
        if (!n) throw std::invalid_argument(std::string("ComputeConfig.solver.N")+(axis?'y':'x')+"=0 — must be >= 1");
    }
    for (std::size_t side=0;side<2;++side)
        sides[side].port=checked_port(sides[side].port,input.grid,side?"B":"A");
    check_cfd_geometry(input);
    if (scope!=CaseScope::air_cfd_v1) {
        for (std::size_t side=0;side<2;++side) if (sides[side].fluid==Fluid::sco2) {
            check_sco2_inlet(sides[side],side);
            check_sco2_geometry(false,geometry.delta_levelset);
        }
        if (co2_geometry(input)) check_co2_geometry(false,geometry.delta_levelset);
    }
    if (!static_only) for (std::size_t side=0;side<2;++side)
        positive(sides[side].velocity_m_s,std::string("fluid_")+(side?"B":"A")+".u_mps");
    if (scope==CaseScope::air_cfd_v1) for (const auto& side:sides) if (side.fluid!=Fluid::air)
        throw std::invalid_argument("native 2D preparation currently supports air/air only");
    for (const auto& side:sides) fluid_name(side.fluid);
    if (!static_only && input.df_mode) {
        const double domain[]{input.grid.length_m,input.grid.height_m};
        validate_experiment_scope(input,sides,input.geometry_mode,{domain,2});
    }
    for (std::size_t side=0;side<2;++side) if (sides[side].fluid==Fluid::water) {
        const auto& inlet=sides[side];
        try {validate_water_pt({&inlet.temperature_K,1},{&inlet.pressure_Pa,1});}
        catch (const PropertyError& error) {
            const auto& value=error.failure;
            PreparationError failure(error.status,"pipeline inlet "+std::string(side?"B":"A")+
                ": water index=(), T="+significant(inlet.temperature_K,6)+" K, P_abs="+
                significant(inlet.pressure_Pa,6)+" Pa: "+error.what(),2,static_cast<std::uint32_t>(side),
                value.reason==1?std::vector<PreparationFailureCause>{}:
                    std::vector<PreparationFailureCause>{{value.reason==6?2u:1u,error.what()}});
            failure.have_property=true;failure.property={value.reason,value.input,value.index,value.first_t_index,
                value.first_p_index,value.temperature,value.pressure,value.detail,value.fp};
            throw failure;
        }
    }
    for (std::size_t axis=0;axis<2;++axis) {
        const double length=axis?input.grid.height_m:input.grid.length_m;
        if (length>10.) throw std::invalid_argument(std::string("Domain dimension '")+(axis?'H':'L')+"'="+
            decimal(length)+" m exceeds 10.0 m. Likely unit slip — GUI expects meters here, while L_cell and t use millimeters. Re-check input.");
    }
    topology_name(geometry.topology);
    if (geometry.delta_levelset!=0. && !static_only && scope!=CaseScope::offset_v10)
        throw std::invalid_argument("native 2D preparation currently requires symmetric delta_levelset=0 geometry");
    return sides;
}

g::Port native_port(const PortInput2D& input) {
    return {input.direction,true,{{{input.inlet_center_m,input.inlet_width_m,{},{}},
        {input.outlet_center_m,input.outlet_width_m,{},{}}}}};
}
g::Values unique(g::Values values) {
    std::stable_sort(values.begin(),values.end());
    values.erase(std::unique(values.begin(),values.end()),values.end());
    return values;
}
g::Values bounds(double length,const g::Values& points) {
    const auto keep=g::aligned_filter(length,points);
    g::Values output{0.,length};
    for (std::size_t i=0;i<points.size();++i) if (keep[i]) output.push_back(points[i]);
    return unique(std::move(output));
}
PhysicalGrid2D physical_grid(const GridInput2D& input,const std::array<InletInput2D,2>& sides,bool zoned=false) {
    const g::Values lengths{input.length_m,input.height_m};
    const std::vector<g::Port> ports{native_port(sides[0].port),native_port(sides[1].port)};
    const std::array<g::Values,2> breaks{unique(g::breaks_2d(lengths,ports,0)),unique(g::breaks_2d(lengths,ports,1))};
    PhysicalGrid2D output;
    output.x_breaks=breaks[0];output.y_breaks=breaks[1];
    std::array<std::vector<double>,2> widths;
    if (input.port_wall_refine) {
        for (std::size_t axis=0;axis<2;++axis) {
            const auto knots=unique(g::port_edges(lengths,ports,axis));
            g::Values outer{0.};outer.insert(outer.end(),knots.begin(),knots.end());outer.push_back(lengths[axis]);
            std::size_t minimum=0;
            widths[axis]=g::port_wall_axis(2,axis?input.requested_ny:input.requested_nx,outer,
                                          bounds(lengths[axis],knots),minimum,axis);
        }
    } else {
        bool refined=false;
        if (!zoned && breaks[0].empty() && breaks[1].empty()) {
            try {
                widths[0]=g::wall(lengths[0],input.requested_nx,8,.02e-3,1.8);
                widths[1]=g::wall(lengths[1],input.requested_ny,8,.02e-3,1.8);
                refined=true;
            } catch (const std::invalid_argument&) {
                // Keep the existing short-domain selection of the aligned grid.
            }
        }
        if (!refined) for (std::size_t axis=0;axis<2;++axis)
            widths[axis]=g::aligned(axis?input.requested_ny:input.requested_nx,
                                    bounds(lengths[axis],breaks[axis])).widths;
    }
    output.dx=std::move(widths[0]);output.dy=std::move(widths[1]);
    output.nx=output.dx.size();output.ny=output.dy.size();
    count(output.nx,output.ny);
    output.x_edges=g::cumulative_widths({output.dx.data(),output.dx.size()});
    output.y_edges=g::cumulative_widths({output.dy.data(),output.dy.size()});
    return output;
}

const geometry::PhiIndex& geometry_index(Topology topology) {
    if (topology==Topology::diamond) {
        static const auto index=geometry::PhiIndex::from_topology(Topology::diamond,128);return index;
    }
    static const auto index=geometry::PhiIndex::from_topology(Topology::gyroid,128);return index;
}

struct Records {
    PreparationEvidence& output;
    const PreparationCallbacks& callbacks;
    std::vector<std::pair<bool,std::size_t>> warning_order;
    std::vector<std::string> plain_warnings;

    void observe(const PreparationRange& range,bool cached,std::optional<double> scalar={}) {
        if (callbacks.observe_range) callbacks.observe_range(callbacks.context,range,cached,scalar);
    }
    void merge(const PreparationEvidence& evidence,const std::string& side={},const std::string& layout="scalar") {
        for (const auto& range:evidence.ranges) {
            const auto bound_side=side.empty()?range.side:side;
            const auto bound_stage=side.empty()?range.stage:"inlet";
            const auto bound_layout=side.empty()?range.layout:layout;
            collect(range.source,bound_side,bound_stage,bound_layout,range.label,range.quantity.c_str(),
                range.unit.c_str(),range.bounds,range.shape,range.sample,range.bounds_list,{},false);
            for (auto& saved:output.ranges) if (saved.source==range.source && saved.shape==range.shape
                    && saved.side==bound_side && saved.stage==bound_stage && saved.layout==bound_layout) {
                saved.last=range.last;observe(saved,true);break;
            }
        }
        for (const auto& message:evidence.warnings) warning(message);
        output.events.insert(output.events.end(),evidence.events.begin(),evidence.events.end());
    }
    void emit(PreparationEvent event) {
        output.events.push_back(std::move(event));
        if (callbacks.event) callbacks.event(callbacks.context,output.events.back());
    }
    void floating(const std::array<std::uint32_t,property_event_count>& events,const char* source="") {
        for (auto encoded:events) if (encoded)
            emit({PreparationEventKind::floating_point,"",source,encoded});
    }
    void warning(std::string message) {
        if (std::find(plain_warnings.begin(),plain_warnings.end(),message)!=plain_warnings.end()) return;
        warning_order.emplace_back(false,plain_warnings.size());plain_warnings.push_back(std::move(message));
    }
    void range(std::vector<std::string> source,const std::string& side,const std::string& stage,
               const std::string& layout,std::string label,const char* quantity,const char* unit,
               const std::array<double,2>& limits,double value,std::vector<std::size_t> shape={},bool bounds_list=false,
               std::optional<double> notice_scalar={}) {
        PreparationRangeSample sample;
        sample.size=1;for (const auto extent:shape) sample.size=count(sample.size,extent);
        sample.have_finite=std::isfinite(value);
        if (sample.have_finite) {
            sample.minimum=sample.maximum=value;
            sample.low=value<limits[0]?sample.size:0;sample.high=value>limits[1]?sample.size:0;
        } else sample.nonfinite=sample.size;
        collect(std::move(source),side,stage,layout,std::move(label),quantity,unit,limits,
                std::move(shape),sample,bounds_list,notice_scalar.value_or(value));
    }
    void range(std::vector<std::string> source,const std::string& side,const std::string& stage,
               const std::string& layout,std::string label,const char* quantity,const char* unit,
               const std::array<double,2>& limits,const std::vector<double>& values,
               std::vector<std::size_t> shape) {
        const auto sample=detail::collect_range<PreparationRangeSample>(values.size(),
            [&](std::size_t index) {return values[index];},limits[0],limits[1]);
        collect(std::move(source),side,stage,layout,std::move(label),quantity,unit,limits,
                std::move(shape),sample,false);
    }
    void collect(std::vector<std::string> source,const std::string& side,const std::string& stage,
                 const std::string& layout,std::string label,const char* quantity,const char* unit,
                 const std::array<double,2>& limits,std::vector<std::size_t> shape,
                 PreparationRangeSample sample,bool bounds_list,std::optional<double> scalar={},bool notify=true) {
        for (auto& previous:output.ranges) if (previous.source==source && previous.side==side
                && previous.stage==stage && previous.layout==layout && previous.shape==shape) {
            auto aggregate=previous.sample;
            if (sample.low+sample.high>aggregate.low+aggregate.high) {
                aggregate.low=sample.low;aggregate.high=sample.high;aggregate.size=sample.size;
            }
            if (sample.have_finite) {
                if (!aggregate.have_finite || sample.minimum<aggregate.minimum) {
                    aggregate.minimum=sample.minimum;aggregate.minimum_index=sample.minimum_index;
                }
                if (!aggregate.have_finite || sample.maximum>aggregate.maximum) {
                    aggregate.maximum=sample.maximum;aggregate.maximum_index=sample.maximum_index;
                }
                aggregate.have_finite=true;
            }
            aggregate.nonfinite=std::max(aggregate.nonfinite,sample.nonfinite);
            previous.sample=aggregate;previous.last=sample;
            if (notify) observe(previous,false,scalar);
            return;
        }
        warning_order.emplace_back(true,output.ranges.size());
        output.ranges.push_back({std::move(source),side,stage,layout,std::move(label),quantity,unit,limits,
                                 std::move(shape),sample,sample,bounds_list});
        if (notify) observe(output.ranges.back(),false,scalar);
    }
};

void nominal_grid_steps(const CaseInput2D& input,Records& records) {
    for (std::size_t axis=0;axis<2;++axis) {
        const double length=axis?input.grid.height_m:input.grid.length_m;
        const auto count=axis?input.grid.requested_ny:input.grid.requested_nx;
        std::array<std::uint32_t,property_event_count> events{};PropertyArithmetic arithmetic(events);
        arithmetic.divide(length,static_cast<double>(count));
        records.floating(events,axis?"nominal-grid-y":"nominal-grid-x");
    }
}

std::string sample_index(const PreparationRange& range,std::size_t index) {
    if (range.shape.empty()) return "()";
    std::vector<std::size_t> coordinates(range.shape.size());
    for (std::size_t axis=range.shape.size();axis-->0;) {
        coordinates[axis]=index%range.shape[axis];index/=range.shape[axis];
    }
    std::string text="(";
    for (std::size_t axis=0;axis<coordinates.size();++axis) {
        if (axis) text+=", ";text+=std::to_string(coordinates[axis]);
    }
    return text+(coordinates.size()==1?",)":")");
}
std::string range_warning(const PreparationRange& range) {
    const auto& sample=range.sample;
    if (!sample.low && !sample.high && !sample.nonfinite) return {};
    const auto extremum=[&](double value,std::size_t index) {
        return sample.have_finite?"("+decimal(value)+", "+sample_index(range,index)+")":"None";
    };
    std::string shape="scalar";
    if (!range.shape.empty()) {
        shape="array(";
        for (std::size_t i=0;i<range.shape.size();++i) {if(i)shape+=", ";shape+=std::to_string(range.shape[i]);}
        shape+=range.shape.size()==1?",)":")";
    }
    return range.label+": "+range.quantity+" source range "+(range.bounds_list?"[":"(")+decimal(range.bounds[0])+", "+decimal(range.bounds[1])+(range.bounds_list?"] ":") ")+
        range.unit+"; view="+range.source.front()+", side="+range.side+", stage="+range.stage+", layout="+range.layout+
        ", sample="+shape+"; finite extrema across observations: min="+extremum(sample.minimum,sample.minimum_index)+
        ", max="+extremum(sample.maximum,sample.maximum_index)+" (value, index); worst single snapshot: low="+
        std::to_string(sample.low)+", high="+std::to_string(sample.high)+", outside="+std::to_string(sample.low+sample.high)+
        "/"+std::to_string(sample.size)+" ("+fixed(100.*static_cast<double>(sample.low+sample.high)/
        static_cast<double>(sample.size),2)+"% of sampled values); peak nonfinite in one snapshot="+
        std::to_string(sample.nonfinite)+"/"+std::to_string(sample.size)+" (not classified inside range).";
}

PropertyInput operand(const double& value) {return {{&value,1}};}
const std::array<double,2>& re_range(Fluid fluid) {
    switch (fluid) {
    case Fluid::air:return data::air_nu_re_range;
    case Fluid::water:return data::water_nu_re_range;
    case Fluid::sco2:return data::sco2_nu_re_range;
    case Fluid::co2:return data::co2_nu_re_range;
    }
    throw std::invalid_argument("unknown preparation fluid");
}
template<class Inlet>
double property(std::uint32_t quantity,const Inlet& inlet,
                const std::string& side,const std::string& stage,Records& records,
                const std::string& layout="scalar") {
    const auto temperature=inlet.temperature_K,pressure=inlet.pressure_Pa;
    if (inlet.fluid==Fluid::co2) return co2_pt({}, {&temperature,1},{&pressure,1},true).at(quantity);
    if (inlet.fluid==Fluid::sco2) {
        constexpr const char* keys[]{"D","V","L","C"};
        return sco2_pt(0,{keys[quantity]},{&temperature,1},{&pressure,1}).front();
    }
    const bool water=inlet.fluid==Fluid::water;
    constexpr std::array<Empirical,4> air{{Empirical::air_density,Empirical::air_viscosity,
                                         Empirical::air_conductivity,Empirical::air_cp}};
    const auto getter=water?static_cast<Empirical>(4+quantity):air[quantity];
    if (const auto range=empirical_range(getter);range.label)
        records.range({"property",range.label},side,stage,side=="unbound"?"source":layout,
            range.label,"T","K",range.bounds,temperature);
    const auto result=empirical(getter,operand(temperature),operand(pressure));
    records.floating(result.events);
    return result.values.front();
}
PropertyResult inlet_re(double rho,double velocity,double diameter,double mu,Records& records) {
    auto result=reynolds(operand(rho),operand(velocity),operand(diameter),operand(mu));
    records.floating(result.events);return result;
}
template<class Inlet> void check_co2_inlet(const Inlet& inlet,std::size_t side) {
    if (inlet.fluid!=Fluid::co2) return;
    try {co2_pt({}, {&inlet.temperature_K,1},{&inlet.pressure_Pa,1},true);}
    catch (const PropertyError& error) {
        const auto& value=error.failure;
        std::vector<PreparationFailureCause> causes{{1,error.what()}};
        if (value.reason!=1 && value.reason!=5) {
            const std::string prefix="CO2 requires a stable single-phase PT state; saturation, two-phase and critical-point states are unsupported. ";
            const std::string message=error.what();
            causes.push_back({1,message.compare(0,prefix.size(),prefix)==0?message.substr(prefix.size()):message});
        }
        PreparationError failure(error.status,"CO2 inlet "+std::string(side?"B":"A")+": "+error.what(),1,
                                 static_cast<std::uint32_t>(side),std::move(causes));
        failure.have_property=true;failure.property={value.reason,value.input,value.index,value.first_t_index,
            value.first_p_index,value.temperature,value.pressure,value.detail,value.fp};
        throw failure;
    }
}
template<class Input>
PreparationGeometryKey geometry_key(const Input& input) {
    return {input.geometry.topology,input.geometry.cell_length_mm,input.geometry.wall_thickness_mm};
}
template<class Input>
PreparationInletKey inlet_key(const Input& input,std::size_t side,bool nominal) {
    const auto& inlet=input.sides[side];
    PreparationInletKey key{geometry_key(input),inlet.fluid,inlet.velocity_m_s,inlet.temperature_K,
        inlet.pressure_Pa,{},co2_geometry(input)};
    if (nominal) key.sco2_nu=input.sco2_nu;
    return key;
}
template<class Input>
geometry::MaterialGeometry material_geometry(const Input&,const PreparationOptions&,const PreparationCallbacks& = {});
template<class Input,class Inlet>
void preflight(const Input& input,const PreparationOptions& options,const geometry::Geometry& geometry,
               const std::array<Inlet,2>& sides,Records& records) {
    for (std::size_t i=0;i<2;++i) {
        const auto& inlet=sides[i];const std::string side=i?"B":"A";
        check_co2_inlet(inlet,i);
        const double rho=property(0,inlet,"unbound","unbound",records);
        const double mu=property(1,inlet,"unbound","unbound",records);
        const auto diameter=(records.callbacks.geometry_cache || records.callbacks.geometry_cache_at)?
            material_geometry(input,options,records.callbacks).geometry.hydraulic_diameter:geometry.hydraulic_diameter;
        const double re=inlet_re(rho,inlet.velocity_m_s,diameter,mu,records).values.front();
        const auto& bounds=re_range(inlet.fluid);
        const auto fluid=std::string(fluid_name(inlet.fluid));
        records.range({"nu",fluid,topology_name(input.geometry.topology)},side,"inlet-preflight","scalar",
                      fluid+" inlet Nu","Re","-",bounds,re);
        std::vector<std::string> reasons;
        if (!(bounds[0]<=re && re<=bounds[1])) {
            reasons.push_back("Fluid "+side+": Re = "+fixed(re,0)+" outside "+fluid+" Nu window ["+
                fixed(bounds[0],0)+", "+fixed(bounds[1],0)+"] (u="+
                decimal(inlet.velocity_m_s)+" m/s, T="+decimal(inlet.temperature_K)+" K, P="+
                fixed(inlet.pressure_Pa,0)+" Pa, L="+decimal(input.geometry.cell_length_mm)+"mm, t="+
                decimal(input.geometry.wall_thickness_mm)+"mm).");
        }
        if (inlet.fluid==Fluid::co2) {
            const auto cp=property(3,inlet,"unbound","unbound",records);
            const auto conductivity=property(2,inlet,"unbound","unbound",records);
            const auto value=prandtl(operand(mu),operand(cp),operand(conductivity));
            records.floating(value.events);const double pr=value.values.front();
            records.range({"nu_pr","co2",topology_name(input.geometry.topology)},side,"inlet-preflight","scalar",
                          "CO2 inlet Nu","Pr","-",data::co2_nu_pr_range,pr);
            if (!(data::co2_nu_pr_range[0]<=pr && pr<=data::co2_nu_pr_range[1]))
                reasons.push_back("Fluid "+side+": Pr="+significant(pr,6)+" outside CO2 Nu window ["+
                                  significant(data::co2_nu_pr_range[0],6)+", "+significant(data::co2_nu_pr_range[1],6)+"].");
        }
        const auto nu_count=reasons.size();
        if (input.geometry.cell_length_mm<df_data::df_L_nodes.front()
            || input.geometry.cell_length_mm>df_data::df_L_nodes.back())
            reasons.push_back("V2 L_cell must be inside the "+significant(df_data::df_L_nodes.front(),6)+".."+significant(df_data::df_L_nodes.back(),6)+" mm CFD grid.");
        if (input.geometry.wall_thickness_mm<df_data::df_t_nodes.front()
            || input.geometry.wall_thickness_mm>df_data::df_t_nodes.back())
            reasons.push_back("V2 wall thickness must be inside the "+significant(df_data::df_t_nodes.front(),6)+".."+significant(df_data::df_t_nodes.back(),6)+" mm CFD grid.");
        if (!reasons.empty() && !options.allow_extrapolation) {
            std::string text;for (const auto& reason:reasons) {if(!text.empty())text+=" | ";text+=reason;}
            throw PreparationError(1,std::move(text),1,static_cast<std::uint32_t>(i));
        }
        for (const auto& reason:reasons)
            records.emit({PreparationEventKind::warning,"", "[surrogate extrap] "+reason});
        if (records.callbacks.observe_notice) for (std::size_t j=nu_count;j<reasons.size();++j)
            records.callbacks.observe_notice(records.callbacks.context,2,static_cast<std::uint32_t>(i),0.,reasons[j]);
        // The original per-side record keeps the first Nu reason.
        if (nu_count) {
            records.warning(reasons.front());
            if (records.callbacks.observe_notice)
                records.callbacks.observe_notice(records.callbacks.context,1,static_cast<std::uint32_t>(i),0.,reasons.front());
        }
    }
}

InletQueryResult inlet_property_values(const InletPropertyQuery& query,Records& records,
    const std::string& side,const std::string& stage,const std::string& layout,bool raw_query,
    std::uint32_t notice_side=0) {
    const auto& input=query.inlet;
    const InletInput2D inlet{input.fluid,input.velocity_m_s,input.temperature_K,input.pressure_Pa,{}, {}};
    const auto validate_host=[&](std::uint32_t step) {
        if (raw_query && records.callbacks.validate_host_input)
            records.callbacks.validate_host_input(records.callbacks.context,4,step);
    };
    double diameter_mm=0.;
    if (raw_query) {
        validate_host(0);
        std::array<std::uint32_t,property_event_count> events{};PropertyArithmetic arithmetic(events);
        diameter_mm=arithmetic.multiply(query.hydraulic_diameter_m,1000.);
        records.floating(events);
        validate_host(1);
        if (input.fluid==Fluid::sco2 && input.sco2_nu) validate_nu(*input.sco2_nu);
    }
    InletQueryResult output{};
    constexpr std::array<std::uint32_t,4> quantities{1,2,0,3};
    for (std::size_t i=0;i<quantities.size();++i) {
        validate_host(static_cast<std::uint32_t>(2+i));
        const auto quantity=quantities[i];
        output[quantity]=property(quantity,inlet,side,stage,records,layout);
    }
    validate_host(6);
    auto result=reynolds(operand(output[0]),operand(input.velocity_m_s),
        operand(query.hydraulic_diameter_m),operand(output[1]));
    records.floating(result.events);output[5]=result.values.front();
    if (records.callbacks.observe_notice) {
        const auto& bounds=re_range(input.fluid);
        const auto message=bounds[0]<=output[5] && output[5]<=bounds[1]?std::string{}:
            std::string(topology_name(input.geometry.topology))+": Re = "+fixed(output[5],1)+
            " is outside the validated range ["+fixed(bounds[0],0)+", "+fixed(bounds[1],0)+
            "]. Correlation accuracy may be reduced.";
        records.callbacks.observe_notice(records.callbacks.context,0,notice_side,output[5],message);
    }
    result=prandtl(operand(output[1]),operand(output[3]),operand(output[2]));
    records.floating(result.events);output[4]=result.values.front();
    if (!raw_query) diameter_mm=query.hydraulic_diameter_m*1000.;
    validate_host(7);
    std::array<double,4> extrema{};
    const auto route=input.fluid==Fluid::air?NuRoute::air_direct:input.fluid==Fluid::water?NuRoute::water:
                     input.fluid==Fluid::sco2?NuRoute::sco2:NuRoute::co2;
    const auto co2=input.fluid==Fluid::co2;
    const auto cell=input.geometry.cell_length_mm;
    result=nu_inputs(route,operand(output[5]),operand(output[4]),operand(cell),operand(diameter_mm),{},extrema);
    records.floating(result.events);
    const double prepared_re=result.values.front(),pr=input.fluid==Fluid::air?data::pr_air:output[4];
    const auto label=input.fluid==Fluid::air?"[Nu extrap] ":input.fluid==Fluid::water?"[water Nu extrap] ":
                     input.fluid==Fluid::sco2?"[sCO2 Nu extrap] ":"[CO2 Nu extrap] ";
    records.range({"nu",fluid_name(input.fluid),topology_name(input.geometry.topology)},side,stage,layout,
        std::string(label)+topology_name(input.geometry.topology),"Re","-",re_range(input.fluid),output[5],{},false,extrema[0]);
    if (co2) records.range({"nu_pr","co2",topology_name(input.geometry.topology)},side,stage,layout,
        std::string(label)+topology_name(input.geometry.topology),"Pr","-",data::co2_nu_pr_range,output[4],{},true);
    const double alpha=input.fluid==Fluid::sco2 && input.sco2_nu && input.sco2_nu->mode?
        *input.sco2_nu->alpha[static_cast<std::size_t>(input.geometry.topology)]:1.;
    result=nusselt(route,input.geometry.topology,operand(prepared_re),operand(pr),
        operand(cell),operand(diameter_mm),alpha);
    records.floating(result.events);output[6]=result.values.front();
    result=surface_transfer(operand(output[6]),operand(output[2]),operand(query.hydraulic_diameter_m));
    records.floating(result.events);output[10]=result.values.front();
    validate_host(8);
    const auto drag=fixed_df(static_cast<std::uint32_t>(input.geometry.topology),cell,input.geometry.wall_thickness_mm);
    output[7]=drag.K;output[8]=drag.cF;
    if (query.exact_co2_drag) {
        const auto factors=df_co2_factors();
        output[7]=df_apply_scale({&drag.K,1},{&factors.K,1},false).front();
        output[8]=df_apply_scale({&drag.cF,1},{&factors.cF,1},false).front();
    }
    result=df_pressure_gradient(operand(output[0]),operand(output[1]),operand(input.velocity_m_s),
        operand(output[7]),operand(output[8]));
    records.floating(result.events);output[9]=result.values.front();
    validate_host(9);
    result=pore_conductivity(operand(query.epsilon_a),operand(output[2]));
    records.floating(result.events);output[11]=result.values.front();
    return output;
}

template<class Input,class Inlet>
UniformInletProperties inlet_properties(const Input& input,const Inlet& inlet,std::size_t index,
                                       const geometry::MaterialGeometry& geometry,Records& records,
                                       bool unbound=false,const std::string& bound_layout="scalar") {
    InletPropertyQuery query;
    query.inlet=inlet_key(input,index,true);
    query.inlet.fluid=inlet.fluid;query.inlet.velocity_m_s=inlet.velocity_m_s;
    query.inlet.temperature_K=inlet.temperature_K;query.inlet.pressure_Pa=inlet.pressure_Pa;
    query.hydraulic_diameter_m=geometry.geometry.hydraulic_diameter;
    query.epsilon_a=geometry.geometry.epsilon_a;
    query.exact_co2_drag=inlet.fluid==Fluid::co2;
    const auto values=inlet_property_values(query,records,unbound?"unbound":index?"B":"A",
        unbound?"unbound":"inlet",unbound?"source":bound_layout,false,static_cast<std::uint32_t>(index));
    return {values[0],values[1],values[2],values[3],values[4],values[5],
        values[6],values[7],values[8],values[9],values[10],values[11],
        geometry.solid_conductivity};
}

template<class Input,class Inlet>
DfPair drag_factors(const Input& input,const Inlet& inlet,std::size_t index,Records& records,
                   PreparationDragEvidence& evidence,bool continuous,const std::string& layout) {
    evidence.campaign="water-sco2-cfd-fixed-v2";evidence.scope="CFD-smooth-wall";
    DfPair factors{1.,1.};
    const bool co2=inlet.fluid==Fluid::co2,experimental=!co2 && input.df_mode==1;
    if (co2) {
        factors=df_co2_factors();evidence.campaign=data::co2_application_version;
        evidence.scope="CO2-user-fixed";evidence.fluid="co2";
    } else if (experimental) {
        const auto selected=experiment_selection(input,inlet,index,continuous);
        evidence.selection=selected.first;factors=selected.second;
        const auto& selection=selected.first;
        const char* campaigns[]{"air-specimen-friction","water-air-hx-7-6",
                                df_data::hx_air_calibration[0][1],"sco2-hx-hot-ok-dp"};
        evidence.campaign=campaigns[selection.campaign];
        evidence.scope=selection.scope?"HX-effective":"core-calibrated";
        if (selection.scope) {
            evidence.application_scope=continuous?
                "Exploratory Gyroid air/water geometry transfer of frozen 7/0.6 HX factors; accuracy unvalidated":
                df_data::hx_application_scope;
            if (continuous) evidence.transfer_policy="frozen-hx-7-0.6-trend";
            if (inlet.fluid==Fluid::air && input.geometry.topology==Topology::gyroid)
                for (const auto& item:df_data::hx_air_calibration) evidence.calibration.push_back({item[0],item[1]});
            const auto fluid=std::string(fluid_name(inlet.fluid));
            const auto topology=std::string(topology_name(input.geometry.topology));
            const auto label="[D-F extrap] "+fluid+"/"+topology+"; frozen sF; "+
                (continuous?"research transfer":"approved application")+"; reference window ["+
                decimal(selection.application_u[0])+", "+decimal(selection.application_u[1])+"] m/s; "+evidence.application_scope;
            records.range({"df-experimental",fluid,topology},index?"B":"A","prepared-df",layout,label,
                "inlet u","m/s",{selection.runtime_u[0],selection.runtime_u[1]},inlet.velocity_m_s);
        }
    }
    return factors;
}

void prepare_drag(const CaseInput2D& input,std::size_t index,DfPair base,PreparedSide2D& side,Records& records,
                  const std::vector<DfPair>* local=nullptr,const PhysicalGrid2D* grid=nullptr) {
    auto& evidence=side.drag_evidence;
    const bool experimental=side.inlet.fluid!=Fluid::co2 && input.df_mode==1;
    const auto factors=drag_factors(input,side.inlet,index,records,evidence,local!=nullptr,"solver-row");
    side.seed_permeability_m2=df_apply_scale({&base.K,1},{&factors.K,1},false).front();
    side.seed_forchheimer_per_m=df_apply_scale({&base.cF,1},{&factors.cF,1},false).front();
    side.row_permeability.assign(side.stream_widths.size(),side.seed_permeability_m2);
    side.row_forchheimer.assign(side.stream_widths.size(),side.seed_forchheimer_per_m);
    if (local) {
        const auto cross=side.cross_widths.size(),stream=side.stream_widths.size();
        std::vector<double> base_k(count(cross,stream)),base_f(base_k.size());
        const auto direction=side.inlet.port.direction;
        for (std::size_t row=0;row<cross;++row) for (std::size_t column=0;column<stream;++column) {
            const auto physical=(direction==1 || direction==3)?stream-1-column:column;
            const auto source=direction<2?physical*grid->ny+row:row*grid->ny+physical;
            base_k[row*stream+column]=(*local)[source].K;base_f[row*stream+column]=(*local)[source].cF;
        }
        const std::vector<double> scale_k(base_k.size(),factors.K),scale_f(base_f.size(),factors.cF);
        side.permeability=df_apply_scale({base_k.data(),base_k.size()},{scale_k.data(),scale_k.size()},experimental);
        side.forchheimer=df_apply_scale({base_f.data(),base_f.size()},{scale_f.data(),scale_f.size()},experimental);
        const auto rows=df_row_means(cross,stream,{side.permeability.data(),side.permeability.size()},
            {side.forchheimer.data(),side.forchheimer.size()},false,false);
        for (std::size_t i=0;i<rows.size();++i) {
            side.row_permeability[i]=rows[i].K;side.row_forchheimer[i]=rows[i].cF;
        }
        evidence.base_permeability=df_summary({base_k.data(),base_k.size()},base_k.size()==1);
        evidence.base_forchheimer=df_summary({base_f.data(),base_f.size()},base_f.size()==1);
        evidence.applied_permeability=df_summary({side.permeability.data(),side.permeability.size()},side.permeability.size()==1);
        evidence.applied_forchheimer=df_summary({side.forchheimer.data(),side.forchheimer.size()},side.forchheimer.size()==1);
        evidence.scale_permeability=factors.K;evidence.scale_forchheimer=factors.cF;
        if (experimental) {
            evidence.geometry_application="continuous-field-extrapolation";
            evidence.reference_geometry_mm=std::array<double,2>{input.geometry.cell_length_mm,input.geometry.wall_thickness_mm};
            evidence.application_scope="Exploratory continuous L/t trend prediction using "
                "frozen uniform-HX factors; gradient accuracy unvalidated";
        }
        return;
    }
    const bool summary_scalar=experimental || side.stream_widths.size()==1;
    const std::vector<double> base_k(side.stream_widths.size(),base.K),base_f(side.stream_widths.size(),base.cF);
    evidence.base_permeability=df_summary({base_k.data(),base_k.size()},summary_scalar);
    evidence.base_forchheimer=df_summary({base_f.data(),base_f.size()},summary_scalar);
    evidence.applied_permeability=df_summary({side.row_permeability.data(),side.row_permeability.size()},summary_scalar);
    evidence.applied_forchheimer=df_summary({side.row_forchheimer.data(),side.row_forchheimer.size()},summary_scalar);
    evidence.scale_permeability=factors.K;evidence.scale_forchheimer=factors.cF;
}

template<class Input> void model_evidence(const Input& input,PreparationEvidence& evidence,bool continuous=false) {
    for (std::size_t i=0;i<2;++i) {
        const auto co2=input.sides[i].fluid==Fluid::co2;
        evidence.models[i]={co2?"co2_fluid":"fluid",co2?data::co2_fluid_version:data::fluid_version,i?"B":"A"};
    }
    evidence.co2_geometry=co2_geometry(input);
    evidence.models[2]={evidence.co2_geometry?"co2_geometry":"geometry",
                       evidence.co2_geometry?data::co2_geometry_version:data::geometry_version,""};
    evidence.models[3]={"darcy_forchheimer",data::darcy_forchheimer_version,""};
    evidence.sco2_nu_model_version=input.sco2_nu.mode?"sco2-cfd-common-multiplier-v1":"sco2-cfd-smooth";
    evidence.sco2_nu_coefficients=data::nu_sco2;
    if (input.sco2_nu.mode && (input.sides[0].fluid==Fluid::sco2 || input.sides[1].fluid==Fluid::sco2)) {
        const auto& selected=input.sco2_nu;
        auto notice="sCO2 Nu experimental effective correction ["+selected.parameter_version+"]; source: "+selected.source+
            "; declared applicability: "+selected.applicability+
            ". This selection does not certify local Nu or whole-unit validation.";
        if (input.geometry.cell_length_mm!=df_data::hx_geometry_mm[0]
            || input.geometry.wall_thickness_mm!=df_data::hx_geometry_mm[1] || continuous)
            notice+=" Experimental geometry extrapolation beyond the uniform 7 mm / 0.6 mm specimen.";
        evidence.notices.push_back(std::move(notice));
    }
    if (evidence.co2_geometry) {
        evidence.co2_version=data::co2_model_version;evidence.co2_application_version=data::co2_application_version;
        evidence.co2_pressure_multiplier=df_data::co2_pressure_multiplier;evidence.co2_nu_multiplier=data::co2_nu_multiplier;
        evidence.co2_drag_factors=df_co2_factors();evidence.co2_re_range=data::co2_nu_re_range;evidence.co2_pr_range=data::co2_nu_pr_range;
        evidence.notices.push_back("CO2: single-phase HEOS; segment-2 constant-property CFD Nu. "
            "Fixed K=K0/2.5, cF=2.5*cF0, Nu=1.28*Nu_base, including its floor, "
            "on CO2 sides only. These user factors do not establish experimental "
            "accuracy for variable-property heat exchangers or geometry gradients.");
    }
}
template<class Input>
geometry::MaterialGeometry material_geometry(const Input& input,const PreparationOptions& options,const PreparationCallbacks& callbacks) {
    const auto& model=input.geometry;
    geometry::MaterialGeometry output{};
    const auto calibration=geometry::calibration(model.topology);
    const bool co2=co2_geometry(input);
    if (co2) {
        static const std::array<geometry::Co2GeometryTable,2> tables{{geometry::Co2GeometryTable::from_generated(Topology::diamond),
                                                                   geometry::Co2GeometryTable::from_generated(Topology::gyroid)}};
        output=tables[static_cast<std::size_t>(model.topology)].evaluate(
            model.cell_length_mm,model.wall_thickness_mm,model.solid_conductivity_W_mK,options.chi_override);
    } else {
        const auto key=geometry_key(input);
        const bool hit=callbacks.geometry_cache_at?callbacks.geometry_cache_at(callbacks.context,false,key,output.geometry):
            callbacks.geometry_cache && callbacks.geometry_cache(callbacks.context,false,output.geometry);
        if (!hit) {
            output.geometry=geometry::standard_geometry(geometry_index(model.topology),calibration,
                model.cell_length_mm,model.wall_thickness_mm);
            if (callbacks.geometry_cache_at) callbacks.geometry_cache_at(callbacks.context,true,key,output.geometry);
            else if (callbacks.geometry_cache) callbacks.geometry_cache(callbacks.context,true,output.geometry);
        }
        output.solid_conductivity=geometry::solid_conductivity(calibration.solid_tortuosity,
            output.geometry.epsilon,model.solid_conductivity_W_mK,options.chi_override);
    }
    return output;
}

void prepare_ports(const PhysicalGrid2D& grid,PreparedSide2D& side) {
    const auto& port=side.inlet.port;
    const bool x=port.direction==0 || port.direction==1;
    side.cross_widths=x?grid.dy:grid.dx;
    side.stream_widths=x?grid.dx:grid.dy;
    if (port.direction==1 || port.direction==3) std::reverse(side.stream_widths.begin(),side.stream_widths.end());
    const auto edges=g::rectangles(native_port(port),1.);
    side.inlet_bounds={edges[0],edges[1]};
    side.outlet_bounds={edges[4],edges[5]};
    auto openings=g::port_fractions(side.cross_widths,edges[0],edges[1],port.uniform_inlet);
    side.inlet_geometry=std::move(openings[0]);side.inlet_profile=std::move(openings[1]);
    openings=g::port_fractions(side.cross_widths,edges[4],edges[5]);
    side.outlet_geometry=std::move(openings[0]);side.outlet_profile=std::move(openings[1]);
    side.outlet_u_fraction=g::port_overlap(side.cross_widths,edges[4],edges[5],true);
}

void record_grid(const CaseInput2D& input,const PhysicalGrid2D& grid,Records& records) {
    if (grid.nx!=input.grid.requested_nx || grid.ny!=input.grid.requested_ny)
        records.emit({PreparationEventKind::log,logger,"[run_calculation] Wall-refined grid: "+
            std::to_string(grid.nx)+"×"+std::to_string(grid.ny)+" cells (4-wall BL resolved)"});
}

void finish_warnings(Records& records) {
    for (const auto item:records.warning_order) {
        const auto warning=item.first?range_warning(records.output.ranges[item.second]):records.plain_warnings[item.second];
        if (!warning.empty() && std::find(records.output.warnings.begin(),records.output.warnings.end(),warning)==records.output.warnings.end())
            records.output.warnings.push_back(warning);
    }
}

struct LocalGeometry2D {
    std::vector<double> cell_mm,wall_mm,epsilon,solid,radius,area,diameter;
};
double control_midpoint(double length,Records* records,const char* source="control-axis-midpoint") {
    std::array<std::uint32_t,property_event_count> events{};PropertyArithmetic arithmetic(events,records!=nullptr);
    const auto value=arithmetic.divide(length,2.);
    if (records) records->floating(events,source);
    return value;
}
// This follows np.linspace(0, length, count) for float64 values.
std::vector<double> control_axis(std::size_t count,double length,Records* records=nullptr) {
    if (count==1) return {control_midpoint(length,records)};
    const double divisor=static_cast<double>(count-1);
    std::array<std::uint32_t,property_event_count> events{};PropertyArithmetic arithmetic(events,records!=nullptr);
    const auto step=arithmetic.divide(length,divisor);
    if (records) records->floating(events,"control-axis-step");
    events.fill(0);
    std::vector<double> values(count);
    for (std::size_t i=0;i<count;++i) {
        const double index=static_cast<double>(i);
        PropertyArithmetic element(events,records!=nullptr);
        values[i]=step==0.?element.multiply(element.divide(index,divisor),length):element.multiply(index,step);
    }
    if (records) for (const auto event:events) if (event) {
        const auto operation=(event>>8)&255u;
        const auto source=step!=0.?"control-axis-multiply":
            operation==3?"control-axis-scale":"control-axis-divide";
        records->emit({PreparationEventKind::floating_point,"",source,event});
    }
    values.back()=length;
    return values;
}
std::array<std::vector<double>,2> control_axes(const CaseInput2D& input,Records& records) {
    const auto& controls=*input.continuous;
    const std::array<double,2> lengths{{input.grid.length_m,input.grid.height_m}};
    std::array<std::vector<double>,2> axes{{control_axis(controls.nx,lengths[0],&records),
        control_axis(controls.ny,lengths[1],&records)}};
    for (std::size_t axis=0;axis<2;++axis) {
        const auto& values=axes[axis];
        for (std::size_t i=0;i<values.size();++i)
            if (!std::isfinite(values[i]) || (i && values[i]<=values[i-1]))
                throw std::invalid_argument("control axes must increase across the domain, or use its midpoint for one control");
        if (values.size()==1?values[0]!=control_midpoint(lengths[axis],&records,"control-axis-check-midpoint"):
                values.front()!=0. || values.back()!=lengths[axis])
            throw std::invalid_argument("control axes must increase across the domain, or use its midpoint for one control");
    }
    return axes;
}
std::array<std::vector<double>,2> sampling_axes(const CaseInput2D& input,const PhysicalGrid2D* grid=nullptr) {
    std::array<std::vector<double>,2> axes;
    for (std::size_t axis=0;axis<2;++axis) {
        const double extent=axis?input.grid.height_m:input.grid.length_m;
        const auto count=grid?(axis?grid->ny:grid->nx):(axis?input.grid.requested_ny:input.grid.requested_nx);
        const auto* widths=grid?(axis?&grid->dy:&grid->dx):nullptr;
        if (widths) {
            const double total=0.+tpmshx::detail::contiguous_sum({widths->data(),widths->size()});
            if (!(std::abs(total-extent)<=1e-12*extent))
                throw std::invalid_argument("cell widths must be finite, positive and cover the field domain");
        }
        axes[axis]=g::continuous_centres(count,extent,widths);
    }
    for (std::size_t axis=0;axis<2;++axis) {
        const auto& points=axes[axis];
        const char* error="sampling axes must be finite, increasing and inside the field domain";
        try {fields::sample_axis(points.data(),points.size());}
        catch (const std::invalid_argument&) {throw std::invalid_argument(error);}
        if (points.front()<0. || points.back()>(axis?input.grid.height_m:input.grid.length_m))
            throw std::invalid_argument(error);
    }
    return axes;
}
LocalGeometry2D local_geometry(const CaseInput2D& input,const PhysicalGrid2D& grid,
                               const PreparationOptions& options,Records& records) {
    const auto& controls=*input.continuous;
    const auto axes=control_axes(input,records),samples=sampling_axes(input,&grid);
    const auto& x=axes[0];const auto& y=axes[1];
    const auto& xc=samples[0];const auto& yc=samples[1];
    const auto half_y=controls.symmetric_y?controls.ny/2+controls.ny%2:controls.ny;
    const auto half=count(controls.nx,half_y);
    std::array<std::vector<double>,2> sampled;
    for (std::size_t field=0;field<2;++field) {
        std::vector<double> values(count(controls.nx,controls.ny));
        for (std::size_t i=0;i<controls.nx;++i) for (std::size_t j=0;j<controls.ny;++j) {
            const auto source=controls.symmetric_y && j>=half_y?controls.ny-1-j:j;
            values[i*controls.ny+j]=controls.decision_mm[field*half+i*half_y+source];
        }
        const auto& limits=field?controls.wall_bounds_mm:controls.cell_bounds_mm;
        if (controls.nx>1 && controls.ny>1) {
            fields::XYFit fit(x.data(),x.size(),y.data(),y.size(),values.data(),values.size(),
                static_cast<int>(std::min<std::size_t>(controls.order,controls.nx-1)),
                static_cast<int>(std::min<std::size_t>(controls.order,controls.ny-1)));
            sampled[field]=fit.sample(values.data(),values.size(),xc.data(),xc.size(),yc.data(),yc.size(),limits[0],limits[1]);
        } else {
            const std::size_t counts[]{controls.nx,controls.ny},sizes[]{grid.nx,grid.ny};
            const double* axis_data[]{x.data(),y.data()};const double* sample_data[]{xc.data(),yc.data()};
            sampled[field]=fields::sample_tensor(2,counts,axis_data,values.data(),values.size(),
                static_cast<int>(controls.order),sizes,sample_data,limits[0],limits[1]);
        }
    }
    LocalGeometry2D output;output.cell_mm=std::move(sampled[0]);output.wall_mm=std::move(sampled[1]);
    const auto& model=input.geometry;const auto cells=count(grid.nx,grid.ny);
    std::vector<geometry::MaterialGeometry> materials;
    if (co2_geometry(input)) {
        const auto table=geometry::Co2GeometryTable::from_generated(model.topology);
        materials.reserve(cells);
        for (std::size_t i=0;i<cells;++i) materials.push_back(table.evaluate(
            output.cell_mm[i],output.wall_mm[i],model.solid_conductivity_W_mK,options.chi_override));
    } else materials=geometry::standard_material_geometry_batch(geometry_index(model.topology),
        geometry::calibration(model.topology),{output.cell_mm.data(),cells},{output.wall_mm.data(),cells},
        model.solid_conductivity_W_mK,options.chi_override);
    for (const auto& material:materials) {
        const auto& value=material.geometry;
        output.epsilon.push_back(value.epsilon);output.solid.push_back(material.solid_conductivity);
        output.radius.push_back(geometry::hydraulic_radius(value.hydraulic_diameter));
        output.area.push_back(value.area_density);output.diameter.push_back(value.hydraulic_diameter);
    }
    return output;
}
struct InletGeometry2D {
    geometry::MaterialGeometry material;
    PhysicalGrid2D grid;
    std::array<PreparedSide2D,2> sides;
    std::optional<LocalGeometry2D> local;
};

void prepare_thermal_sides(PreparedCase2D& output,const CaseInput2D& input) {
    if (!input.offset_scope || input.geometry.delta_levelset==0.) return;
    const auto& model=input.geometry;
    const auto value=geometry::asym::prepare_from_index(geometry_index(model.topology),
        geometry::calibration(model.topology),model.cell_length_mm,model.wall_thickness_mm,model.delta_levelset);
    output.split_a=value.split_a;output.thermal_sides=value.sides;
}

PreparedCase2D prepare_case(const CaseInput2D& input,const PreparationOptions& options,
                              const PreparationCallbacks& callbacks,CaseScope scope,const InletGeometry2D* inlet_geometry=nullptr) {
    FloatingEnvironment floating_environment;
    if (callbacks.validate_host_input) callbacks.validate_host_input(callbacks.context,0,2);
    const auto inlets=validate(input,scope);
    PreparedCase2D output{};output.input=input;output.options=options;
    Records records{output.evidence,callbacks,{},{}};
    nominal_grid_steps(input,records);
    const auto& model=input.geometry;
    if (callbacks.validate_host_input) callbacks.validate_host_input(callbacks.context,1,2);
    output.uniform_geometry=inlet_geometry && !callbacks.geometry_cache?inlet_geometry->material:material_geometry(input,options,callbacks);
    const auto& uniform=output.uniform_geometry.geometry;
    output.hydraulic_radius_m=geometry::hydraulic_radius(uniform.hydraulic_diameter);
    preflight(input,options,uniform,inlets,records);
    // The original first field construction precedes conductivity and mesh checks.
    if (input.continuous) {control_axes(input,records);sampling_axes(input);}
    // Full host preparation reads both conductivities before and after its mesh.
    if (input.continuous) for (std::size_t i=0;i<2;++i)
        property(2,inlets[i],"unbound","unbound",records);
    if (!inlet_geometry && callbacks.validate_grid) callbacks.validate_grid(callbacks.context);
    output.grid=inlet_geometry?inlet_geometry->grid:physical_grid(input.grid,inlets);
    if (!inlet_geometry) record_grid(input,output.grid,records);
    std::optional<LocalGeometry2D> local;
    std::vector<DfPair> local_drag;
    if (input.continuous) {
        if (inlet_geometry) control_axes(input,records);
        local=inlet_geometry?inlet_geometry->local:std::optional<LocalGeometry2D>{local_geometry(input,output.grid,options,records)};
        auto& epsilon_half=output.design_pore_porosity;
        epsilon_half.resize(local->epsilon.size());
        for (std::size_t i=0;i<epsilon_half.size();++i) epsilon_half[i]=local->epsilon[i]*.5;
        for (std::size_t i=0;i<2;++i) {
            const auto conductivity=property(2,inlets[i],"unbound","unbound",records);
            const std::vector<double> conductivity_values(epsilon_half.size(),conductivity);
            auto result=pore_conductivity({{epsilon_half.data(),epsilon_half.size()}},
                {{conductivity_values.data(),conductivity_values.size()}});
            records.floating(result.events);output.fluid_conductivity[i]=std::move(result.values);
        }
        local_drag=fixed_df_batch(static_cast<std::uint32_t>(model.topology),
            {local->cell_mm.data(),local->cell_mm.size()},{local->wall_mm.data(),local->wall_mm.size()});
    }
    const auto drag=fixed_df(static_cast<std::uint32_t>(model.topology),model.cell_length_mm,model.wall_thickness_mm);
    for (std::size_t i=0;i<2;++i) {
        auto& side=output.sides[i];
        if (inlet_geometry) side=inlet_geometry->sides[i];
        side.inlet=inlets[i];
        if (!inlet_geometry) prepare_ports(output.grid,side);
        prepare_drag(input,i,drag,side,records,local?&local_drag:nullptr,local?&output.grid:nullptr);
    }
    // The thermal and final geometry facades use the same scalar cache.
    if (callbacks.geometry_cache) output.uniform_geometry=material_geometry(input,options,callbacks);
    prepare_thermal_sides(output,input);
    for (std::size_t i=0;i<2;++i) {
        if (callbacks.validate_host_input)
            callbacks.validate_host_input(callbacks.context,2,static_cast<std::uint32_t>(i));
        auto& side=output.sides[i];
        if (!callbacks.inlet_cache) {
            side.properties=inlet_properties(input,inlets[i],i,output.uniform_geometry,records);
            continue;
        }
        PreparationInletCache cached{};
        const auto index=static_cast<std::uint32_t>(i);
        const bool hit=callbacks.inlet_cache(callbacks.context,false,index,inlets[i],cached);
        if (!hit) {
            const auto geometry=material_geometry(input,options,callbacks);
            cached.geometry=geometry.geometry;
            Records local_records{cached.evidence,callbacks,{},{}};
            cached.properties=inlet_properties(input,inlets[i],i,geometry,local_records);
            callbacks.inlet_cache(callbacks.context,true,index,inlets[i],cached);
        }
        side.properties=cached.properties;
        const auto calibration=geometry::calibration(model.topology);
        side.properties.solid_conductivity_W_mK=geometry::solid_conductivity(calibration.solid_tortuosity,
            cached.geometry.epsilon,model.solid_conductivity_W_mK,options.chi_override);
        records.merge(cached.evidence,i?"B":"A");
    }
    if (callbacks.geometry_cache) output.uniform_geometry=material_geometry(input,options,callbacks);
    const auto cells=count(output.grid.nx,output.grid.ny);
    output.cell_length_m=model.cell_length_mm*1e-3;
    output.wall_thickness_m=model.wall_thickness_mm*1e-3;
    output.cell_length.assign(cells,output.cell_length_m);output.wall_thickness.assign(cells,output.wall_thickness_m);
    output.total_porosity.assign(cells,uniform.epsilon);
    output.solid_conductivity.assign(cells,output.uniform_geometry.solid_conductivity);
    output.hydraulic_radius.assign(cells,output.hydraulic_radius_m);
    if (local) {
        for (std::size_t i=0;i<cells;++i) {
            output.cell_length[i]=local->cell_mm[i]*1e-3;output.wall_thickness[i]=local->wall_mm[i]*1e-3;
        }
        output.total_porosity=local->epsilon;output.solid_conductivity=local->solid;
        output.hydraulic_radius=local->radius;output.area_density=local->area;output.hydraulic_diameter=local->diameter;
    }
    model_evidence(input,output.evidence,input.continuous.has_value());
    const std::vector<std::size_t> shape{output.grid.nx,output.grid.ny};
    if (local) {
        std::vector<double> cell_mm(cells),wall_mm(cells);
        for (std::size_t i=0;i<cells;++i) {cell_mm[i]=output.cell_length[i]*1e3;wall_mm[i]=output.wall_thickness[i]*1e3;}
        records.range({"geometry","L_field_m"},"shared","prepared-geometry","physical-cell","fixed geometry domain","cell length","mm",
            {df_data::df_L_nodes.front(),df_data::df_L_nodes.back()},cell_mm,shape);
        records.range({"geometry","t_field_m"},"shared","prepared-geometry","physical-cell","fixed geometry domain","wall thickness","mm",
            {df_data::df_t_nodes.front(),df_data::df_t_nodes.back()},wall_mm,shape);
    } else {
    records.range({"geometry","L_field_m"},"shared","prepared-geometry","physical-cell","fixed geometry domain","cell length","mm",
                  {df_data::df_L_nodes.front(),df_data::df_L_nodes.back()},
                  output.cell_length_m*1e3,shape);
    records.range({"geometry","t_field_m"},"shared","prepared-geometry","physical-cell","fixed geometry domain","wall thickness","mm",
                  {df_data::df_t_nodes.front(),df_data::df_t_nodes.back()},
                  output.wall_thickness_m*1e3,shape);
    }
    finish_warnings(records);
    return output;
}


void validate_zone_bounds(const ZonedInput2D& request) {
    if (request.kind>1 || request.axis>1)
        throw std::invalid_argument("native zoned preparation requires stripe/rectangle kind and x/y axis");
    if (request.kind==0) return;
    if (request.regions.empty()) throw std::invalid_argument("Enabled grid zones require non-empty grid cells");
    for (std::size_t i=0;i<request.regions.size();++i) for (std::size_t axis=0;axis<2;++axis) {
        const auto& values=request.regions[i].bounds;
        const auto start=values[2*axis],end=values[2*axis+1];
        if (!(std::isfinite(start) && std::isfinite(end) && !(start<0.) && start<end && !(1.<end)))
            throw std::invalid_argument("Zone grid cell "+std::to_string(i+1)+": "+(axis?"y":"x")+
                " coordinates must be finite and satisfy 0 <= start < end <= 1");
    }
}
bool exceeds_zone_tolerance(double value) {return 1e-9<std::abs(value);}
void sort_stripes(std::vector<ZoneRegion2D>& regions) {
    if (regions.empty()) throw std::invalid_argument("At least one zone is required");
    for (const auto& row:regions)
        if (!std::isfinite(row.bounds[0]) || !std::isfinite(row.bounds[1]))
            throw std::invalid_argument("Zone '"+row.name+"': endpoints must be finite");
    std::stable_sort(regions.begin(),regions.end(),[](const auto& a,const auto& b) {
        return a.bounds[0]<b.bounds[0];
    });
    if (exceeds_zone_tolerance(regions.front().bounds[0]))
        throw std::invalid_argument("First zone must start at 0, got "+decimal(regions.front().bounds[0]));
    if (exceeds_zone_tolerance(regions.back().bounds[1]-1.))
        throw std::invalid_argument("Last zone must end at 1.0, got "+decimal(regions.back().bounds[1]));
    for (std::size_t i=0;i+1<regions.size();++i)
        if (exceeds_zone_tolerance(regions[i].bounds[1]-regions[i+1].bounds[0]))
            throw std::invalid_argument("Gap/overlap between zone '"+regions[i].name+"' (end="+
                decimal(regions[i].bounds[1])+") and '"+regions[i+1].name+"' (start="+
                decimal(regions[i+1].bounds[0])+")");
    for (const auto& row:regions) {
        if (!(row.bounds[0]<row.bounds[1]))
            throw std::invalid_argument("Zone '"+row.name+"': end <= start");
        const double cell=row.cell_length_mm,wall=row.wall_thickness_mm;
        if (std::isnan(cell) || cell<1. || 20.<cell)
            throw std::invalid_argument("Zone '"+row.name+"': L_mm="+decimal(row.cell_length_mm)+" outside [1, 20]");
        if (std::isnan(wall) || wall<.1 || 2.<wall)
            throw std::invalid_argument("Zone '"+row.name+"': t_mm="+decimal(row.wall_thickness_mm)+" outside [0.1, 2.0]");
    }
}

SigmoidLUT2D sigmoid_lut_axes(std::size_t cell_nodes,std::size_t wall_nodes) {
    const auto axis=[](std::size_t count,double lower,double upper) {
        if (!count) return std::vector<double>{};
        if (count==1) return std::vector<double>{lower};
        auto values=control_axis(count,upper-lower);
        for (auto& value:values) value+=lower;
        values.back()=upper;return values;
    };
    SigmoidLUT2D output;
    output.cell_mm=axis(cell_nodes,df_data::df_L_nodes.front(),df_data::df_L_nodes.back());
    output.wall_mm=axis(wall_nodes,df_data::df_t_nodes.front(),df_data::df_t_nodes.back());
    return output;
}

// Raw calls retain first typed values; host hooks own the shared cache.
struct ZonedCache {
    struct GeometryEntry {std::array<double,3> key;geometry::Geometry value;};
    struct InletEntry {std::array<double,7> key;PreparationInletCache value;};
    const PreparationCallbacks& callbacks;
    std::list<GeometryEntry> geometries;
    std::list<InletEntry> inlets;
    std::optional<SigmoidLUT2D> loaded_lut;

    geometry::MaterialGeometry material(const CaseInput2D& input,const PreparationOptions& options) {
        const auto& model=input.geometry;
        const std::array<double,3> key{model.cell_length_mm,model.wall_thickness_mm,static_cast<double>(model.topology)};
        const auto probe=geometry_key(input);geometry::Geometry value{};
        bool hit=false;
        if (callbacks.geometry_cache_at) hit=callbacks.geometry_cache_at(callbacks.context,false,probe,value);
        else {
            const auto found=std::find_if(geometries.begin(),geometries.end(),[&](const auto& item){return item.key==key;});
            hit=found!=geometries.end();
            if (hit) {geometries.splice(geometries.begin(),geometries,found);value=geometries.front().value;}
        }
        if (!hit) {
            if (key[0]<=0.) throw std::invalid_argument("L_mm must be positive, got "+decimal(key[0]));
            if (key[1]<=0.) throw std::invalid_argument("t_mm must be positive, got "+decimal(key[1]));
            const double length=key[0],twice_wall=2.*key[1];
            if (!std::isnan(length) && !std::isnan(twice_wall) && !(twice_wall<length))
                throw std::invalid_argument("Wall thickness t="+decimal(key[1])+
                    "mm >= L="+decimal(key[0])+"mm, no pore space");
            try {value=material_geometry(input,options).geometry;}
            catch (const std::invalid_argument& error) {
                if (std::string_view(error.what()).find("Degenerate TPMS geometry:")==0)
                    throw std::invalid_argument("Degenerate TPMS geometry: "+std::string(topology_name(model.topology))+
                        " L="+decimal(key[0])+"mm t="+decimal(key[1])+"mm has no usable pore space. Reduce t or increase L.");
                throw;
            }
            if (callbacks.geometry_cache_at) callbacks.geometry_cache_at(callbacks.context,true,probe,value);
            else {geometries.push_front({key,value});if (geometries.size()>32768) geometries.pop_back();}
        }
        return {value,geometry::solid_conductivity(geometry::calibration(model.topology).solid_tortuosity,
            value.epsilon,model.solid_conductivity_W_mK,options.chi_override)};
    }
    PreparationInletCache properties(const CaseInput2D& input,std::size_t side,bool nominal,
                                    const PreparationOptions& options,Records& records) {
        const auto& inlet=input.sides[side];
        const std::array<double,7> key{input.geometry.cell_length_mm,input.geometry.wall_thickness_mm,
            inlet.velocity_m_s,inlet.temperature_K,inlet.pressure_Pa,nominal?1.:0.,static_cast<double>(input.geometry.topology)};
        const auto probe=inlet_key(input,side,nominal);PreparationInletCache value;
        bool hit=false;
        if (callbacks.inlet_cache_at) hit=callbacks.inlet_cache_at(callbacks.context,false,probe,value);
        else {
            const auto found=std::find_if(inlets.begin(),inlets.end(),[&](const auto& item){return item.key==key;});
            hit=found!=inlets.end();
            if (hit) {inlets.splice(inlets.begin(),inlets,found);value=inlets.front().value;}
        }
        if (!hit) {
            const auto geometry=material(input,options);value.geometry=geometry.geometry;
            Records local{value.evidence,records.callbacks,{},{}};
            value.properties=inlet_properties(input,inlet,side,geometry,local,!nominal);
            if (nominal) for (auto& range:value.evidence.ranges) {
                range.side=range.stage="unbound";range.layout="source";
            }
            if (callbacks.inlet_cache_at) callbacks.inlet_cache_at(callbacks.context,true,probe,value);
            else {inlets.push_front({key,value});if (inlets.size()>4096) inlets.pop_back();}
        }
        value.properties.solid_conductivity_W_mK=geometry::solid_conductivity(
            geometry::calibration(input.geometry.topology).solid_tortuosity,value.geometry.epsilon,
            input.geometry.solid_conductivity_W_mK,options.chi_override);
        if (hit) value.evidence.events.clear();
        records.merge(value.evidence,nominal?(side?"B":"A"):"");
        return value;
    }
    const SigmoidLUT2D& lut(const ZonedInput2D& input) {
        if (!input.spatial_model || !input.spatial_model->load_default_lut) return input.sigmoid->lut;
        if (!loaded_lut) {
            auto values=sigmoid_lut_axes(41,31);
            const auto topology=input.input.geometry.topology;
            const bool hit=callbacks.sigmoid_lut_cache && callbacks.sigmoid_lut_cache(callbacks.context,false,topology,256,values);
            if (!hit) {
                values=build_sigmoid_lut_2d(topology);
                if (callbacks.sigmoid_lut_cache) callbacks.sigmoid_lut_cache(callbacks.context,true,topology,256,values);
            }
            loaded_lut=std::move(values);
        }
        return *loaded_lut;
    }
    void retain_lut(ZonedInput2D& input) const {
        if (loaded_lut && input.sigmoid) input.sigmoid->lut=*loaded_lut;
    }
};
CaseInput2D region_input(const CaseInput2D& input,const ZoneRegion2D& region,const ZonedInput2D& request) {
    auto result=input;result.geometry.cell_length_mm=region.cell_length_mm;
    result.geometry.wall_thickness_mm=region.wall_thickness_mm;
    if (request.spatial_model)
        result.geometry.solid_conductivity_W_mK=request.spatial_model->solid_conductivity_W_mK;
    return result;
}
PropertyResult sigmoid_air_property(Empirical getter,const InletInput2D& inlet,Records& records) {
    if (const auto range=empirical_range(getter);range.label)
        records.range({"property",range.label},"unbound","unbound","source",range.label,"T","K",
            range.bounds,inlet.temperature_K);
    auto result=empirical(getter,operand(inlet.temperature_K),operand(inlet.pressure_Pa));
    records.floating(result.events);return result;
}
std::array<double,6> sigmoid_boundaries(const SigmoidControls2D& controls,Records& records) {
    std::array<std::uint32_t,property_event_count> events{};PropertyArithmetic arithmetic(events);
    const double inlet=controls.inlet_transition,outlet=controls.outlet_transition;
    const auto dy_in=arithmetic.divide(inlet,3.),dy_out=arithmetic.divide(outlet,3.);
    std::array<double,6> result{{dy_in,arithmetic.multiply(2.,dy_in),inlet,arithmetic.subtract(1.,outlet),0.,0.}};
    const auto fourth=arithmetic.subtract(1.,outlet);
    result[4]=arithmetic.add(fourth,dy_out);
    const auto fifth=arithmetic.subtract(1.,outlet),twice_out=arithmetic.multiply(2.,dy_out);
    result[5]=arithmetic.add(fifth,twice_out);
    records.floating(events);return result;
}
void spatial_log(const PreparedZonedCase2D& output,const PhysicalGrid2D& grid,Records& records) {
    std::string message;
    if (output.kind==2) message="[ZONE] Continuous Sigmoid field ("+
        std::to_string(grid.nx)+"x"+std::to_string(grid.ny)+")";
    else if (output.kind) message="[ZONE] Grid "+std::to_string(output.regions.size())+" cells (discrete)";
    else message="[ZONE] "+std::to_string(output.regions.size())+" zones along "+(output.axis?"y":"x");
    records.emit({PreparationEventKind::log,logger,std::move(message)});
}
void sigmoid_geometry(PreparedZonedCase2D& output,const ZonedInput2D& request,const PhysicalGrid2D& grid,
                      bool physical,Records& records,const SigmoidLUT2D& lut) {
    auto& prepared=output.prepared;const auto& input=prepared.input;
    const auto& sigmoid=*request.sigmoid;const auto& controls=sigmoid.controls;
    if (controls.decision_mm.size()<36)
        throw std::invalid_argument("sigmoid controls require at least 36 interleaved L/t values");
    const auto x=g::sigmoid_centres(grid.nx,input.grid.length_m,physical?&grid.dx:nullptr);
    const auto y=g::sigmoid_centres(grid.ny,input.grid.height_m,physical?&grid.dy:nullptr);
    const auto cells=count(grid.nx,grid.ny);
    std::vector<double> xf(cells),yf(cells);
    for (std::size_t i=0;i<grid.nx;++i) for (std::size_t j=0;j<grid.ny;++j) {
        xf[i*grid.ny+j]=x[i];yf[i*grid.ny+j]=y[j];
    }
    for (std::size_t field=0;field<2;++field) {
        std::array<double,9> inlet_values,outlet_values;
        for (std::size_t i=0;i<9;++i) {
            inlet_values[i]=controls.decision_mm[2*i+field];
            outlet_values[i]=controls.decision_mm[18+2*i+field];
        }
        const double uniform=field?input.geometry.wall_thickness_mm:input.geometry.cell_length_mm;
        const auto boundaries=sigmoid_boundaries(controls,records);
        auto sampled=fields::sigmoid_field(xf.data(),yf.data(),cells,
            inlet_values,outlet_values,uniform,boundaries,.05,.02);
        auto& values=field?prepared.wall_thickness:prepared.cell_length;
        values=std::move(sampled.values);
    }
    const std::array<double,2> cell_limits{{df_data::df_L_nodes.front(),df_data::df_L_nodes.back()}};
    const std::array<double,2> wall_limits{{df_data::df_t_nodes.front(),df_data::df_t_nodes.back()}};
    const bool allow=request.spatial_model?request.spatial_model->allow_geometry_extrapolation:prepared.options.allow_extrapolation;
    if (!allow) {
        prepared.cell_length=fields::clip_values(prepared.cell_length.data(),cells,
            cell_limits[0],cell_limits[1]).values;
        prepared.wall_thickness=fields::clip_values(prepared.wall_thickness.data(),cells,
            wall_limits[0],wall_limits[1]).values;
    } else {
        const auto extrema=[](const std::vector<double>& values) {
            if (std::any_of(values.begin(),values.end(),[](double value){return std::isnan(value);}))
                return std::array<double,2>{{NAN,NAN}};
            const auto pair=std::minmax_element(values.begin(),values.end());
            return std::array<double,2>{{*pair.first,*pair.second}};
        };
        const auto lengths=extrema(prepared.cell_length),walls=extrema(prepared.wall_thickness);
        if (lengths[0]<cell_limits[0] || lengths[1]>cell_limits[1] || walls[0]<wall_limits[0] || walls[1]>wall_limits[1])
            records.emit({PreparationEventKind::warning,"","[geometry extrap] L=["+fixed(lengths[0],2)+","+
                fixed(lengths[1],2)+"]mm t=["+fixed(walls[0],3)+","+fixed(walls[1],3)+"]mm outside fit L("+
                decimal(cell_limits[0])+", "+decimal(cell_limits[1])+") / t("+decimal(wall_limits[0])+", "+
                decimal(wall_limits[1])+"); geometry LUT extrapolated."});
    }
    if (lut.area_density.size()!=lut.porosity.size()) throw std::invalid_argument("incorrect LUT extent or path");
    const auto sampled=fields::sample_lut({lut.cell_mm.data(),lut.wall_mm.data(),lut.porosity.data(),lut.area_density.data(),
        lut.cell_mm.size(),lut.wall_mm.size(),lut.porosity.size(),lut.porosity_fast,lut.area_fast},
        prepared.cell_length.data(),prepared.wall_thickness.data(),cells);
    output.zone_id.assign(cells,0);prepared.total_porosity.resize(cells);prepared.solid_conductivity.resize(cells);
    prepared.hydraulic_radius.resize(cells);prepared.area_density.resize(cells);prepared.hydraulic_diameter.resize(cells);
    output.design_area_density.resize(cells);
    for (std::size_t i=0;i<cells;++i) {
        const auto value=geometry::lut_geometry(geometry::calibration(input.geometry.topology).solid_tortuosity,
            sampled[0][i],sampled[1][i],input.geometry.solid_conductivity_W_mK,prepared.options.chi_override);
        prepared.total_porosity[i]=value.material.geometry.epsilon;
        prepared.solid_conductivity[i]=value.material.solid_conductivity;
        prepared.hydraulic_radius[i]=value.hydraulic_radius;
        prepared.area_density[i]=output.design_area_density[i]=value.material.geometry.area_density;
        prepared.hydraulic_diameter[i]=value.hydraulic_radius*2.;
    }
}
void sigmoid_properties(PreparedZonedCase2D& output,const PhysicalGrid2D& grid,Records& records) {
    auto& prepared=output.prepared;const auto& input=prepared.input;const auto cells=count(grid.nx,grid.ny);
    std::vector<double> pore_porosity(cells),diameter_mm(cells);
    for (std::size_t i=0;i<cells;++i) {
        pore_porosity[i]=prepared.total_porosity[i]*.5;
        diameter_mm[i]=prepared.hydraulic_diameter[i]*1000.;
    }
    const auto field=[](const std::vector<double>& values) {return PropertyInput{{values.data(),values.size()}};};
    std::array<PropertyResult,2> conductivity,viscosity,density,re,nu;
    for (std::size_t i=0;i<2;++i) {
        const auto& inlet=input.sides[i];
        conductivity[i]=sigmoid_air_property(Empirical::air_conductivity,inlet,records);
        viscosity[i]=sigmoid_air_property(Empirical::air_viscosity,inlet,records);
        density[i]=sigmoid_air_property(Empirical::air_density,inlet,records);
    }
    const auto broadcast=[&](PropertyResult& value) {
        value.values.resize(cells,value.values.front());
        return PropertyInput{{value.values.data(),cells}};
    };
    for (std::size_t i=0;i<2;++i) {
        const std::vector<double> speeds(cells,input.sides[i].velocity_m_s);
        const auto rho=broadcast(density[i]),mu=broadcast(viscosity[i]);
        re[i]=reynolds(rho,field(speeds),field(prepared.hydraulic_diameter),mu);
        records.floating(re[i].events);
        re[i].values=fields::clip_values(re[i].values.data(),cells,10.,INFINITY).values;
    }
    const std::vector<double> floors(cells,10.),prandtl_values(cells,data::pr_air);
    for (std::size_t i=0;i<2;++i) {
        std::array<double,4> extrema{};
        auto values=nu_inputs(NuRoute::air_vector,field(re[i].values),{}, {}, {},field(floors),extrema);
        records.floating(values.events);
        records.range({"nu","air",topology_name(input.geometry.topology)},"unbound","unbound","source",
            "[Nu extrap] "+std::string(topology_name(input.geometry.topology)),"Re","-",data::air_nu_re_range,
            re[i].values,{grid.nx,grid.ny});
        nu[i]=nusselt(NuRoute::air_vector,input.geometry.topology,field(values.values),field(prandtl_values),
            field(prepared.cell_length),field(diameter_mm),1.);
        records.floating(nu[i].events);
    }
    for (std::size_t i=0;i<2;++i) {
        const auto conductivity_field=broadcast(conductivity[i]);
        auto transfer=inlet_transfer(field(nu[i].values),conductivity_field,
            field(prepared.hydraulic_diameter),field(prepared.area_density),field(pore_porosity));
        for (const auto& value:transfer) records.floating(value.events);
        output.volumetric_transfer[i]=std::move(transfer[1].values);
        prepared.fluid_conductivity[i]=std::move(transfer[2].values);
    }
    spatial_log(output,grid,records);
}
void take_spatial_geometry(PreparedZonedCase2D& output,PreparedZonedCase2D& geometry) {
    auto& target=output.prepared;auto& source=geometry.prepared;
    for (auto member:{&PreparedCase2D::cell_length,&PreparedCase2D::wall_thickness,
                     &PreparedCase2D::total_porosity,&PreparedCase2D::solid_conductivity,
                     &PreparedCase2D::hydraulic_radius,&PreparedCase2D::area_density,&PreparedCase2D::hydraulic_diameter})
        (target.*member).swap(source.*member);
    output.zone_id.swap(geometry.zone_id);output.design_area_density.swap(geometry.design_area_density);
}
void sigmoid_fields(PreparedZonedCase2D& output,const ZonedInput2D& request,const PhysicalGrid2D& grid,
                    bool physical,Records& records,ZonedCache& cache,PreparedZonedCase2D* retained=nullptr) {
    if (retained) {
        take_spatial_geometry(output,*retained);
        for (const auto& event:retained->prepared.evidence.events) records.emit(event);
    } else sigmoid_geometry(output,request,grid,physical,records,cache.lut(request));
    sigmoid_properties(output,grid,records);
}
void zoned_geometry(PreparedZonedCase2D& output,const ZonedInput2D& request,const PhysicalGrid2D& grid,
                    bool physical,ZonedCache& cache,bool assign_first=false) {
    auto& prepared=output.prepared;const auto& input=prepared.input;
    std::vector<zones::Bounds> bounds;bounds.reserve(output.regions.size());
    for (const auto& zone:output.regions) bounds.push_back(zone.region.bounds);
    if (!assign_first) for (auto& zone:output.regions)
        zone.geometry=cache.material(region_input(input,zone.region,request),prepared.options);
    output.zone_id=zones::assign(request.kind,grid.nx,grid.ny,static_cast<int>(request.axis),
        request.axis?input.grid.height_m:input.grid.length_m,bounds,
        physical?&grid.dx:nullptr,physical?&grid.dy:nullptr);
    if (assign_first) for (auto& zone:output.regions)
        zone.geometry=cache.material(region_input(input,zone.region,request),prepared.options);
    const auto cells=count(grid.nx,grid.ny);
    prepared.cell_length.resize(cells);prepared.wall_thickness.resize(cells);prepared.total_porosity.resize(cells);
    prepared.solid_conductivity.resize(cells);prepared.hydraulic_radius.resize(cells);prepared.area_density.resize(cells);
    prepared.hydraulic_diameter.resize(cells);output.design_area_density.resize(cells);
    for (std::size_t i=0;i<cells;++i) {
        const auto index=static_cast<std::size_t>(output.zone_id[i]);const auto& zone=output.regions[index];
        const auto& geometry=zone.geometry.geometry;
        prepared.cell_length[i]=zone.region.cell_length_mm;prepared.wall_thickness[i]=zone.region.wall_thickness_mm;
        prepared.total_porosity[i]=geometry.epsilon;prepared.solid_conductivity[i]=zone.geometry.solid_conductivity;
        prepared.hydraulic_radius[i]=geometry::hydraulic_radius(geometry.hydraulic_diameter);
        prepared.area_density[i]=geometry.area_density;output.design_area_density[i]=geometry.area_density;
        prepared.hydraulic_diameter[i]=geometry.hydraulic_diameter;
    }
}
void zoned_fields(PreparedZonedCase2D& output,const ZonedInput2D& request,const PhysicalGrid2D& grid,
                  bool physical,ZonedCache& cache,Records& records,PreparedZonedCase2D* retained=nullptr) {
    auto& prepared=output.prepared;const auto& input=prepared.input;
    // Each zone computes A then B before the geometry-only scatter.
    for (auto current=output.regions.begin();current!=output.regions.end();++current) {
        auto& zone=*current;
        const auto previous=request.kind?std::find_if(output.regions.begin(),current,[&](const auto& item) {
            return item.region.cell_length_mm==zone.region.cell_length_mm
                && item.region.wall_thickness_mm==zone.region.wall_thickness_mm;
        }):current;
        if (previous!=current) {
            zone.properties=previous->properties;zone.property_geometry=previous->property_geometry;continue;
        }
        const auto probe=region_input(input,zone.region,request);
        for (std::size_t side=0;side<2;++side) {
            const auto cached=cache.properties(probe,side,false,prepared.options,records);
            zone.properties[side]=cached.properties;zone.property_geometry[side]=cached.geometry;
        }
    }
    if (retained) {
        for (auto& zone:output.regions) zone.geometry=cache.material(region_input(input,zone.region,request),prepared.options);
        take_spatial_geometry(output,*retained);
    } else zoned_geometry(output,request,grid,physical,cache);
    std::array<std::vector<double>,2> transfer;
    for (std::size_t side=0;side<2;++side) for (const auto& zone:output.regions) {
        const auto result=volumetric_transfer(operand(zone.properties[side].surface_transfer_W_m2K),
            operand(zone.property_geometry[side].area_density));
        records.floating(result.events);transfer[side].push_back(result.values.front());
    }
    const auto cells=count(grid.nx,grid.ny);
    for (std::size_t side=0;side<2;++side) {
        prepared.fluid_conductivity[side].resize(cells);output.volumetric_transfer[side].resize(cells);
        for (std::size_t i=0;i<cells;++i) {
            const auto index=static_cast<std::size_t>(output.zone_id[i]);
            prepared.fluid_conductivity[side][i]=output.regions[index].properties[side].fluid_conductivity_W_mK;
            output.volumetric_transfer[side][i]=transfer[side][index];
        }
    }
    spatial_log(output,grid,records);
    for (auto* field:{&prepared.fluid_conductivity[0],&prepared.fluid_conductivity[1],&prepared.solid_conductivity,
                     &output.volumetric_transfer[0],&output.volumetric_transfer[1],&prepared.total_porosity}) {
        if (retained && (field==&prepared.solid_conductivity || field==&prepared.total_porosity)) continue;
        *field=zones::gaussian_sigma2(*field,grid.nx,grid.ny);
    }
}

void validate_zoned_request(const ZonedInput2D& request,const PreparationCallbacks& callbacks) {
    validate_zone_bounds(request);
    if (request.spatial_model) positive(request.spatial_model->solid_conductivity_W_mK,"spatial.solid_conductivity_W_mK");
    if (request.sigmoid && request.kind!=1)
        throw std::invalid_argument("sigmoid preparation requires grid zones");
    if (request.input.geometry_mode!=2 || request.input.continuous)
        throw std::invalid_argument("native zoned preparation requires geometry_mode=2 and raw regions");
    if (callbacks.validate_host_input || callbacks.geometry_cache || callbacks.inlet_cache
        || callbacks.observe_range || callbacks.observe_notice) {
        if (!callbacks.geometry_cache_at || !callbacks.inlet_cache_at)
            throw std::invalid_argument("native zoned preparation currently accepts event callbacks only");
    }
}
void require_spatial_air(const CaseInput2D& input) {
    if (input.sides[0].fluid==Fluid::air && input.sides[1].fluid==Fluid::air) return;
    throw PreparationError(1,std::string("Zoned 2D compute supports air only (fluid_A='")+fluid_name(input.sides[0].fluid)+
        "', fluid_B='"+fluid_name(input.sides[1].fluid)+"'); the zone property builders would silently use "
        "air properties for a non-air side. Disable zones or run a uniform (non-zoned) case for water.",4);
}
PreparedZonedCase2D spatial_output(const ZonedInput2D& request,const CaseInput2D& input,
                                  const PreparationOptions& options) {
    PreparedZonedCase2D output;output.prepared.input=input;output.prepared.input.geometry_mode=2;
    output.prepared.options=options;output.kind=request.sigmoid?2:request.kind;output.axis=request.axis;
    if (request.sigmoid) output.sigmoid=request.sigmoid->controls;
    return output;
}
void spatial_regions(PreparedZonedCase2D& output,const ZonedInput2D& request) {
    auto regions=request.regions;if (!request.kind) sort_stripes(regions);
    if (!request.sigmoid) for (const auto& region:regions) output.regions.push_back({region,{},{},{}});
}
PreparedZonedCase2D prepare_zoned_case(const ZonedInput2D& request,const PreparationOptions& options,
                                     const PreparationCallbacks& callbacks,ZonedCache& cache,PreparedZonedCase2D* retained=nullptr) {
    FloatingEnvironment floating_environment;
    validate_zoned_request(request,callbacks);
    auto input=request.input;input.geometry_mode=0;validate_nu(input.sco2_nu);
    const auto inlets=validate(input,input.offset_scope?CaseScope::offset_v10:retained?CaseScope::uniform_mass_v3:CaseScope::air_cfd_v1);input.sides=inlets;
    if (input.offset_scope && input.df_mode)
        throw std::invalid_argument(experimental_layout_error);
    auto output=spatial_output(request,input,options);auto& prepared=output.prepared;
    Records records{prepared.evidence,callbacks,{},{}};
    nominal_grid_steps(input,records);
    if (callbacks.validate_host_input) callbacks.validate_host_input(callbacks.context,1,2);
    prepared.uniform_geometry=cache.material(input,options);
    preflight(input,options,prepared.uniform_geometry.geometry,inlets,records);
    if (input.offset_scope) require_spatial_air(input);
    if (callbacks.validate_host_input) callbacks.validate_host_input(callbacks.context,4,2);
    spatial_regions(output,request);
    PhysicalGrid2D requested;requested.nx=input.grid.requested_nx;requested.ny=input.grid.requested_ny;
    if (request.sigmoid) sigmoid_fields(output,request,requested,false,records,cache);
    else zoned_fields(output,request,requested,false,cache,records);
    if (retained) prepared.grid=std::move(retained->prepared.grid);
    else {
        if (callbacks.validate_grid) callbacks.validate_grid(callbacks.context);
        prepared.grid=physical_grid(input.grid,inlets,true);record_grid(input,prepared.grid,records);
    }
    if (request.sigmoid) sigmoid_fields(output,request,prepared.grid,true,records,cache,retained);
    else zoned_fields(output,request,prepared.grid,true,cache,records,retained);
    output.design_pore_porosity=prepared.total_porosity;
    for (auto& value:output.design_pore_porosity) value*=.5;
    const auto topology=static_cast<std::uint32_t>(input.geometry.topology);
    const auto base=fixed_df(topology,input.geometry.cell_length_mm,input.geometry.wall_thickness_mm);
    const auto& grid=prepared.grid;
    for (std::size_t i=0;i<2;++i) {
        auto& side=prepared.sides[i];side.inlet=inlets[i];prepare_ports(grid,side);
        const auto rows=df_project_rows(grid.nx,grid.ny,{prepared.cell_length.data(),prepared.cell_length.size()},
            {prepared.wall_thickness.data(),prepared.wall_thickness.size()},false,false,
            static_cast<std::uint32_t>(side.inlet.port.direction),side.stream_widths.size(),
            {grid.dx.data(),grid.dx.size()},{grid.dy.data(),grid.dy.size()},
            {side.stream_widths.data(),side.stream_widths.size()});
        for (std::size_t j=0;j<rows.lengths.size();++j) {
            auto probe=input;probe.geometry.cell_length_mm=rows.lengths[j];probe.geometry.wall_thickness_mm=rows.walls[j];
            cache.material(probe,options);
        }
        const auto drag=fixed_df_batch(topology,{rows.lengths.data(),rows.lengths.size()},{rows.walls.data(),rows.walls.size()});
        side.seed_permeability_m2=base.K;side.seed_forchheimer_per_m=base.cF;
        for (const auto value:drag) {side.row_permeability.push_back(value.K);side.row_forchheimer.push_back(value.cF);}
        auto& evidence=side.drag_evidence;evidence.campaign="water-sco2-cfd-fixed-v2";evidence.scope="CFD-smooth-wall";
        evidence.base_permeability=evidence.applied_permeability=df_summary(
            {side.row_permeability.data(),side.row_permeability.size()},side.row_permeability.size()==1);
        evidence.base_forchheimer=evidence.applied_forchheimer=df_summary(
            {side.row_forchheimer.data(),side.row_forchheimer.size()},side.row_forchheimer.size()==1);
    }
    // Thermal geometry recomputes float64 fields; design smoothing stays separate.
    cache.material(input,options);
    const auto thermal=geometry::standard_material_geometry_batch(geometry_index(input.geometry.topology),
        geometry::calibration(input.geometry.topology),{prepared.cell_length.data(),prepared.cell_length.size()},
        {prepared.wall_thickness.data(),prepared.wall_thickness.size()},input.geometry.solid_conductivity_W_mK,options.chi_override);
    for (std::size_t i=0;i<thermal.size();++i) {
        output.thermal_porosity.push_back(thermal[i].geometry.epsilon);
        prepared.area_density[i]=thermal[i].geometry.area_density;
        prepared.hydraulic_diameter[i]=thermal[i].geometry.hydraulic_diameter;
    }
    prepare_thermal_sides(prepared,input);
    for (std::size_t i=0;i<2;++i) {
        const auto cached=cache.properties(input,i,true,options,records);
        prepared.sides[i].properties=cached.properties;
    }
    prepared.uniform_geometry=cache.material(input,options);
    prepared.hydraulic_radius_m=geometry::hydraulic_radius(prepared.uniform_geometry.geometry.hydraulic_diameter);
    prepared.cell_length_m=input.geometry.cell_length_mm*1e-3;
    prepared.wall_thickness_m=input.geometry.wall_thickness_mm*1e-3;
    for (auto& value:prepared.cell_length) value*=1e-3;
    for (auto& value:prepared.wall_thickness) value*=1e-3;
    model_evidence(input,prepared.evidence);
    const std::vector<std::size_t> shape{grid.nx,grid.ny};
    for (std::size_t field=0;field<2;++field) {
        auto values=field?prepared.wall_thickness:prepared.cell_length;for(auto& value:values)value*=1e3;
        records.range({"geometry",field?"t_field_m":"L_field_m"},"shared","prepared-geometry","physical-cell",
            "fixed geometry domain",field?"wall thickness":"cell length","mm",
            field?std::array<double,2>{df_data::df_t_nodes.front(),df_data::df_t_nodes.back()}:
                  std::array<double,2>{df_data::df_L_nodes.front(),df_data::df_L_nodes.back()},values,shape);
    }
    finish_warnings(records);return output;
}


void prepare_capacities(const CaseInput2D& input,const PhysicalGrid2D& grid,
    const std::array<PreparedSide2D,2>& sides,double uniform_epsilon,const std::vector<double>* spatial_epsilon,
    Records& records,InletFlow2D& flow) {
    std::array<double,2> densities;
    for (std::size_t i=0;i<2;++i)
        densities[i]=property(0,sides[i].inlet,"unbound","unbound",records);
    for (std::size_t i=0;i<2;++i) {
        if (!input.physical_depth_m || !std::isfinite(*input.physical_depth_m) || *input.physical_depth_m<=0.)
            throw std::invalid_argument("2D total mass flow requires a positive physical Lz_m");
        if (input.geometry.delta_levelset!=0.)
            throw std::invalid_argument("2D fixed-flow optimization currently requires delta_levelset=0");
        const auto& side=sides[i];
        std::vector<double> epsilon(side.cross_widths.size(),uniform_epsilon);
        if (spatial_epsilon) {
            const auto direction=side.inlet.port.direction;
            for (std::size_t j=0;j<epsilon.size();++j) {
                const auto index=direction==0?j:direction==1?(grid.nx-1)*grid.ny+j:
                    direction==2?j*grid.ny:j*grid.ny+grid.ny-1;
                epsilon[j]=(*spatial_epsilon)[index];
            }
        }
        const auto field=[](const std::vector<double>& values) {return FlowValues{values.data(),values.size()};};
        flow.capacities[i]=inlet_capacity_2d(field(epsilon),field(side.inlet_profile),field(side.inlet_geometry),
            field(side.cross_widths),densities[i],*input.physical_depth_m);
        if (!std::isfinite(flow.capacities[i]) || flow.capacities[i]<=0.)
            throw std::invalid_argument("side "+std::string(i?"B":"A")+
                ": inlet density times open pore area must be finite and positive");
    }
    flow.have_capacities=true;
}

InletGeometry2D prepare_inlet_geometry(const CaseInput2D& input,
    const PreparationOptions& options,const PreparationCallbacks& callbacks,InletFlow2D& flow) {
    const auto inlets=validate(input,flow_scope(input),true);
    Records records{flow.evidence,callbacks,{},{}};nominal_grid_steps(input,records);
    if (callbacks.validate_host_input) callbacks.validate_host_input(callbacks.context,1,2);
    InletGeometry2D output{};output.material=material_geometry(input,options,callbacks);
    if (callbacks.validate_grid) callbacks.validate_grid(callbacks.context);
    output.grid=physical_grid(input.grid,inlets);
    record_grid(input,output.grid,records);
    for (std::size_t i=0;i<2;++i) {output.sides[i].inlet=inlets[i];prepare_ports(output.grid,output.sides[i]);}
    if (input.continuous) output.local=local_geometry(input,output.grid,options,records);
    prepare_capacities(input,output.grid,output.sides,output.material.geometry.epsilon,
        output.local?&output.local->epsilon:nullptr,records,flow);
    finish_warnings(records);return output;
}

std::array<std::optional<double>,2> flow_targets(const InletFlowRequest2D& request,CaseInput2D& input) {
    input=request.input;
    if (request.explicit_targets) {
        if (!input.physical_depth_m || !std::isfinite(*input.physical_depth_m) || *input.physical_depth_m<=0.)
            throw std::invalid_argument("2D total mass flow requires a positive physical Lz_m");
        for (std::size_t i=0;i<2;++i) {
            const auto target=(*request.explicit_targets)[i];
            if (!std::isfinite(target) || target<=0.)
                throw std::invalid_argument("mass_flow_"+std::string(i?"B":"A")+"_kg_s must be finite and positive");
            input.sides[i].mass_flow_kg_s.reset();
        }
        return {(*request.explicit_targets)[0],(*request.explicit_targets)[1]};
    }
    return {input.sides[0].mass_flow_kg_s,input.sides[1].mass_flow_kg_s};
}

void resolve_speeds(const std::array<std::optional<double>,2>& targets,
                    InletFlow2D& flow,bool spatial=false) {
    for (std::size_t i=0;i<2;++i) {
        auto& inlet=flow.input.sides[i];
        if (targets[i]) {
            flow.speeds[i]=inlet_speed(*targets[i],flow.capacities[i]);
            inlet.velocity_m_s=flow.speeds[i];
        } else flow.speeds[i]=inlet.velocity_m_s;
    }
    if (spatial && flow.input.df_mode) {
        for (std::size_t side=0;side<2;++side)
            positive(flow.input.sides[side].velocity_m_s,std::string("fluid_")+(side?"B":"A")+".u_mps");
        throw std::invalid_argument(experimental_layout_error);
    }
    validate(flow.input,flow_scope(flow.input));
}
InletFlowRequest2D spatial_flow_request(const ZonedFlowRequest2D& source) {
    InletFlowRequest2D output{source.input.input,source.explicit_targets};
    output.input.geometry_mode=0;return output;
}
PreparedZonedCase2D prepare_spatial_inlet_geometry(const ZonedInput2D& request,
    const PreparationOptions& options,const PreparationCallbacks& callbacks,ZonedCache& cache,InletFlow2D& flow) {
    validate_zoned_request(request,callbacks);
    auto input=request.input;input.geometry_mode=0;
    const auto inlets=validate(input,CaseScope::uniform_mass_v3,true);input.sides=inlets;
    if (input.df_mode && !request.spatial_model)
        throw std::invalid_argument("native 2D preparation currently requires df_mode='cfd_smooth'");
    if (!input.offset_scope) for (const auto& side:inlets) if (side.fluid!=Fluid::air)
        throw std::invalid_argument("native 2D preparation currently supports air/air only");
    Records records{flow.evidence,callbacks,{},{}};nominal_grid_steps(input,records);
    auto output=spatial_output(request,input,options);auto& prepared=output.prepared;
    if (callbacks.validate_host_input) callbacks.validate_host_input(callbacks.context,1,2);
    prepared.uniform_geometry=cache.material(input,options);
    if (callbacks.validate_grid) callbacks.validate_grid(callbacks.context);
    prepared.grid=physical_grid(input.grid,inlets,true);record_grid(input,prepared.grid,records);
    if (input.offset_scope) require_spatial_air(input);
    if (callbacks.validate_host_input) callbacks.validate_host_input(callbacks.context,4,2);
    spatial_regions(output,request);
    Records geometry_records{prepared.evidence,callbacks,{},{}};
    if (request.sigmoid) sigmoid_geometry(output,request,prepared.grid,true,geometry_records,cache.lut(request));
    else zoned_geometry(output,request,prepared.grid,true,cache,true);
    records.merge(prepared.evidence);
    spatial_log(output,prepared.grid,records);
    if (!request.sigmoid) for (auto* field:{&prepared.solid_conductivity,&prepared.total_porosity})
        *field=zones::gaussian_sigma2(*field,prepared.grid.nx,prepared.grid.ny);
    for (std::size_t i=0;i<2;++i) {prepared.sides[i].inlet=inlets[i];prepare_ports(prepared.grid,prepared.sides[i]);}
    prepare_capacities(input,prepared.grid,prepared.sides,prepared.uniform_geometry.geometry.epsilon,
        &prepared.total_porosity,records,flow);
    finish_warnings(records);return output;
}
void resolved_spatial_input(ZonedInletFlow2D& output) {
    output.flow.input.geometry_mode=2;output.input.input=output.flow.input;
}

}  // namespace

InletQueryResult query_inlet_properties(const InletPropertyQuery& input,const PreparationCallbacks& callbacks) {
    FloatingEnvironment floating_environment;
    topology_name(input.inlet.geometry.topology);fluid_name(input.inlet.fluid);
    PreparationEvidence evidence;Records records{evidence,callbacks,{},{}};
    return inlet_property_values(input,records,"unbound","unbound","source",true);
}

SigmoidLUT2D build_sigmoid_lut_2d(Topology topology,std::size_t cell_nodes,
    std::size_t wall_nodes,std::size_t resolution) {
    FloatingEnvironment floating_environment;
    const auto cells=count(cell_nodes,wall_nodes);
    auto output=sigmoid_lut_axes(cell_nodes,wall_nodes);
    output.porosity.reserve(cells);output.area_density.reserve(cells);
    const auto index=geometry::PhiIndex::from_topology(topology,resolution);
    const auto model=geometry::calibration(topology);
    for (const auto cell:output.cell_mm) for (const auto wall:output.wall_mm) {
        const auto value=geometry::raw_geometry(index,model,cell,wall);
        output.porosity.push_back(value.epsilon);output.area_density.push_back(value.area_density);
    }
    return output;
}

PreparedCase2D prepare_case_2d(const CaseInput2D& input,const PreparationOptions& options,
    const PreparationCallbacks& callbacks,CaseScope scope) {
    return prepare_case(input,options,callbacks,scope);
}

InletFlow2D prepare_inlet_mass_capacities_2d(const CaseInput2D& input,
    const PreparationOptions& options,const PreparationCallbacks& callbacks) {
    FloatingEnvironment floating_environment;
    InletFlow2D output;output.input=input;
    prepare_inlet_geometry(input,options,callbacks,output);
    return output;
}

InletFlow2D resolve_inlet_flow_2d(const InletFlowRequest2D& request,
    const PreparationOptions& options,const PreparationCallbacks& callbacks) {
    FloatingEnvironment floating_environment;
    InletFlow2D output;const auto targets=flow_targets(request,output.input);
    if (!targets[0] && !targets[1]) return output;
    prepare_inlet_geometry(output.input,options,callbacks,output);
    resolve_speeds(targets,output);return output;
}

PreparedFlowCase2D prepare_flow_case_2d(const InletFlowRequest2D& request,
    const PreparationOptions& options,const PreparationCallbacks& callbacks) {
    FloatingEnvironment floating_environment;
    PreparedFlowCase2D output;const auto targets=flow_targets(request,output.flow.input);
    if (!targets[0] && !targets[1]) {
        output.prepared=prepare_case(output.flow.input,options,callbacks,flow_scope(output.flow.input));
        return output;
    }
    const auto inlet_geometry=prepare_inlet_geometry(output.flow.input,options,callbacks,output.flow);
    resolve_speeds(targets,output.flow);
    output.prepared=prepare_case(output.flow.input,options,callbacks,flow_scope(output.flow.input),&inlet_geometry);
    return output;
}

PreparedZonedCase2D prepare_zoned_case_2d(const ZonedInput2D& input,const PreparationOptions& options,
    const PreparationCallbacks& callbacks) {
    ZonedCache cache{callbacks,{},{},{}};return prepare_zoned_case(input,options,callbacks,cache);
}

ZonedInletFlow2D prepare_zoned_inlet_mass_capacities_2d(const ZonedInput2D& input,
    const PreparationOptions& options,const PreparationCallbacks& callbacks) {
    FloatingEnvironment floating_environment;
    ZonedInletFlow2D output;output.input=input;output.flow.input=input.input;ZonedCache cache{callbacks,{},{},{}};
    prepare_spatial_inlet_geometry(input,options,callbacks,cache,output.flow);
    cache.retain_lut(output.input);return output;
}

ZonedInletFlow2D resolve_zoned_inlet_flow_2d(const ZonedFlowRequest2D& request,
    const PreparationOptions& options,const PreparationCallbacks& callbacks) {
    FloatingEnvironment floating_environment;
    ZonedInletFlow2D output;output.input=request.input;
    const auto flow_request=spatial_flow_request(request);
    const auto targets=flow_targets(flow_request,output.flow.input);
    if (!targets[0] && !targets[1]) {output.flow.input=request.input.input;return output;}
    output.input.input=output.flow.input;output.input.input.geometry_mode=2;
    ZonedCache cache{callbacks,{},{},{}};
    prepare_spatial_inlet_geometry(output.input,options,callbacks,cache,output.flow);
    resolve_speeds(targets,output.flow,request.input.spatial_model.has_value());resolved_spatial_input(output);
    cache.retain_lut(output.input);return output;
}

PreparedZonedFlowCase2D prepare_zoned_flow_case_2d(const ZonedFlowRequest2D& request,
    const PreparationOptions& options,const PreparationCallbacks& callbacks) {
    FloatingEnvironment floating_environment;
    PreparedZonedFlowCase2D output;output.flow.input=request.input;ZonedCache cache{callbacks,{},{},{}};
    const auto flow_request=spatial_flow_request(request);
    const auto targets=flow_targets(flow_request,output.flow.flow.input);
    output.flow.input.input=output.flow.flow.input;output.flow.input.input.geometry_mode=2;
    if (!targets[0] && !targets[1]) {
        resolved_spatial_input(output.flow);
        if (callbacks.validate_host_input) callbacks.validate_host_input(callbacks.context,0,2);
        output.prepared=prepare_zoned_case(output.flow.input,options,callbacks,cache);
        cache.retain_lut(output.flow.input);return output;
    }
    auto geometry=prepare_spatial_inlet_geometry(output.flow.input,options,callbacks,cache,output.flow.flow);
    resolve_speeds(targets,output.flow.flow,request.input.spatial_model.has_value());resolved_spatial_input(output.flow);
    if (callbacks.validate_host_input) callbacks.validate_host_input(callbacks.context,0,2);
    output.prepared=prepare_zoned_case(output.flow.input,options,callbacks,cache,&geometry);
    cache.retain_lut(output.flow.input);return output;
}

namespace {

g::Port checked_port_3d(g::Port port,const GridInput3D& input,const std::string& side) {
    const auto prefix="ComputeConfig.bc_"+side;
    if (!port.active) throw std::invalid_argument("native typed 3D preparation requires both fluid ports");
    const auto cross=input.lengths[first_cross_axis(port.direction)];
    const auto face=full_face(port.ends[0].width.value_or(0.),port.ends[1].width.value_or(0.),cross,prefix);
    if (face) for (auto& end:port.ends) {
        end.center=face->center;
        end.width=face->width;
    }
    if (port.direction<0 || port.direction>5)
        throw std::invalid_argument(prefix+" is invalid: [error] pipe_bad_dir: pipe direction "+
                                    std::to_string(port.direction)+" not in 0..5");
    std::vector<std::string> errors;
    for (std::size_t end=0;end<2;++end) {
        auto& window=port.ends[end];
        window.center=window.center.value_or(0.);window.width=window.width.value_or(0.);
        const double center=*window.center,width=*window.width;
        const std::string name=end?"out":"in";
        if (!std::isfinite(center) || !std::isfinite(width))
            errors.push_back("[error] pipe_"+name+"_invalid: "+name+" centre and width must be finite numbers");
        else if (center-width/2.<0. || center+width/2.>cross)
            errors.push_back("[error] pipe_"+name+"_out_of_domain: "+name+"_ctr ± "+name+"_w/2 = ["+
                significant(center-width/2.,3)+", "+significant(center+width/2.,3)+
                "] m leaves the cross-axis range [0, "+significant(cross,3)+"].");
    }
    const auto cross2=port.direction<4?input.lengths[2]:input.lengths[1];
    for (std::size_t end=0;end<2;++end) {
        const auto& window=port.ends[end];const std::string name=end?"out":"in";
        if (!window.center2 && !window.width2) continue;
        if (!window.center2 || !window.width2) {
            errors.push_back("[error] pipe_"+name+"_z_incomplete: "+name+" second-cross-axis centre and width must be set together");
            continue;
        }
        const double center=*window.center2,width=*window.width2;
        if (!std::isfinite(center) || !std::isfinite(width))
            errors.push_back("[error] pipe_"+name+"_z_invalid: "+name+" second-cross-axis centre and width must be finite numbers");
        else if (width<=0.)
            errors.push_back("[error] pipe_"+name+"_z_w_nonpos: "+name+"_z_w = "+decimal(width)+" must be > 0");
        else if (center-width/2.<0. || center+width/2.>cross2)
            errors.push_back("[error] pipe_"+name+"_z_out_of_domain: "+name+"_z_ctr ± "+name+"_z_w/2 = ["+
                significant(center-width/2.,3)+", "+significant(center+width/2.,3)+"] m leaves "+
                (port.direction<4?"Z":"Y")+"-range [0, "+significant(cross2,3)+"].");
    }
    if (!errors.empty()) {
        std::string text=prefix+" is invalid: ";
        for (std::size_t i=0;i<errors.size();++i) {if (i) text+="; ";text+=errors[i];}
        throw std::invalid_argument(text);
    }
    return port;
}

CaseInput3D validate_3d(CaseInput3D input,CaseScope3D scope,bool allow_mass=false,bool velocities=true) {
    if (input.continuous) {
        if (input.geometry_mode!=1)
            throw std::invalid_argument("native continuous 3D preparation requires geometry_mode=1");
        validate_controls(*input.continuous,input.continuous->nz.value_or(1));
    } else if (scope==CaseScope3D::spatial_v4) {
        if (input.geometry_mode==2) {
            if (input.grid_cells.empty()) throw std::invalid_argument("Enabled grid zones require non-empty grid cells");
            for (std::size_t i=0;i<input.grid_cells.size();++i) for (std::size_t axis=0;axis<2;++axis) {
                const auto& bounds=input.grid_cells[i].bounds;
                const double lower=bounds[2*axis],upper=bounds[2*axis+1];
                if (!std::isfinite(lower) || !std::isfinite(upper) || !(0.<=lower && lower<upper && upper<=1.))
                    throw std::invalid_argument("Zone grid cell "+std::to_string(i+1)+": "+(axis?"y":"x")+
                        " coordinates must be finite and satisfy 0 <= start < end <= 1");
            }
        } else if (input.geometry_mode || !input.grid_cells.empty())
            throw std::invalid_argument("native spatial 3D preparation requires uniform mode 0 or grid mode 2");
    } else if (input.geometry_mode || input.geometry.delta_levelset!=0.)
        throw std::invalid_argument("native 3D preparation currently requires symmetric uniform geometry");
    validate_nu(input.sco2_nu);
    if (input.continuous && input.geometry.delta_levelset!=0.)
        throw std::invalid_argument("Continuous spatial fields require delta_levelset=0");
    if (input.df_mode>1) throw std::invalid_argument("native 3D preparation DF mode must be CFD or experimental");
    if (allow_mass) for (std::size_t i=0;i<2;++i) if (input.sides[i].mass_flow_kg_s)
        positive(*input.sides[i].mass_flow_kg_s,std::string("fluid_")+(i?"B":"A")+".mass_flow_kg_s");
    const char* dimensions[]{"geometry.L_dom_m","geometry.H_dom_m","geometry.Lz_m"};
    for (std::size_t axis=0;axis<2;++axis) positive(input.grid.lengths[axis],dimensions[axis]);
    const auto& model=input.geometry;
    positive(model.cell_length_mm,"geometry.L_cell_mm");
    positive(model.wall_thickness_mm,"geometry.t_wall_mm");
    positive(model.solid_conductivity_W_mK,"geometry.k_s_W_mK");
    positive(input.grid.lengths[2],dimensions[2]);
    for (std::size_t i=0;i<2;++i) {
        const auto& inlet=input.sides[i];const std::string side=i?"B":"A";
        if (inlet.mass_flow_kg_s && !allow_mass)
            throw std::invalid_argument("native 3D preparation currently requires prescribed inlet velocity");
        positive(inlet.temperature_K,"fluid_"+side+".T_in_K");positive(inlet.pressure_Pa,"fluid_"+side+".P_in_Pa");
    }
    for (std::size_t axis=0;axis<3;++axis) if (!input.grid.counts[axis])
        throw std::invalid_argument(std::string("ComputeConfig.solver.N")+static_cast<char>('x'+axis)+"=0 — must be >= 1");
    if (input.grid.counts[2]<2) throw std::invalid_argument("3D preparation requires solver.Nz >= 2");
    for (std::size_t i=0;i<2;++i) input.sides[i].port=checked_port_3d(input.sides[i].port,input.grid,i?"B":"A");
    check_cfd_geometry(input);
    for (std::size_t i=0;i<2;++i) {
        const auto& inlet=input.sides[i];fluid_name(inlet.fluid);
        if (inlet.fluid==Fluid::sco2) check_sco2_inlet(inlet,i);
    }
    if (scope==CaseScope3D::spatial_v4) {
        const bool sco2=std::any_of(input.sides.begin(),input.sides.end(),[](const auto& side) {return side.fluid==Fluid::sco2;});
        if (sco2) check_sco2_geometry(input.geometry_mode==2,model.delta_levelset);
        if (co2_geometry(input)) check_co2_geometry(input.geometry_mode==2,model.delta_levelset);
    }
    if (velocities) for (std::size_t i=0;i<2;++i) positive(input.sides[i].velocity_m_s,std::string("fluid_")+(i?"B":"A")+".u_mps");
    if (velocities && input.df_mode) {
        const double domain[]{input.grid.lengths[0],input.grid.lengths[1],input.grid.lengths[2]};
        validate_experiment_scope(input,input.sides,input.geometry_mode,{domain,3});
    }
    for (std::size_t axis=0;axis<3;++axis) if (input.grid.lengths[axis]>10.) {
        const char* names[]{"L","H","Lz"};
        throw std::invalid_argument(std::string("Domain dimension '")+names[axis]+"'="+
            decimal(input.grid.lengths[axis])+" m exceeds 10.0 m. Likely unit slip — GUI expects meters here, while L_cell and t use millimeters. Re-check input.");
    }
    topology_name(model.topology);
    return input;
}

void water_inlet_3d(const InletInput3D& inlet,std::size_t side,const std::string& where) {
    if (inlet.fluid!=Fluid::water) return;
    try {validate_water_pt({&inlet.temperature_K,1},{&inlet.pressure_Pa,1});}
    catch (const PropertyError& error) {
        const auto& value=error.failure;
        PreparationError failure(error.status,where+" "+(side?"B":"A")+
            ": water index=(), T="+significant(inlet.temperature_K,6)+" K, P_abs="+
            significant(inlet.pressure_Pa,6)+" Pa: "+error.what(),2,static_cast<std::uint32_t>(side),
            value.reason==1?std::vector<PreparationFailureCause>{}:
                std::vector<PreparationFailureCause>{{value.reason==6?2u:1u,error.what()}});
        failure.have_property=true;failure.property={value.reason,value.input,value.index,value.first_t_index,
            value.first_p_index,value.temperature,value.pressure,value.detail,value.fp};
        throw failure;
    }
}

void host_3d(Records& records,std::uint32_t stage) {
    if (records.callbacks.validate_host_input)
        records.callbacks.validate_host_input(records.callbacks.context,stage,2);
}

void physical_grid_3d(PreparedCase3D& output,Records& records) {

    const auto& input=output.input.grid;
    const g::Values lengths(input.lengths.begin(),input.lengths.end());
    const std::vector<g::Port> ports{output.input.sides[0].port,output.input.sides[1].port};
    for (std::size_t axis=0;axis<3;++axis) {
        if (!input.port_wall_refine) {
            host_3d(records,17+static_cast<std::uint32_t>(axis));
            output.widths[axis]=g::uniform(input.counts[axis],lengths[axis]);
        } else {
            const auto knots=unique(g::port_edges(lengths,ports,axis));
            g::Values outer{0.};outer.insert(outer.end(),knots.begin(),knots.end());outer.push_back(lengths[axis]);
            const auto keep=g::aligned_filter(lengths[axis],knots);
            g::Values bulk{0.,lengths[axis]};
            for (std::size_t i=0;i<knots.size();++i) if (keep[i]) bulk.push_back(knots[i]);
            std::size_t minimum=0;
            host_3d(records,17+static_cast<std::uint32_t>(axis));
            output.widths[axis]=g::port_wall_axis(3,input.counts[axis],outer,unique(std::move(bulk)),minimum,axis);
        }
    }
    const auto cells=count(count(output.widths[0].size(),output.widths[1].size()),output.widths[2].size());
    host_3d(records,14);
    if (cells>input.max_cells)
        throw std::invalid_argument("3D grid "+std::to_string(output.widths[0].size())+"x"+
            std::to_string(output.widths[1].size())+"x"+std::to_string(output.widths[2].size())+
            " exceeds the "+std::to_string(input.max_cells)+"-cell cap");
}

void prepare_thermal_sides_3d(PreparedCase3D& output,Records& records) {
    if (records.callbacks.geometry_cache_at)
        material_geometry(output.input,output.options,records.callbacks);

    const auto& model=output.input.geometry;
    if (model.delta_levelset!=0.)
        output.thermal_sides=geometry::asym::prepare_from_index(geometry_index(model.topology),
            geometry::calibration(model.topology),model.cell_length_mm,model.wall_thickness_mm,model.delta_levelset);
    host_3d(records,15);
}

void store_spatial_fields_3d(PreparedCase3D& output,std::vector<double> cell_mm,std::vector<double> wall_mm,Records& records) {
    const auto& model=output.input.geometry;
    prepare_thermal_sides_3d(output,records);
    const auto cells=cell_mm.size();
    output.side_porosity=geometry::asym::split_porosity({output.total_porosity.data(),cells},.5).a;
    const auto drag=fixed_df_batch(static_cast<std::uint32_t>(model.topology),
        {cell_mm.data(),cells},{wall_mm.data(),cells});
    output.permeability.resize(cells);output.forchheimer.resize(cells);
    for (std::size_t i=0;i<cells;++i) {output.permeability[i]=drag[i].K;output.forchheimer[i]=drag[i].cF;}
    output.cell_length.resize(cells);output.wall_thickness.resize(cells);
    for (std::size_t i=0;i<cells;++i) {
        output.cell_length[i]=cell_mm[i]*1e-3;output.wall_thickness[i]=wall_mm[i]*1e-3;
    }
}

void continuous_geometry_3d(PreparedCase3D& output,Records& records) {
    const auto& input=output.input;const auto& controls=*input.continuous;
    const auto nx=output.widths[0].size(),ny=output.widths[1].size(),nz=output.widths[2].size();
    const auto dimension=controls.nz?3u:2u;
    const std::size_t counts[]{controls.nx,controls.ny,controls.nz.value_or(1)};
    const std::size_t sizes[]{nx,ny,nz};
    std::array<std::vector<double>,3> axes,centres;
    for (std::size_t axis=0;axis<dimension;++axis) {
        const auto length=input.grid.lengths[axis];
        auto& nodes=axes[axis];nodes=control_axis(counts[axis],length,&records);
        bool valid=nodes.size()==1?nodes[0]==control_midpoint(length,&records,"control-axis-check-midpoint"):
            nodes.front()==0. && nodes.back()==length;
        for (std::size_t i=0;i<nodes.size();++i)
            valid=valid && std::isfinite(nodes[i]) && (!i || nodes[i]>nodes[i-1]);
        if (!valid)
            throw std::invalid_argument("control axes must increase across the domain, or use its midpoint for one control");
    }
    for (std::size_t axis=0;axis<dimension;++axis) {
        const auto length=input.grid.lengths[axis];const auto& widths=output.widths[axis];
        const double total=0.+tpmshx::detail::contiguous_sum({widths.data(),widths.size()});
        if (!(std::abs(total-length)<=1e-12*length))
            throw std::invalid_argument("cell widths must be finite, positive and cover the field domain");
        centres[axis]=g::continuous_centres(sizes[axis],length,&widths);
    }
    const auto half_y=controls.symmetric_y?controls.ny/2+controls.ny%2:controls.ny;
    const auto half=count(count(controls.nx,half_y),counts[2]);
    std::array<std::vector<double>,2> sampled;
    for (std::size_t field=0;field<2;++field) {
        std::vector<double> values(count(count(controls.nx,controls.ny),counts[2]));
        for (std::size_t i=0;i<controls.nx;++i) for (std::size_t j=0;j<controls.ny;++j)
            for (std::size_t k=0;k<counts[2];++k) {
                const auto source=controls.symmetric_y && j>=half_y?controls.ny-1-j:j;
                values[(i*controls.ny+j)*counts[2]+k]=controls.decision_mm[field*half+(i*half_y+source)*counts[2]+k];
            }
        const auto& limits=field?controls.wall_bounds_mm:controls.cell_bounds_mm;
        if (!controls.nz && controls.nx>1 && controls.ny>1) {
            fields::XYFit fit(axes[0].data(),counts[0],axes[1].data(),counts[1],values.data(),values.size(),
                static_cast<int>(std::min<std::size_t>(controls.order,counts[0]-1)),
                static_cast<int>(std::min<std::size_t>(controls.order,counts[1]-1)));
            sampled[field]=fit.sample(values.data(),values.size(),centres[0].data(),nx,centres[1].data(),ny,limits[0],limits[1]);
        } else {
            const double* nodes[]{axes[0].data(),axes[1].data(),axes[2].data()};
            const double* points[]{centres[0].data(),centres[1].data(),centres[2].data()};
            sampled[field]=fields::sample_tensor(dimension,counts,nodes,values.data(),values.size(),
                static_cast<int>(controls.order),sizes,points,limits[0],limits[1]);
        }
    }
    const auto local_count=sampled[0].size();const auto& model=input.geometry;
    std::array<std::vector<double>,2> thermal;
    for (std::size_t field=0;field<2;++field) {
        thermal[field].resize(local_count);
        for (std::size_t i=0;i<local_count;++i) thermal[field][i]=(sampled[field][i]*1e-3)*1e3;
    }
    std::vector<double> epsilon(local_count),area(local_count),diameter(local_count),thermal_epsilon(local_count);
    if (co2_geometry(input)) {
        const auto table=geometry::Co2GeometryTable::from_generated(model.topology);
        for (std::size_t i=0;i<local_count;++i) {
            auto material=table.evaluate(sampled[0][i],sampled[1][i],model.solid_conductivity_W_mK,output.options.chi_override);
            epsilon[i]=material.geometry.epsilon;
            if (thermal[0][i]!=sampled[0][i] || thermal[1][i]!=sampled[1][i])
                material=table.evaluate(thermal[0][i],thermal[1][i],model.solid_conductivity_W_mK,output.options.chi_override);
            area[i]=material.geometry.area_density;diameter[i]=material.geometry.hydraulic_diameter;
            thermal_epsilon[i]=material.geometry.epsilon;
        }
    } else {
        const auto& index=geometry_index(model.topology);const auto calibration=geometry::calibration(model.topology);
        auto materials=geometry::standard_material_geometry_batch(index,calibration,
            {sampled[0].data(),local_count},{sampled[1].data(),local_count},model.solid_conductivity_W_mK,output.options.chi_override);
        for (std::size_t i=0;i<local_count;++i) epsilon[i]=materials[i].geometry.epsilon;
        materials=geometry::standard_material_geometry_batch(index,calibration,
            {thermal[0].data(),local_count},{thermal[1].data(),local_count},model.solid_conductivity_W_mK,output.options.chi_override);
        for (std::size_t i=0;i<local_count;++i) {
            area[i]=materials[i].geometry.area_density;diameter[i]=materials[i].geometry.hydraulic_diameter;
            thermal_epsilon[i]=materials[i].geometry.epsilon;
        }
    }
    const auto extrude=[&](std::vector<double> values) {
        if (controls.nz) return values;
        std::vector<double> volume(count(values.size(),nz));
        for (std::size_t i=0;i<values.size();++i)
            std::fill_n(volume.begin()+static_cast<std::ptrdiff_t>(i*nz),nz,values[i]);
        return volume;
    };
    auto cell_mm=extrude(std::move(sampled[0])),wall_mm=extrude(std::move(sampled[1]));
    output.total_porosity=extrude(std::move(epsilon));output.area_density=extrude(std::move(area));
    output.hydraulic_diameter=extrude(std::move(diameter));output.thermal_porosity=extrude(std::move(thermal_epsilon));
    store_spatial_fields_3d(output,std::move(cell_mm),std::move(wall_mm),records);
}

void grid_geometry_3d(PreparedCase3D& output,Records& records) {
    const auto& input=output.input;const auto& model=input.geometry;
    const auto nx=output.widths[0].size(),ny=output.widths[1].size(),nz=output.widths[2].size();
    std::vector<zones::Bounds> bounds;bounds.reserve(input.grid_cells.size());
    for (const auto& cell:input.grid_cells) bounds.push_back(cell.bounds);
    const auto ids=zones::assign(2,nx,ny,1,1.,bounds,&output.widths[0],&output.widths[1]);
    host_3d(records,16);
    std::array<std::vector<double>,2> local;
    for (std::size_t field=0;field<2;++field) {
        auto& values=local[field];values.resize(ids.size());
        for (std::size_t i=0;i<ids.size();++i) {
            if (ids[i]<0) values[i]=field?model.wall_thickness_mm:model.cell_length_mm;
            else {
                const auto& cell=input.grid_cells[static_cast<std::size_t>(ids[i])];
                values[i]=field?cell.wall_thickness_mm:cell.cell_length_mm;
            }
        }
        values=zones::gaussian_sigma2(values,nx,ny);
    }
    const auto& index=geometry_index(model.topology);const auto calibration=geometry::calibration(model.topology);
    auto materials=geometry::standard_material_geometry_batch(index,calibration,
        {local[0].data(),ids.size()},{local[1].data(),ids.size()},model.solid_conductivity_W_mK,output.options.chi_override);
    const auto cells=count(ids.size(),nz);
    std::vector<double> cell_mm(cells),wall_mm(cells),thermal_cell(cells),thermal_wall(cells);
    output.total_porosity.resize(cells);
    for (std::size_t i=0;i<ids.size();++i) for (std::size_t k=0;k<nz;++k) {
        const auto j=i*nz+k;cell_mm[j]=local[0][i];wall_mm[j]=local[1][i];
        output.total_porosity[j]=materials[i].geometry.epsilon;
        thermal_cell[j]=(cell_mm[j]*1e-3)*1e3;thermal_wall[j]=(wall_mm[j]*1e-3)*1e3;
    }
    materials=geometry::standard_material_geometry_batch(index,calibration,
        {thermal_cell.data(),cells},{thermal_wall.data(),cells},model.solid_conductivity_W_mK,output.options.chi_override);
    output.area_density.resize(cells);output.hydraulic_diameter.resize(cells);output.thermal_porosity.resize(cells);
    for (std::size_t i=0;i<cells;++i) {
        const auto& geometry=materials[i].geometry;
        output.area_density[i]=geometry.area_density;output.hydraulic_diameter[i]=geometry.hydraulic_diameter;
        output.thermal_porosity[i]=geometry.epsilon;
    }
    store_spatial_fields_3d(output,std::move(cell_mm),std::move(wall_mm),records);
}

void air_spatial_ranges_3d(const PreparedCase3D& output,std::size_t side,Records& records) {
    const auto& input=output.input;const auto& inlet=input.sides[side];
    const auto name=std::string(side?"B":"A");
    const auto mu=property(1,inlet,name,"inlet",records,"scalar-zoned-call");
    property(2,inlet,name,"inlet",records,"scalar-zoned-call");
    const auto rho=property(0,inlet,name,"inlet",records,"scalar-zoned-call");
    property(3,inlet,name,"inlet",records,"scalar-zoned-call");
    PropertyResult re;re.values.reserve(output.hydraulic_diameter.size());
    for (const auto diameter:output.hydraulic_diameter)
        re.values.push_back(reynolds_point(rho,inlet.velocity_m_s,diameter,mu,re.events));
    records.floating(re.events);
    const auto topology=std::string(topology_name(input.geometry.topology));
    const auto limits=re_range(Fluid::air);
    const auto selected=detail::scalar_range_samples(re.values.size(),
        [&](std::size_t index) {return re.values[index];},limits[0],limits[1]);
    for (const auto index:selected)
        records.range({"nu","air",topology},name,"inlet","scalar-zoned-call","[Nu extrap] "+topology,
            "Re","-",limits,re.values[index]);
    records.range({"nu_raw","air",topology},name,"inlet","real-cell(x,y,z)-bulk-Re","[air Nu raw] "+topology,
        "Re","-",re_range(Fluid::air),re.values,{output.widths[0].size(),output.widths[1].size(),output.widths[2].size()});
}

void prepare_geometry_3d(PreparedCase3D& output,Records& records,bool check_speed) {
    const auto& input=output.input;const auto& model=input.geometry;const auto& options=output.options;
    host_3d(records,10);
    output.uniform_geometry=material_geometry(input,options,records.callbacks);
    host_3d(records,11);
    for (std::size_t i=0;i<2;++i) water_inlet_3d(input.sides[i],i,"pipeline inlet");
    host_3d(records,12);
    if (check_speed) preflight(input,options,output.uniform_geometry.geometry,input.sides,records);
    host_3d(records,13);
    physical_grid_3d(output,records);
    if (records.callbacks.geometry_cache_at)
        output.uniform_geometry=material_geometry(input,options,records.callbacks);
    const auto cells=count(count(output.widths[0].size(),output.widths[1].size()),output.widths[2].size());
    const auto& uniform=output.uniform_geometry.geometry;
    if (input.geometry_mode==2 && input.df_mode)
        throw std::invalid_argument("experimental calibration currently requires uniform L/t");
    if (input.continuous) continuous_geometry_3d(output,records);
    else if (input.geometry_mode==2) grid_geometry_3d(output,records);
    else {
        prepare_thermal_sides_3d(output,records);
        output.total_porosity.assign(cells,uniform.epsilon);
        output.side_porosity.assign(cells,uniform.epsilon_a);
        const auto drag=fixed_df_batch(static_cast<std::uint32_t>(model.topology),
            {&model.cell_length_mm,1},{&model.wall_thickness_mm,1}).front();
        output.permeability.assign(cells,drag.K);output.forchheimer.assign(cells,drag.cF);
    }
    if (model.delta_levelset!=0.) {
        auto split=geometry::asym::split_porosity({output.total_porosity.data(),cells},output.thermal_sides.split_a);
        output.side_porosity=std::move(split.a);output.side_b_porosity=std::move(split.b);
    }
    for (std::size_t i=0;i<2;++i) {
        const auto& inlet=input.sides[i];auto& side=output.sides[i];
        side.axes=g::axis_map(inlet.port.direction);
        const auto& cross1=output.widths[static_cast<std::size_t>(side.axes[0])];
        const auto& cross2=output.widths[static_cast<std::size_t>(side.axes[2])];
        side.openings=g::partial_masks(inlet.port,cross1,&cross2,cross2.size());
        water_inlet_3d(inlet,i,"3D prepared inlet");
        constexpr std::array<std::uint32_t,4> order{{0,1,3,2}};
        for (std::size_t j=0;j<order.size();++j)
            side.properties[j]=property(order[j],inlet,"unbound","unbound",records);
    }
    const auto calibration=geometry::calibration(model.topology);
    if (input.continuous || input.geometry_mode==2) {
        output.solid_conductivity=geometry::solid_conductivity(calibration.solid_tortuosity,
            {output.total_porosity.data(),cells},model.solid_conductivity_W_mK,options.chi_override);
    } else {
        output.cell_length.assign(cells,model.cell_length_mm*1e-3);
        output.wall_thickness.assign(cells,model.wall_thickness_mm*1e-3);
        const auto solid=geometry::solid_conductivity(calibration.solid_tortuosity,uniform.epsilon,
            model.solid_conductivity_W_mK,options.chi_override);
        output.solid_conductivity.assign(cells,solid);
    }
}

void air_uniform_ranges_3d(const PreparedCase3D& output,std::size_t side,Records& records) {
    const auto& input=output.input;const auto& inlet=input.sides[side];
    const auto& callbacks=records.callbacks;
    if (!callbacks.inlet_cache_at) {
        inlet_properties(input,inlet,side,output.uniform_geometry,records,false,"scalar-hv-bulk");
        return;
    }
    const PreparationInletKey key{geometry_key(input),inlet.fluid,inlet.velocity_m_s,
        inlet.temperature_K,inlet.pressure_Pa,{},co2_geometry(input)};
    PreparationInletCache cached;
    const bool hit=callbacks.inlet_cache_at(callbacks.context,false,key,cached);
    if (!hit) {
        const auto geometry=material_geometry(input,output.options,callbacks);
        cached.geometry=geometry.geometry;
        Records local{cached.evidence,callbacks,{},{}};
        cached.properties=inlet_properties(input,inlet,side,geometry,local,false,"scalar-hv-bulk");
        for (auto& range:cached.evidence.ranges) {range.side="unbound";range.stage="unbound";range.layout="source";}
        callbacks.inlet_cache_at(callbacks.context,true,key,cached);
    }
    // Public compute applies the current material after either cache outcome.
    geometry::solid_conductivity(geometry::calibration(input.geometry.topology).solid_tortuosity,
        cached.geometry.epsilon,input.geometry.solid_conductivity_W_mK,output.options.chi_override);
    if (hit) cached.evidence.events.clear();
    records.merge(cached.evidence,side?"B":"A","scalar-hv-bulk");
}

void finish_case_3d(PreparedCase3D& output,Records& records) {
    const auto& input=output.input;
    const auto cells=output.total_porosity.size();
    for (std::size_t i=0;i<2;++i) if (input.sides[i].fluid==Fluid::air) {
        if (input.continuous || input.geometry_mode==2) air_spatial_ranges_3d(output,i,records);
        else air_uniform_ranges_3d(output,i,records);
    }
    for (std::size_t i=0;i<2;++i) {
        const auto& inlet=input.sides[i];auto& side=output.sides[i];
        if (inlet.fluid!=Fluid::co2 && !input.df_mode) continue;
        side.have_drag_application=true;
        auto& evidence=side.drag_evidence;
        const auto factors=drag_factors(input,inlet,i,records,evidence,input.continuous.has_value(),"scalar");
        const bool scalar_summary=inlet.fluid!=Fluid::co2;
        const std::size_t size=scalar_summary?1:cells;
        const std::vector<double> scale_k(size,factors.K),scale_f(size,factors.cF);
        const auto applied_k=df_apply_scale({output.permeability.data(),size},{scale_k.data(),size},scalar_summary);
        const auto applied_f=df_apply_scale({output.forchheimer.data(),size},{scale_f.data(),size},scalar_summary);
        evidence.base_permeability=df_summary({output.permeability.data(),size},scalar_summary);
        evidence.base_forchheimer=df_summary({output.forchheimer.data(),size},scalar_summary);
        evidence.applied_permeability=df_summary({applied_k.data(),size},scalar_summary);
        evidence.applied_forchheimer=df_summary({applied_f.data(),size},scalar_summary);
        evidence.scale_permeability=factors.K;evidence.scale_forchheimer=factors.cF;
        if (input.continuous && inlet.fluid!=Fluid::co2) {
            evidence.geometry_application="continuous-field-extrapolation";
            evidence.reference_geometry_mm=std::array<double,2>{input.geometry.cell_length_mm,input.geometry.wall_thickness_mm};
            evidence.application_scope="Exploratory continuous L/t trend prediction using "
                "frozen uniform-HX factors; gradient accuracy unvalidated";
        }
    }
    for (std::size_t axis=0;axis<3;++axis)
        output.edges[axis]=g::cumulative_widths({output.widths[axis].data(),output.widths[axis].size()});
    model_evidence(input,output.evidence,input.continuous.has_value() || input.geometry_mode==2);
    const std::vector<std::size_t> shape{output.widths[0].size(),output.widths[1].size(),output.widths[2].size()};
    if (input.continuous || input.geometry_mode==2) {
        auto cell_mm=output.cell_length,wall_mm=output.wall_thickness;
        for (auto& value:cell_mm) value*=1e3;
        for (auto& value:wall_mm) value*=1e3;
        records.range({"geometry","L_field_m"},"shared","prepared-geometry","physical-cell","fixed geometry domain","cell length","mm",
            {df_data::df_L_nodes.front(),df_data::df_L_nodes.back()},cell_mm,shape);
        records.range({"geometry","t_field_m"},"shared","prepared-geometry","physical-cell","fixed geometry domain","wall thickness","mm",
            {df_data::df_t_nodes.front(),df_data::df_t_nodes.back()},wall_mm,shape);
    } else {
        records.range({"geometry","L_field_m"},"shared","prepared-geometry","physical-cell","fixed geometry domain","cell length","mm",
            {df_data::df_L_nodes.front(),df_data::df_L_nodes.back()},
            output.cell_length.front()*1e3,shape);
        records.range({"geometry","t_field_m"},"shared","prepared-geometry","physical-cell","fixed geometry domain","wall thickness","mm",
            {df_data::df_t_nodes.front(),df_data::df_t_nodes.back()},
            output.wall_thickness.front()*1e3,shape);
    }
    finish_warnings(records);
}

void capacities_3d(const PreparedCase3D& prepared,InletFlow3D& flow) {
    const std::array<std::size_t,3> shape{{prepared.widths[0].size(),prepared.widths[1].size(),prepared.widths[2].size()}};
    const auto field=[](const std::vector<double>& values) {return FlowValues{values.data(),values.size()};};
    for (std::size_t i=0;i<2;++i) {
        const auto& side=prepared.sides[i];
        const auto& porosity=i && !prepared.side_b_porosity.empty()?prepared.side_b_porosity:prepared.side_porosity;
        flow.capacities[i]=inlet_capacity_3d(field(porosity),shape,prepared.input.sides[i].port.direction,
            field(prepared.widths[static_cast<std::size_t>(side.axes[0])]),
            field(prepared.widths[static_cast<std::size_t>(side.axes[2])]),field(side.openings[0]),side.properties[0]);
        if (!std::isfinite(flow.capacities[i]) || flow.capacities[i]<=0.)
            throw std::invalid_argument("side "+std::string(i?"B":"A")+": inlet density times open pore area must be finite and positive");
    }
    flow.have_capacities=true;
}

std::array<std::optional<double>,2> flow_targets(const InletFlowRequest3D& request,CaseInput3D& input) {
    input=request.input;
    if (request.explicit_targets) {
        for (std::size_t i=0;i<2;++i) {
            const auto target=(*request.explicit_targets)[i];
            if (!std::isfinite(target) || target<=0.)
                throw std::invalid_argument("mass_flow_"+std::string(i?"B":"A")+"_kg_s must be finite and positive");
            input.sides[i].mass_flow_kg_s.reset();
        }
        return {(*request.explicit_targets)[0],(*request.explicit_targets)[1]};
    }
    return {input.sides[0].mass_flow_kg_s,input.sides[1].mass_flow_kg_s};
}

void resolve_speeds(const std::array<std::optional<double>,2>& targets,
                    InletFlow3D& flow,CaseScope3D scope) {
    for (std::size_t i=0;i<2;++i) {
        auto& inlet=flow.input.sides[i];
        if (targets[i]) {
            flow.speeds[i]=inlet_speed(*targets[i],flow.capacities[i]);
            inlet.velocity_m_s=flow.speeds[i];
        } else flow.speeds[i]=inlet.velocity_m_s;
    }
    flow.input=validate_3d(flow.input,scope,true);
}
}  // namespace

PreparedCase3D prepare_case_3d(const CaseInput3D& requested,const PreparationOptions& options,
                             const PreparationCallbacks& callbacks,CaseScope3D scope) {
    FloatingEnvironment floating_environment;
    PreparedCase3D output{};output.input=validate_3d(requested,scope);output.options=options;
    Records records{output.evidence,callbacks,{},{}};
    prepare_geometry_3d(output,records,true);finish_case_3d(output,records);
    return output;
}

InletFlow3D prepare_inlet_mass_capacities_3d(const CaseInput3D& input,const PreparationOptions& options,
                                          const PreparationCallbacks& callbacks,CaseScope3D scope) {
    FloatingEnvironment floating_environment;
    InletFlow3D output;output.input=input;
    PreparedCase3D prepared{};prepared.input=validate_3d(input,scope,true,false);prepared.options=options;
    Records records{prepared.evidence,callbacks,{},{}};
    prepare_geometry_3d(prepared,records,false);capacities_3d(prepared,output);finish_warnings(records);
    output.evidence=std::move(prepared.evidence);return output;
}

InletFlow3D resolve_inlet_flow_3d(const InletFlowRequest3D& request,const PreparationOptions& options,
                               const PreparationCallbacks& callbacks,CaseScope3D scope) {
    FloatingEnvironment floating_environment;
    InletFlow3D output;const auto targets=flow_targets(request,output.input);
    if (!targets[0] && !targets[1]) return output;
    output=prepare_inlet_mass_capacities_3d(output.input,options,callbacks,scope);
    resolve_speeds(targets,output,scope);return output;
}

PreparedFlowCase3D prepare_flow_case_3d(const InletFlowRequest3D& request,const PreparationOptions& options,
                                     const PreparationCallbacks& callbacks,CaseScope3D scope) {
    FloatingEnvironment floating_environment;
    PreparedFlowCase3D output;const auto targets=flow_targets(request,output.flow.input);
    if (!targets[0] && !targets[1]) {
        output.prepared=prepare_case_3d(output.flow.input,options,callbacks,scope);return output;
    }
    auto& prepared=output.prepared;
    prepared.input=validate_3d(output.flow.input,scope,true,false);prepared.options=options;
    Records records{prepared.evidence,callbacks,{},{}};
    prepare_geometry_3d(prepared,records,false);capacities_3d(prepared,output.flow);
    output.flow.evidence=prepared.evidence;
    Records preliminary{output.flow.evidence,callbacks,records.warning_order,records.plain_warnings};
    finish_warnings(preliminary);
    resolve_speeds(targets,output.flow,scope);
    prepared.input=output.flow.input;
    preflight(prepared.input,options,prepared.uniform_geometry.geometry,prepared.input.sides,records);
    finish_case_3d(prepared,records);return output;
}

}  // namespace tpmshx::preparation
