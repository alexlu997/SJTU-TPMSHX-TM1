#include "tpmshx/preparation_case.hpp"
#include "tpmshx/grid.hpp"
#include "tpmshx/model_coefficients.hpp"
#include "tpmshx/preparation_df.hpp"
#include "tpmshx/preparation_df_data.hpp"
#include "preparation_df_fields.hpp"
#include "preparation_properties.hpp"

#include <algorithm>
#include <charconv>
#include <cfenv>
#include <cmath>
#include <iomanip>
#include <limits>
#include <locale>
#include <sstream>
#include <stdexcept>
#include <utility>

namespace tpmshx::preparation {
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

std::string decimal(double value) {
    if (std::isnan(value)) return "nan";
    if (std::isinf(value)) return value<0.?"-inf":"inf";
    char buffer[64];
    const auto converted=std::to_chars(buffer,buffer+sizeof(buffer),value,std::chars_format::scientific);
    if (converted.ec!=std::errc{}) throw std::runtime_error("cannot format preparation value");
    std::string text(buffer,converted.ptr);
    const auto e=text.find('e');
    const int exponent=std::stoi(text.substr(e+1));
    if (exponent < -4 || exponent>=16) return text;
    const bool negative=text.front()=='-';
    std::string digits=text.substr(negative?1:0,e-(negative?1:0));
    const auto point=digits.find('.');
    if (point!=std::string::npos) digits.erase(point,1);
    const int position=exponent+1;
    if (position<=0) digits="0."+std::string(static_cast<std::size_t>(-position),'0')+digits;
    else if (static_cast<std::size_t>(position)>=digits.size())
        digits+=std::string(static_cast<std::size_t>(position)-digits.size(),'0')+".0";
    else digits.insert(static_cast<std::size_t>(position),1,'.');
    return (negative?"-":"")+digits;
}
std::string fixed(double value,int precision) {
    std::ostringstream stream;stream.imbue(std::locale::classic());
    stream<<std::fixed<<std::setprecision(precision)<<value;
    return stream.str();
}
std::string significant(double value,int precision) {
    std::ostringstream stream;stream.imbue(std::locale::classic());
    stream<<std::setprecision(precision)<<value;
    return stream.str();
}
const char* topology_name(Topology topology) {
    if (topology==Topology::diamond) return "Diamond";
    if (topology==Topology::gyroid) return "Gyroid";
    throw std::invalid_argument("TPMS geometry supports Diamond and Gyroid only");
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

PortInput2D checked_port(PortInput2D port,const GridInput2D& grid,const std::string& side) {
    const auto prefix="ComputeConfig.bc_"+side;
    if ((port.inlet_width_m<=0.)!=(port.outlet_width_m<=0.))
        throw std::invalid_argument(prefix+".in_w and out_w must both be positive, or both be <= 0 for a full-face port");
    if (!std::isfinite(port.inlet_width_m) || !std::isfinite(port.outlet_width_m))
        throw std::invalid_argument("port width must be finite before full-face normalization");
    const double cross=port.direction==0 || port.direction==1?grid.height_m:grid.length_m;
    if (port.inlet_width_m<=0. && port.outlet_width_m<=0.) {
        port.inlet_center_m=port.outlet_center_m=cross/2.;
        port.inlet_width_m=port.outlet_width_m=cross;
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
        else if (center-width/2.<0. || center+width/2.>cross)
            error="[error] pipe_"+name+"_out_of_domain: "+name+"_ctr ± "+name+"_w/2 = ["+
                  significant(center-width/2.,3)+", "+significant(center+width/2.,3)+
                  "] m leaves the cross-axis range [0, "+significant(cross,3)+"].";
        if (!error.empty()) {if (!errors.empty()) errors+="; ";errors+=error;}
    }
    if (!errors.empty()) throw std::invalid_argument(prefix+" is invalid: "+errors);
    return port;
}

std::array<InletInput2D,2> validate(const CaseInput2D& input) {
    if (input.geometry_mode!=0)
        throw std::invalid_argument("native 2D preparation currently requires uniform geometry");
    if (input.df_mode!=0)
        throw std::invalid_argument("native 2D preparation currently requires df_mode='cfd_smooth'");
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
        if (sides[side].mass_flow_kg_s)
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
    if (geometry.cell_length_mm<df_data::df_L_nodes.front() || geometry.cell_length_mm>df_data::df_L_nodes.back()
        || geometry.wall_thickness_mm<df_data::df_t_nodes.front() || geometry.wall_thickness_mm>df_data::df_t_nodes.back())
        throw std::invalid_argument("V2 geometry must lie inside the CFD grid: 4 <= L <= 8 mm, 0.3 <= t <= 0.6 mm");
    for (std::size_t side=0;side<2;++side)
        positive(sides[side].velocity_m_s,std::string("fluid_")+(side?"B":"A")+".u_mps");
    for (const auto& side:sides) if (side.fluid!=Fluid::air)
        throw std::invalid_argument("native 2D preparation currently supports air/air only");
    for (std::size_t axis=0;axis<2;++axis) {
        const double length=axis?input.grid.height_m:input.grid.length_m;
        if (length>10.) throw std::invalid_argument(std::string("Domain dimension '")+(axis?'H':'L')+"'="+
            decimal(length)+" m exceeds 10.0 m. Likely unit slip — GUI expects meters here, while L_cell and t use millimeters. Re-check input.");
    }
    topology_name(geometry.topology);
    if (geometry.delta_levelset!=0.)
        throw std::invalid_argument("native 2D preparation currently requires symmetric delta_levelset=0 geometry");
    return sides;
}

g::Port native_port(const PortInput2D& input) {
    return {input.direction,true,{{{g::weak(input.inlet_center_m),g::weak(input.inlet_width_m),{},{}},
                                  {g::weak(input.outlet_center_m),g::weak(input.outlet_width_m),{},{}}}}};
}
g::Scalars unique(g::Scalars values) {
    std::sort(values.begin(),values.end(),[](auto a,auto b){return a.value<b.value;});
    values.erase(std::unique(values.begin(),values.end(),[](auto a,auto b){return a.value==b.value;}),values.end());
    return values;
}
g::Scalars bounds(double length,const g::Scalars& points) {
    const auto keep=g::aligned_filter(g::weak(length),points);
    g::Scalars output{g::weak(0.),g::weak(length)};
    for (std::size_t i=0;i<points.size();++i) if (keep[i]) output.push_back(points[i]);
    return unique(std::move(output));
}
std::vector<double> values(const g::Scalars& input) {
    std::vector<double> result;result.reserve(input.size());
    for (const auto& item:input) result.push_back(item.value);
    return result;
}
PhysicalGrid2D physical_grid(const GridInput2D& input,const std::array<InletInput2D,2>& sides) {
    const g::Scalars lengths{g::weak(input.length_m),g::weak(input.height_m)};
    const std::vector<g::Port> ports{native_port(sides[0].port),native_port(sides[1].port)};
    const std::array<g::Scalars,2> breaks{unique(g::breaks_2d(lengths,ports,0)),unique(g::breaks_2d(lengths,ports,1))};
    PhysicalGrid2D output;
    output.x_breaks=values(breaks[0]);output.y_breaks=values(breaks[1]);
    std::array<std::vector<double>,2> widths;
    if (input.port_wall_refine) {
        for (std::size_t axis=0;axis<2;++axis) {
            const auto knots=unique(g::port_edges(lengths,ports,axis));
            g::Scalars outer{g::weak(0.)};outer.insert(outer.end(),knots.begin(),knots.end());outer.push_back(lengths[axis]);
            std::size_t minimum=0;
            widths[axis]=g::port_wall_axis(2,axis?input.requested_ny:input.requested_nx,outer,
                                          bounds(lengths[axis].value,knots),minimum,axis);
        }
    } else {
        bool refined=false;
        if (breaks[0].empty() && breaks[1].empty()) {
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
                                    bounds(lengths[axis].value,breaks[axis])).widths;
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

    void emit(PreparationEvent event) {
        output.events.push_back(std::move(event));
        if (callbacks.event) callbacks.event(callbacks.context,output.events.back());
    }
    void floating(const std::array<std::uint32_t,property_event_count>& events) {
        for (auto encoded:events) if (encoded)
            emit({PreparationEventKind::floating_point,"","",encoded});
    }
    void warning(std::string message) {
        if (std::find(plain_warnings.begin(),plain_warnings.end(),message)!=plain_warnings.end()) return;
        warning_order.emplace_back(false,plain_warnings.size());plain_warnings.push_back(std::move(message));
    }
    void range(std::vector<std::string> source,const std::string& side,const std::string& stage,
               const std::string& layout,std::string label,const char* quantity,const char* unit,
               const std::array<double,2>& limits,double value,std::vector<std::size_t> shape={}) {
        PreparationRangeSample sample;
        sample.size=1;for (const auto extent:shape) sample.size=count(sample.size,extent);
        sample.have_finite=std::isfinite(value);
        if (sample.have_finite) {
            sample.minimum=sample.maximum=value;
            sample.low=value<limits[0]?sample.size:0;sample.high=value>limits[1]?sample.size:0;
        } else sample.nonfinite=sample.size;
        for (auto& previous:output.ranges) if (previous.source==source && previous.side==side
                && previous.stage==stage && previous.layout==layout && previous.shape==shape) {
            auto aggregate=previous.sample;
            if (sample.low+sample.high>aggregate.low+aggregate.high) {
                aggregate.low=sample.low;aggregate.high=sample.high;aggregate.size=sample.size;
            }
            if (sample.have_finite) {
                if (!aggregate.have_finite || sample.minimum<aggregate.minimum) aggregate.minimum=sample.minimum;
                if (!aggregate.have_finite || sample.maximum>aggregate.maximum) aggregate.maximum=sample.maximum;
                aggregate.have_finite=true;
            }
            aggregate.nonfinite=std::max(aggregate.nonfinite,sample.nonfinite);
            previous.sample=aggregate;previous.last=sample;return;
        }
        warning_order.emplace_back(true,output.ranges.size());
        output.ranges.push_back({std::move(source),side,stage,layout,std::move(label),quantity,unit,limits,
                                 std::move(shape),sample,sample});
    }
};

std::string sample_index(const PreparationRange& range,std::size_t index) {
    if (range.shape.empty()) return "()";
    if (range.shape.size()==1) return "("+std::to_string(index)+",)";
    return "("+std::to_string(index/range.shape[1])+", "+std::to_string(index%range.shape[1])+")";
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
    return range.label+": "+range.quantity+" source range ("+decimal(range.bounds[0])+", "+decimal(range.bounds[1])+") "+
        range.unit+"; view="+range.source.front()+", side="+range.side+", stage="+range.stage+", layout="+range.layout+
        ", sample="+shape+"; finite extrema across observations: min="+extremum(sample.minimum,sample.minimum_index)+
        ", max="+extremum(sample.maximum,sample.maximum_index)+" (value, index); worst single snapshot: low="+
        std::to_string(sample.low)+", high="+std::to_string(sample.high)+", outside="+std::to_string(sample.low+sample.high)+
        "/"+std::to_string(sample.size)+" ("+fixed(100.*static_cast<double>(sample.low+sample.high)/
        static_cast<double>(sample.size),2)+"% of sampled values); peak nonfinite in one snapshot="+
        std::to_string(sample.nonfinite)+"/"+std::to_string(sample.size)+" (not classified inside range).";
}

PropertyInput operand(double& value,bool strong=false) {
    return {{&value,1},{value,64,strong?1u:0u},strong?1u:0u};
}
double property(Empirical getter,double temperature,double pressure,Records& records) {
    const auto result=empirical(getter,operand(temperature),operand(pressure));
    records.floating(result.events);return result.values.front();
}
double inlet_re(double rho,double velocity,double diameter,double mu,Records& records) {
    const auto result=reynolds(operand(rho),operand(velocity),operand(diameter,true),operand(mu));
    records.floating(result.events);return result.values.front();
}
void preflight(const CaseInput2D& input,const PreparationOptions& options,const geometry::Geometry& geometry,
               const std::array<InletInput2D,2>& sides,Records& records) {
    for (std::size_t i=0;i<2;++i) {
        const auto& inlet=sides[i];const std::string side=i?"B":"A";
        const double rho=property(Empirical::air_density,inlet.temperature_K,inlet.pressure_Pa,records);
        records.range({"property","air_viscosity"},"unbound","unbound","source","air_viscosity","T","K",
                      data::air_temperature_range,inlet.temperature_K);
        const double mu=property(Empirical::air_viscosity,inlet.temperature_K,inlet.pressure_Pa,records);
        const double re=inlet_re(rho,inlet.velocity_m_s,geometry.hydraulic_diameter,mu,records);
        records.range({"nu","air",topology_name(input.geometry.topology)},side,"inlet-preflight","scalar",
                      "air inlet Nu","Re","-",data::air_nu_re_range,re);
        if (!(data::air_nu_re_range[0]<=re && re<=data::air_nu_re_range[1])) {
            const std::string reason="Fluid "+side+": Re = "+fixed(re,0)+" outside air Nu window ["+
                fixed(data::air_nu_re_range[0],0)+", "+fixed(data::air_nu_re_range[1],0)+"] (u="+
                decimal(inlet.velocity_m_s)+" m/s, T="+decimal(inlet.temperature_K)+" K, P="+
                fixed(inlet.pressure_Pa,0)+" Pa, L="+decimal(input.geometry.cell_length_mm)+"mm, t="+
                decimal(input.geometry.wall_thickness_mm)+"mm).";
            if (!options.allow_extrapolation) throw std::invalid_argument(reason);
            records.emit({PreparationEventKind::warning,"", "[surrogate extrap] "+reason});
            records.warning(reason);
        }
    }
}

UniformInletProperties inlet_properties(const CaseInput2D& input,const InletInput2D& inlet,std::size_t index,
                                       const geometry::MaterialGeometry& geometry,Records& records) {
    const std::string side=index?"B":"A";
    UniformInletProperties output{};
    const auto temperature=[&](Empirical getter,const char* name,const std::array<double,2>& limits) {
        records.range({"property",name},side,"inlet","scalar",name,"T","K",limits,inlet.temperature_K);
        return property(getter,inlet.temperature_K,inlet.pressure_Pa,records);
    };
    output.mu=temperature(Empirical::air_viscosity,"air_viscosity",data::air_temperature_range);
    output.k_f=temperature(Empirical::air_conductivity,"air_conductivity",data::air_temperature_range);
    output.rho=property(Empirical::air_density,inlet.temperature_K,inlet.pressure_Pa,records);
    output.cp=temperature(Empirical::air_cp,"air_cp",data::air_cp_temperature_range);
    double diameter=geometry.geometry.hydraulic_diameter,velocity=inlet.velocity_m_s;
    output.re=inlet_re(output.rho,velocity,diameter,output.mu,records);
    auto result=prandtl(operand(output.mu),operand(output.cp),operand(output.k_f));
    records.floating(result.events);output.pr=result.values.front();
    std::array<double,4> extrema{};
    result=nu_inputs(NuRoute::air_direct,operand(output.re,true),{},{},{},{},extrema);
    records.floating(result.events);
    double prepared_re=result.values.front(),fixed_pr=data::pr_air;
    double cell=input.geometry.cell_length_mm,diameter_mm=diameter*1000.;
    records.range({"nu","air",topology_name(input.geometry.topology)},side,"inlet","scalar",
                  std::string("[Nu extrap] ")+topology_name(input.geometry.topology),"Re","-",data::air_nu_re_range,output.re);
    result=nusselt(NuRoute::air_direct,input.geometry.topology,operand(prepared_re),operand(fixed_pr),
                   operand(cell),operand(diameter_mm,true),g::weak(1.));
    records.floating(result.events);output.nu=result.values.front();
    result=surface_transfer(operand(output.nu,true),operand(output.k_f),operand(diameter,true));
    records.floating(result.events);output.surface_transfer_W_m2K=result.values.front();
    const auto drag=fixed_df(static_cast<std::uint32_t>(input.geometry.topology),cell,input.geometry.wall_thickness_mm);
    output.permeability_m2=drag.K;output.forchheimer_per_m=drag.cF;
    result=df_pressure_gradient(operand(output.rho),operand(output.mu),operand(velocity),
                                operand(output.permeability_m2),operand(output.forchheimer_per_m));
    records.floating(result.events);output.pressure_gradient_Pa_m=result.values.front();
    double epsilon_a=geometry.geometry.epsilon_a;
    result=pore_conductivity(operand(epsilon_a),operand(output.k_f));
    records.floating(result.events);output.fluid_conductivity_W_mK=result.values.front();
    output.solid_conductivity_W_mK=geometry.solid_conductivity;
    return output;
}
}  // namespace

PreparedCase2D prepare_case_2d(const CaseInput2D& input,const PreparationOptions& options,
                              const PreparationCallbacks& callbacks) {
    FloatingEnvironment floating_environment;
    const auto inlets=validate(input);
    PreparedCase2D output{};output.input=input;output.options=options;
    Records records{output.evidence,callbacks,{},{}};
    const auto& model=input.geometry;
    const auto calibration=geometry::calibration(model.topology);
    const auto uniform=geometry::standard_geometry(geometry_index(model.topology),calibration,
                                                   model.cell_length_mm,model.wall_thickness_mm);
    output.uniform_geometry=geometry::with_material(uniform,calibration.solid_tortuosity,
                                                    model.solid_conductivity_W_mK,options.chi_override);
    output.hydraulic_radius_m=geometry::hydraulic_radius(uniform.hydraulic_diameter);
    preflight(input,options,uniform,inlets,records);
    output.grid=physical_grid(input.grid,inlets);
    if (output.grid.nx!=input.grid.requested_nx || output.grid.ny!=input.grid.requested_ny)
        records.emit({PreparationEventKind::log,logger,"[run_calculation] Wall-refined grid: "+
            std::to_string(output.grid.nx)+"×"+std::to_string(output.grid.ny)+" cells (4-wall BL resolved)"});
    const auto drag=fixed_df(static_cast<std::uint32_t>(model.topology),model.cell_length_mm,model.wall_thickness_mm);
    for (std::size_t i=0;i<2;++i) {
        auto& side=output.sides[i];side.inlet=inlets[i];
        const auto& port=side.inlet.port;
        const bool x=port.direction==0 || port.direction==1;
        side.cross_widths=x?output.grid.dy:output.grid.dx;
        side.stream_widths=x?output.grid.dx:output.grid.dy;
        if (port.direction==1 || port.direction==3) std::reverse(side.stream_widths.begin(),side.stream_widths.end());
        side.row_permeability.assign(side.stream_widths.size(),drag.K);
        side.row_forchheimer.assign(side.stream_widths.size(),drag.cF);
        side.seed_permeability_m2=drag.K;side.seed_forchheimer_per_m=drag.cF;
        const auto permeability_summary=df_summary({side.row_permeability.data(),side.row_permeability.size()},
                                                   side.row_permeability.size()==1);
        const auto forchheimer_summary=df_summary({side.row_forchheimer.data(),side.row_forchheimer.size()},
                                                  side.row_forchheimer.size()==1);
        side.drag_evidence={permeability_summary,forchheimer_summary,permeability_summary,forchheimer_summary,
                            1.,1.,"water-sco2-cfd-fixed-v2","CFD-smooth-wall"};
        side.inlet_bounds={port.inlet_center_m-port.inlet_width_m/2.,port.inlet_center_m+port.inlet_width_m/2.};
        side.outlet_bounds={port.outlet_center_m-port.outlet_width_m/2.,port.outlet_center_m+port.outlet_width_m/2.};
        auto openings=g::port_fractions(side.cross_widths,g::weak(side.inlet_bounds[0]),g::weak(side.inlet_bounds[1]),port.uniform_inlet);
        side.inlet_geometry=std::move(openings[0]);side.inlet_profile=std::move(openings[1]);
        openings=g::port_fractions(side.cross_widths,g::weak(side.outlet_bounds[0]),g::weak(side.outlet_bounds[1]));
        side.outlet_geometry=std::move(openings[0]);side.outlet_profile=std::move(openings[1]);
        side.outlet_u_fraction=g::port_overlap(side.cross_widths,g::weak(side.outlet_bounds[0]),g::weak(side.outlet_bounds[1]),true);
    }
    for (std::size_t i=0;i<2;++i)
        output.sides[i].properties=inlet_properties(input,inlets[i],i,output.uniform_geometry,records);
    const auto cells=count(output.grid.nx,output.grid.ny);
    output.cell_length_m=model.cell_length_mm*1e-3;output.wall_thickness_m=model.wall_thickness_mm*1e-3;
    output.cell_length.assign(cells,output.cell_length_m);output.wall_thickness.assign(cells,output.wall_thickness_m);
    output.total_porosity.assign(cells,uniform.epsilon);
    output.solid_conductivity.assign(cells,output.uniform_geometry.solid_conductivity);
    output.hydraulic_radius.assign(cells,output.hydraulic_radius_m);
    output.evidence.models={{{"fluid",data::fluid_version,"A"},{"fluid",data::fluid_version,"B"},
        {"geometry",data::geometry_version,""},{"darcy_forchheimer",data::darcy_forchheimer_version,""}}};
    const std::vector<std::size_t> shape{output.grid.nx,output.grid.ny};
    records.range({"geometry","L_field_m"},"shared","prepared-geometry","physical-cell","fixed geometry domain","cell length","mm",
                  {df_data::df_L_nodes.front(),df_data::df_L_nodes.back()},output.cell_length_m*1e3,shape);
    records.range({"geometry","t_field_m"},"shared","prepared-geometry","physical-cell","fixed geometry domain","wall thickness","mm",
                  {df_data::df_t_nodes.front(),df_data::df_t_nodes.back()},output.wall_thickness_m*1e3,shape);
    for (const auto item:records.warning_order) {
        const auto warning=item.first?range_warning(output.evidence.ranges[item.second]):records.plain_warnings[item.second];
        if (!warning.empty() && std::find(output.evidence.warnings.begin(),output.evidence.warnings.end(),warning)==output.evidence.warnings.end())
            output.evidence.warnings.push_back(warning);
    }
    return output;
}

}  // namespace tpmshx::preparation
