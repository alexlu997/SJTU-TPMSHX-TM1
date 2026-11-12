#include "tpmshx/preparation_case.hpp"
#include "tpmshx/preparation_flow.hpp"
#include "tpmshx/asym_geometry.hpp"
#include "tpmshx/grid.hpp"
#include "tpmshx/model_coefficients.hpp"
#include "tpmshx/preparation_df.hpp"
#include "tpmshx/preparation_df_data.hpp"
#include "preparation_df_fields.hpp"
#include "preparation_properties.hpp"
#include "field_continuous.hpp"
#include "contiguous_sum.hpp"

#include <algorithm>
#include <charconv>
#include <cfenv>
#include <cmath>
#include <iomanip>
#include <limits>
#include <locale>
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
constexpr ScalarKind numpy_double{64,1,1};

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
template<class Input> ScalarKind solid_result_kind(const Input& input) {
    if (co2_geometry(input)) return numpy_double;
    const auto kind=input.kinds.solid_conductivity;
    // Standard geometry converts a zero-dimensional material array to a Python float.
    return kind.layout==2?ScalarKind{}:kind;
}
g::Scalar scalar(double value,ScalarKind kind) {
    if (kind.strong>1 || kind.layout>2 || (!kind.strong && (kind.precision!=64 || kind.layout))
        || (kind.strong && !kind.layout))
        throw std::invalid_argument("preparation scalar tags must follow the property scalar contract");
    return g::checked({value,kind.precision,kind.strong});
}
bool blank_text(std::string_view text) {
    // Python strips these Unicode spaces and the listed ASCII controls.
    constexpr std::array<std::string_view,19> spaces{{
        "\xC2\x85","\xC2\xA0","\xE1\x9A\x80","\xE2\x80\x80","\xE2\x80\x81",
        "\xE2\x80\x82","\xE2\x80\x83","\xE2\x80\x84","\xE2\x80\x85","\xE2\x80\x86",
        "\xE2\x80\x87","\xE2\x80\x88","\xE2\x80\x89","\xE2\x80\x8A","\xE2\x80\xA8",
        "\xE2\x80\xA9","\xE2\x80\xAF","\xE2\x81\x9F","\xE3\x80\x80"}};
    while (!text.empty()) {
        const auto first=static_cast<unsigned char>(text.front());
        if ((first>=9 && first<=13) || (first>=28 && first<=32)) {text.remove_prefix(1);continue;}
        const auto found=std::find_if(spaces.begin(),spaces.end(),[&](auto space) {
            return text.substr(0,space.size())==space;
        });
        if (found==spaces.end()) return false;
        text.remove_prefix(found->size());
    }
    return true;
}
void validate_nu(const Sco2NuSelection& selected) {
    if (selected.mode>1) throw std::invalid_argument("unsupported sCO2 Nu mode");
    for (std::size_t i=0;i<2;++i) {
        const auto value=selected.alpha[i];
        if (!value && !selected.mode) continue;
        if (!value || !std::isfinite(*value) || *value<=0.)
            throw std::invalid_argument(std::string("sCO2 Nu alpha_")+(i?'G':'D')+" must be finite and positive");
    }
    const std::array<std::pair<const char*,const std::string*>,3> texts{{
        {"parameter_version",&selected.parameter_version},{"source",&selected.source},{"applicability",&selected.applicability}}};
    for (const auto& text:texts) if (selected.mode && blank_text(*text.second))
        throw std::invalid_argument(std::string("sCO2 Nu requires ")+text.first);
}
template<class Input,class Inlet>
std::pair<DfSelection,DfPair> experiment_selection(const Input& input,const Inlet& inlet,
                                                 std::size_t side,bool continuous=false) {
    const auto topology=static_cast<std::uint32_t>(input.geometry.topology);
    const auto fluid=static_cast<std::uint32_t>(inlet.fluid);
    const auto cell=input.geometry.cell_length_mm,wall=input.geometry.wall_thickness_mm,speed=inlet.velocity_m_s;
    try {
        const auto selected=df_select(topology,fluid,continuous,{&cell,1},{&wall,1},{&speed,1},true);
        return {selected,df_scales(topology,selected,{&cell,1},{&wall,1}).front()};
    } catch (const std::invalid_argument& error) {
        std::string text=error.what();
        std::vector<PreparationFailureCause> causes;
        if (text=="HX velocity outside application window") {
            causes.push_back({1,text});
            const auto& window=df_data::application_u[fluid][topology];
            text=std::string(fluid_name(inlet.fluid))+" HX experiment calibration requires "+
                significant(window[0],6)+"<=u<="+significant(window[1],6)+" m/s for "+
                topology_name(input.geometry.topology)+"; got "+decimal(speed);
        }
        causes.insert(causes.begin(),{1,text});
        throw PreparationError(1,"experimental calibration unavailable for active side "+
            std::string(side?"B":"A")+": "+text,1,static_cast<std::uint32_t>(side),std::move(causes));
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
    return input.continuous?CaseScope::continuous_v4:CaseScope::uniform_mass_v3;
}
std::array<InletInput2D,2> validate(const CaseInput2D& input,CaseScope scope,bool static_only=false) {
    const bool continuous=scope==CaseScope::continuous_v4;
    const bool mass=continuous || scope==CaseScope::uniform_mass_v3;
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
    if (geometry.cell_length_mm<df_data::df_L_nodes.front() || geometry.cell_length_mm>df_data::df_L_nodes.back()
        || geometry.wall_thickness_mm<df_data::df_t_nodes.front() || geometry.wall_thickness_mm>df_data::df_t_nodes.back())
        throw std::invalid_argument("V2 geometry must lie inside the CFD grid: 4 <= L <= 8 mm, 0.3 <= t <= 0.6 mm");
    for (std::size_t side=0;side<2;++side) if (scope!=CaseScope::air_cfd_v1 && sides[side].fluid==Fluid::sco2) {
        const auto& inlet=sides[side];
        if (!(data::sco2_temperature_range[0]<=inlet.temperature_K && inlet.temperature_K<=data::sco2_temperature_range[1]))
            throw PreparationError(1,std::string("sCO2 fluid ")+(side?"B":"A")+" temperature must be 280..700 K",1,
                                   static_cast<std::uint32_t>(side));
        if (!(data::sco2_pressure_range[0]<=inlet.pressure_Pa && inlet.pressure_Pa<=data::sco2_pressure_range[1]))
            throw PreparationError(1,std::string("sCO2 fluid ")+(side?"B":"A")+" pressure must be 7.9..16 MPa",1,
                                   static_cast<std::uint32_t>(side));
        if (geometry.delta_levelset!=0.) throw std::invalid_argument("sCO2 V2 requires delta_levelset=0");
    }
    if (scope!=CaseScope::air_cfd_v1 && co2_geometry(input) && geometry.delta_levelset!=0.)
        throw std::invalid_argument("CO2 requires symmetric delta_levelset=0 geometry");
    if (!static_only) for (std::size_t side=0;side<2;++side)
        positive(sides[side].velocity_m_s,std::string("fluid_")+(side?"B":"A")+".u_mps");
    if (scope==CaseScope::air_cfd_v1) for (const auto& side:sides) if (side.fluid!=Fluid::air)
        throw std::invalid_argument("native 2D preparation currently supports air/air only");
    for (const auto& side:sides) fluid_name(side.fluid);
    if (!static_only && continuous && input.df_mode) {
        const bool shanghai=geometry.topology==Topology::gyroid && sides[0].fluid==Fluid::air
            && sides[1].fluid==Fluid::water && std::abs(geometry.cell_length_mm-7.)<=1e-12
            && std::abs(geometry.wall_thickness_mm-.6)<=1e-12;
        if (!shanghai && (sides[0].fluid!=Fluid::co2 || sides[1].fluid!=Fluid::co2))
            throw std::invalid_argument("experimental calibration currently requires uniform L/t; "
                "continuous Shanghai Gyroid air/water fields may use "
                "the 7/0.6 calibration as an exploratory extrapolation");
    }
    if (!static_only && input.df_mode) for (std::size_t side=0;side<2;++side) if (sides[side].fluid!=Fluid::co2) {
        const auto selected=experiment_selection(input,sides[side],side,input.continuous.has_value()).first;
        const auto close=[](double a,double b) {return std::abs(a-b)<=1e-9*std::max(std::abs(a),std::abs(b));};
        if (selected.scope && (geometry.delta_levelset!=0. || !close(input.grid.length_m,df_data::hx_domain_m[0])
                              || !close(input.grid.height_m,df_data::hx_domain_m[1])))
            throw PreparationError(1,"experimental calibration side "+std::string(side?"B":"A")+
                " is HX-effective and requires delta=0 with the matching 0.182 x 0.042 x 0.042 m campaign domain",1,
                static_cast<std::uint32_t>(side));
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
    if (geometry.delta_levelset!=0. && !static_only)
        throw std::invalid_argument("native 2D preparation currently requires symmetric delta_levelset=0 geometry");
    scalar(geometry.cell_length_mm,input.kinds.cell_length);
    scalar(geometry.wall_thickness_mm,input.kinds.wall_thickness);
    scalar(geometry.solid_conductivity_W_mK,input.kinds.solid_conductivity);
    for (std::size_t i=0;i<2;++i) {
        if (!static_only) scalar(sides[i].velocity_m_s,input.kinds.sides[i].velocity);
        scalar(sides[i].temperature_K,input.kinds.sides[i].temperature);
        scalar(sides[i].pressure_Pa,input.kinds.sides[i].pressure);
    }
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

    void observe(const PreparationRange& range,bool cached,std::optional<double> scalar={}) {
        if (callbacks.observe_range) callbacks.observe_range(callbacks.context,range,cached,scalar);
    }
    void merge(const PreparationEvidence& evidence,const std::string& side={}) {
        for (const auto& range:evidence.ranges) {
            const auto bound_side=side.empty()?range.side:side;
            const auto bound_stage=side.empty()?range.stage:"inlet";
            const auto bound_layout=side.empty()?range.layout:"scalar";
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
        PreparationRangeSample sample;sample.size=values.size();
        for (std::size_t i=0;i<values.size();++i) {
            const auto value=values[i];
            if (!std::isfinite(value)) {++sample.nonfinite;continue;}
            if (!sample.have_finite || value<sample.minimum) {sample.minimum=value;sample.minimum_index=i;}
            if (!sample.have_finite || value>sample.maximum) {sample.maximum=value;sample.maximum_index=i;}
            sample.have_finite=true;sample.low+=value<limits[0]?1:0;sample.high+=value>limits[1]?1:0;
        }
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

PropertyInput operand(const double& value,ScalarKind kind={}) {
    return {{&value,1},scalar(value,kind),kind.layout};
}
ScalarKind result_kind(const PropertyResult& value) {
    return {value.kind.precision,value.kind.strong,value.kind.strong?1u:0u};
}
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
double property(std::uint32_t quantity,const Inlet& inlet,const InletScalarKinds& kinds,
                const std::string& side,const std::string& stage,Records& records,const std::string& layout="scalar") {
    const auto temperature=inlet.temperature_K,pressure=inlet.pressure_Pa;
    if (inlet.fluid==Fluid::co2) return co2_pt({}, {&temperature,1},{&pressure,1},true).at(quantity);
    if (inlet.fluid==Fluid::sco2) {
        constexpr const char* keys[]{"D","V","L","C"};
        return sco2_pt(0,{keys[quantity]},{&temperature,1},{&pressure,1}).front();
    }
    const bool water=inlet.fluid==Fluid::water;
    constexpr std::array<Empirical,4> air{{Empirical::air_density,Empirical::air_viscosity,
                                         Empirical::air_conductivity,Empirical::air_cp}};
    constexpr const char* names[]{"density","viscosity","conductivity","cp"};
    if (water || quantity) {
        const auto name=std::string(water?"water_":"air_")+names[quantity];
        const auto& bounds=water?data::water_temperature_range:
            (quantity==3?data::air_cp_temperature_range:data::air_temperature_range);
        records.range({"property",name},side,stage,side=="unbound"?"source":layout,name,"T","K",bounds,temperature);
    }
    const auto getter=water?static_cast<Empirical>(4+quantity):air[quantity];
    const auto result=empirical(getter,operand(temperature,kinds.temperature),operand(pressure,kinds.pressure));
    records.floating(result.events);
    // The public inlet registry converts each property to a Python float.
    return result.values.front();
}
PropertyResult inlet_re(double rho,double velocity,double diameter,double mu,ScalarKind speed,Records& records) {
    auto result=reynolds(operand(rho),operand(velocity,speed),operand(diameter,numpy_double),operand(mu));
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
geometry::MaterialGeometry material_geometry(const Input&,const PreparationOptions&,const PreparationCallbacks& = {});
template<class Input,class Inlet>
void preflight(const Input& input,const PreparationOptions& options,const geometry::Geometry& geometry,
               const std::array<Inlet,2>& sides,Records& records) {
    for (std::size_t i=0;i<2;++i) {
        const auto& inlet=sides[i];const std::string side=i?"B":"A";
        const auto& kinds=input.kinds.sides[i];
        check_co2_inlet(inlet,i);
        const double rho=property(0,inlet,kinds,"unbound","unbound",records);
        const double mu=property(1,inlet,kinds,"unbound","unbound",records);
        const auto diameter=records.callbacks.geometry_cache?
            material_geometry(input,options,records.callbacks).geometry.hydraulic_diameter:geometry.hydraulic_diameter;
        const double re=inlet_re(rho,inlet.velocity_m_s,diameter,mu,kinds.velocity,records).values.front();
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
            const auto cp=property(3,inlet,kinds,"unbound","unbound",records);
            const auto conductivity=property(2,inlet,kinds,"unbound","unbound",records);
            const auto value=prandtl(operand(mu),operand(cp),operand(conductivity));
            records.floating(value.events);const double pr=value.values.front();
            records.range({"nu_pr","co2",topology_name(input.geometry.topology)},side,"inlet-preflight","scalar",
                          "CO2 inlet Nu","Pr","-",data::co2_nu_pr_range,pr);
            if (!(data::co2_nu_pr_range[0]<=pr && pr<=data::co2_nu_pr_range[1]))
                reasons.push_back("Fluid "+side+": Pr="+significant(pr,6)+" outside CO2 Nu window ["+
                                  significant(data::co2_nu_pr_range[0],6)+", "+significant(data::co2_nu_pr_range[1],6)+"].");
        }
        if (!reasons.empty() && !options.allow_extrapolation) {
            std::string text;for (const auto& reason:reasons) {if(!text.empty())text+=" | ";text+=reason;}
            throw PreparationError(1,std::move(text),1,static_cast<std::uint32_t>(i));
        }
        for (const auto& reason:reasons)
            records.emit({PreparationEventKind::warning,"", "[surrogate extrap] "+reason});
        // The original per-side record keeps the first preflight reason.
        if (!reasons.empty()) {
            records.warning(reasons.front());
            if (records.callbacks.observe_notice)
                records.callbacks.observe_notice(records.callbacks.context,1,static_cast<std::uint32_t>(i),0.,reasons.front());
        }
    }
}

template<class Input,class Inlet>
UniformInletProperties inlet_properties(const Input& input,const Inlet& inlet,std::size_t index,
                                       const geometry::MaterialGeometry& geometry,Records& records,
                                       std::array<ScalarKind,13>& output_kinds,const std::string& layout="scalar") {
    const std::string side=index?"B":"A";
    UniformInletProperties output{};
    const auto& kinds=input.kinds.sides[index];
    output.mu=property(1,inlet,kinds,side,"inlet",records,layout);
    output.k_f=property(2,inlet,kinds,side,"inlet",records,layout);
    output.rho=property(0,inlet,kinds,side,"inlet",records,layout);
    output.cp=property(3,inlet,kinds,side,"inlet",records,layout);
    double diameter=geometry.geometry.hydraulic_diameter,velocity=inlet.velocity_m_s;
    auto result=inlet_re(output.rho,velocity,diameter,output.mu,kinds.velocity,records);
    output.re=result.values.front();output_kinds[5]=result_kind(result);
    if (records.callbacks.observe_notice)
        records.callbacks.observe_notice(records.callbacks.context,0,static_cast<std::uint32_t>(index),output.re,{});
    result=prandtl(operand(output.mu),operand(output.cp),operand(output.k_f));
    records.floating(result.events);output.pr=result.values.front();
    output_kinds[4]=result_kind(result);
    std::array<double,4> extrema{};
    const auto route=inlet.fluid==Fluid::air?NuRoute::air_direct:inlet.fluid==Fluid::water?NuRoute::water:
                     inlet.fluid==Fluid::sco2?NuRoute::sco2:NuRoute::co2;
    double cell=input.geometry.cell_length_mm,diameter_mm=diameter*1000.;
    const auto co2=inlet.fluid==Fluid::co2;
    result=nu_inputs(route,operand(output.re,co2?ScalarKind{64,1,2}:output_kinds[5]),
        operand(output.pr,co2?ScalarKind{64,1,2}:output_kinds[4]),
        operand(cell,co2?ScalarKind{64,1,2}:input.kinds.cell_length),
        operand(diameter_mm,co2?ScalarKind{64,1,2}:numpy_double),{},extrema);
    records.floating(result.events);
    const auto prepared_kind=result_kind(result);
    double prepared_re=result.values.front(),pr=inlet.fluid==Fluid::air?data::pr_air:output.pr;
    const auto label=inlet.fluid==Fluid::air?"[Nu extrap] ":inlet.fluid==Fluid::water?"[water Nu extrap] ":
                     inlet.fluid==Fluid::sco2?"[sCO2 Nu extrap] ":"[CO2 Nu extrap] ";
    records.range({"nu",fluid_name(inlet.fluid),topology_name(input.geometry.topology)},side,"inlet",layout,
                  std::string(label)+topology_name(input.geometry.topology),"Re","-",re_range(inlet.fluid),output.re,{},false,extrema[0]);
    if (co2) records.range({"nu_pr","co2",topology_name(input.geometry.topology)},side,"inlet",layout,
                          std::string(label)+topology_name(input.geometry.topology),"Pr","-",data::co2_nu_pr_range,output.pr,{},true);
    const double alpha=inlet.fluid==Fluid::sco2 && input.sco2_nu.mode?
        *input.sco2_nu.alpha[static_cast<std::size_t>(input.geometry.topology)]:1.;
    result=nusselt(route,input.geometry.topology,operand(prepared_re,co2?ScalarKind{64,1,2}:prepared_kind),
        operand(pr,co2?ScalarKind{64,1,2}:ScalarKind{}),
        operand(cell,co2?ScalarKind{64,1,2}:input.kinds.cell_length),
        operand(diameter_mm,co2?ScalarKind{64,1,2}:numpy_double),g::weak(alpha));
    records.floating(result.events);output.nu=result.values.front();output_kinds[6]=co2?ScalarKind{}:result_kind(result);
    result=surface_transfer(operand(output.nu,output_kinds[6]),operand(output.k_f),operand(diameter,numpy_double));
    records.floating(result.events);output.surface_transfer_W_m2K=result.values.front();output_kinds[10]=result_kind(result);
    const auto drag=fixed_df(static_cast<std::uint32_t>(input.geometry.topology),cell,input.geometry.wall_thickness_mm);
    output.permeability_m2=drag.K;output.forchheimer_per_m=drag.cF;
    if (co2) {
        const auto factors=df_co2_factors();
        output.permeability_m2=df_apply_scale({&drag.K,1},{&factors.K,1},false).front();
        output.forchheimer_per_m=df_apply_scale({&drag.cF,1},{&factors.cF,1},false).front();
        output_kinds[7]=output_kinds[8]=numpy_double;
    }
    result=df_pressure_gradient(operand(output.rho),operand(output.mu),operand(velocity,kinds.velocity),
        operand(output.permeability_m2,output_kinds[7]),operand(output.forchheimer_per_m,output_kinds[8]));
    records.floating(result.events);output.pressure_gradient_Pa_m=result.values.front();output_kinds[9]=result_kind(result);
    double epsilon_a=geometry.geometry.epsilon_a;
    result=pore_conductivity(operand(epsilon_a,co2_geometry(input)?numpy_double:ScalarKind{}),operand(output.k_f));
    records.floating(result.events);output.fluid_conductivity_W_mK=result.values.front();output_kinds[11]=result_kind(result);
    output.solid_conductivity_W_mK=geometry.solid_conductivity;
    output_kinds[12]=solid_result_kind(input);
    return output;
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
    geometry::MaterialGeometry output;
    const auto calibration=geometry::calibration(model.topology);
    const bool co2=co2_geometry(input);
    if (co2) {
        static const std::array<geometry::Co2GeometryTable,2> tables{{geometry::Co2GeometryTable::from_generated(Topology::diamond),
                                                                   geometry::Co2GeometryTable::from_generated(Topology::gyroid)}};
        output=tables[static_cast<std::size_t>(model.topology)].evaluate(
            model.cell_length_mm,model.wall_thickness_mm,model.solid_conductivity_W_mK,options.chi_override);
    } else {
        const auto cell=scalar(model.cell_length_mm,input.kinds.cell_length);
        const auto wall=scalar(model.wall_thickness_mm,input.kinds.wall_thickness);
        const bool hit=callbacks.geometry_cache && callbacks.geometry_cache(callbacks.context,false,output.geometry);
        if (!hit) {
            output.geometry=geometry::standard_geometry(geometry_index(model.topology),calibration,
                cell.value,wall.value,cell.precision,g::result_precision(wall,cell));
            if (callbacks.geometry_cache) callbacks.geometry_cache(callbacks.context,true,output.geometry);
        }
        output.solid_conductivity=geometry::solid_conductivity(calibration.solid_tortuosity,
            output.geometry.epsilon,model.solid_conductivity_W_mK,options.chi_override,
            input.kinds.solid_conductivity.precision);
    }
    return output;
}

void prepare_ports(const PhysicalGrid2D& grid,PreparedSide2D& side) {
    const auto& port=side.inlet.port;
    const bool x=port.direction==0 || port.direction==1;
    side.cross_widths=x?grid.dy:grid.dx;
    side.stream_widths=x?grid.dx:grid.dy;
    if (port.direction==1 || port.direction==3) std::reverse(side.stream_widths.begin(),side.stream_widths.end());
    side.inlet_bounds={port.inlet_center_m-port.inlet_width_m/2.,port.inlet_center_m+port.inlet_width_m/2.};
    side.outlet_bounds={port.outlet_center_m-port.outlet_width_m/2.,port.outlet_center_m+port.outlet_width_m/2.};
    auto openings=g::port_fractions(side.cross_widths,g::weak(side.inlet_bounds[0]),g::weak(side.inlet_bounds[1]),port.uniform_inlet);
    side.inlet_geometry=std::move(openings[0]);side.inlet_profile=std::move(openings[1]);
    openings=g::port_fractions(side.cross_widths,g::weak(side.outlet_bounds[0]),g::weak(side.outlet_bounds[1]));
    side.outlet_geometry=std::move(openings[0]);side.outlet_profile=std::move(openings[1]);
    side.outlet_u_fraction=g::port_overlap(side.cross_widths,g::weak(side.outlet_bounds[0]),g::weak(side.outlet_bounds[1]),true);
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
std::vector<double> control_axis(std::size_t count,g::Scalar length) {
    if (count==1) return {g::divide(length,g::weak(2.)).value};
    if (length.strong==2) length={length.value,64,1};
    const auto divisor=g::weak(static_cast<double>(count-1));
    const auto step=g::divide(length,divisor);
    std::vector<double> values(count);
    for (std::size_t i=0;i<count;++i) {
        const auto index=g::checked({static_cast<double>(i),length.precision,1});
        values[i]=(step.value==0.?g::multiply(g::divide(index,divisor),length):g::multiply(index,step)).value;
    }
    values.back()=length.value;return values;
}
LocalGeometry2D local_geometry(const CaseInput2D& input,const PhysicalGrid2D& grid,
                               const PreparationOptions& options) {
    const auto& controls=*input.continuous;
    const auto x=control_axis(controls.nx,g::weak(input.grid.length_m)),y=control_axis(controls.ny,g::weak(input.grid.height_m));
    const auto xc=g::continuous_centres(grid.nx,g::weak(input.grid.length_m),&grid.dx);
    const auto yc=g::continuous_centres(grid.ny,g::weak(input.grid.height_m),&grid.dy);
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
            const double* axes[]{x.data(),y.data()};const double* samples[]{xc.data(),yc.data()};
            sampled[field]=fields::sample_tensor(2,counts,axes,values.data(),values.size(),
                static_cast<int>(controls.order),sizes,samples,limits[0],limits[1]);
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

PreparedCase2D prepare_case(const CaseInput2D& input,const PreparationOptions& options,
                              const PreparationCallbacks& callbacks,CaseScope scope,const InletGeometry2D* inlet_geometry=nullptr) {
    FloatingEnvironment floating_environment;
    if (callbacks.validate_host_input) callbacks.validate_host_input(callbacks.context,0,2);
    const auto inlets=validate(input,scope);
    PreparedCase2D output{};output.input=input;output.options=options;
    Records records{output.evidence,callbacks,{},{}};
    const auto& model=input.geometry;
    if (callbacks.validate_host_input) callbacks.validate_host_input(callbacks.context,1,2);
    output.uniform_geometry=inlet_geometry && !callbacks.geometry_cache?inlet_geometry->material:material_geometry(input,options,callbacks);
    const auto& uniform=output.uniform_geometry.geometry;
    output.hydraulic_radius_m=geometry::hydraulic_radius(uniform.hydraulic_diameter);
    preflight(input,options,uniform,inlets,records);
    // Full host preparation reads both conductivities before and after its mesh.
    if (input.continuous) for (std::size_t i=0;i<2;++i)
        property(2,inlets[i],input.kinds.sides[i],"unbound","unbound",records);
    output.grid=inlet_geometry?inlet_geometry->grid:physical_grid(input.grid,inlets);
    if (!inlet_geometry) record_grid(input,output.grid,records);
    std::optional<LocalGeometry2D> local;
    std::vector<DfPair> local_drag;
    if (input.continuous) {
        local=inlet_geometry?inlet_geometry->local:std::optional<LocalGeometry2D>{local_geometry(input,output.grid,options)};
        std::vector<double> epsilon_half(local->epsilon.size());
        for (std::size_t i=0;i<epsilon_half.size();++i) epsilon_half[i]=local->epsilon[i]*.5;
        for (std::size_t i=0;i<2;++i) {
            const auto conductivity=property(2,inlets[i],input.kinds.sides[i],"unbound","unbound",records);
            const std::vector<double> conductivity_values(epsilon_half.size(),conductivity);
            auto result=pore_conductivity({{epsilon_half.data(),epsilon_half.size()},{0.,64,1},3},
                {{conductivity_values.data(),conductivity_values.size()},g::weak(conductivity),0});
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
    for (std::size_t i=0;i<2;++i) {
        if (callbacks.validate_host_input)
            callbacks.validate_host_input(callbacks.context,2,static_cast<std::uint32_t>(i));
        auto& side=output.sides[i];
        if (!callbacks.inlet_cache) {
            side.properties=inlet_properties(input,inlets[i],i,output.uniform_geometry,records,side.property_kinds);
            continue;
        }
        PreparationInletCache cached{};
        const auto index=static_cast<std::uint32_t>(i);
        const bool hit=callbacks.inlet_cache(callbacks.context,false,index,inlets[i],input.kinds.sides[i].velocity,cached);
        if (!hit) {
            const auto geometry=material_geometry(input,options,callbacks);
            cached.geometry=geometry.geometry;
            Records local_records{cached.evidence,callbacks,{},{}};
            cached.properties=inlet_properties(input,inlets[i],i,geometry,local_records,cached.kinds);
            callbacks.inlet_cache(callbacks.context,true,index,inlets[i],input.kinds.sides[i].velocity,cached);
        }
        side.properties=cached.properties;side.property_kinds=cached.kinds;
        const auto calibration=geometry::calibration(model.topology);
        side.properties.solid_conductivity_W_mK=geometry::solid_conductivity(calibration.solid_tortuosity,
            cached.geometry.epsilon,model.solid_conductivity_W_mK,options.chi_override,
            co2_geometry(input)?64u:input.kinds.solid_conductivity.precision);
        side.property_kinds[12]=solid_result_kind(input);
        records.merge(cached.evidence,i?"B":"A");
    }
    if (callbacks.geometry_cache) output.uniform_geometry=material_geometry(input,options,callbacks);
    const auto cells=count(output.grid.nx,output.grid.ny);
    output.cell_length_m=g::multiply(scalar(model.cell_length_mm,input.kinds.cell_length),g::weak(1e-3)).value;
    output.wall_thickness_m=g::multiply(scalar(model.wall_thickness_mm,input.kinds.wall_thickness),g::weak(1e-3)).value;
    output.cell_length.assign(cells,output.cell_length_m);output.wall_thickness.assign(cells,output.wall_thickness_m);
    output.total_porosity.assign(cells,uniform.epsilon);
    output.solid_conductivity.assign(cells,output.uniform_geometry.solid_conductivity);
    output.hydraulic_radius.assign(cells,output.hydraulic_radius_m);
    output.field_kinds={input.kinds.cell_length,input.kinds.wall_thickness,ScalarKind{},
                        solid_result_kind(input),numpy_double};
    if (local) {
        for (std::size_t i=0;i<cells;++i) {
            output.cell_length[i]=local->cell_mm[i]*1e-3;output.wall_thickness[i]=local->wall_mm[i]*1e-3;
        }
        output.total_porosity=local->epsilon;output.solid_conductivity=local->solid;
        output.hydraulic_radius=local->radius;output.area_density=local->area;output.hydraulic_diameter=local->diameter;
        output.field_kinds.fill(numpy_double);
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
                  g::multiply(scalar(output.cell_length_m,input.kinds.cell_length),g::weak(1e3)).value,shape);
    records.range({"geometry","t_field_m"},"shared","prepared-geometry","physical-cell","fixed geometry domain","wall thickness","mm",
                  {df_data::df_t_nodes.front(),df_data::df_t_nodes.back()},
                  g::multiply(scalar(output.wall_thickness_m,input.kinds.wall_thickness),g::weak(1e3)).value,shape);
    }
    finish_warnings(records);
    return output;
}


g::Scalar flow_scalar(double value,ScalarKind kind) {
    const bool floating=kind.precision==16 || kind.precision==32 || kind.precision==64;
    const bool integer=kind.precision==8 || floating;
    if (!((kind.strong==0 && kind.precision==64 && kind.layout==0)
        || (kind.strong==1 && floating && (kind.layout==1 || kind.layout==2))
        || (kind.strong==2 && integer && (kind.layout==1 || kind.layout==2))))
        throw std::invalid_argument("inlet-flow scalar precision, strength or layout is invalid");
    return {value,kind.precision,kind.strong};
}

InletGeometry2D prepare_inlet_geometry(const CaseInput2D& input,ScalarKind depth_kind,
    const PreparationOptions& options,const PreparationCallbacks& callbacks,InletFlow2D& flow) {
    const auto inlets=validate(input,flow_scope(input),true);
    if (callbacks.validate_host_input) callbacks.validate_host_input(callbacks.context,1,2);
    InletGeometry2D output{};output.material=material_geometry(input,options,callbacks);
    output.grid=physical_grid(input.grid,inlets);
    Records records{flow.evidence,callbacks,{},{}};record_grid(input,output.grid,records);
    for (std::size_t i=0;i<2;++i) {output.sides[i].inlet=inlets[i];prepare_ports(output.grid,output.sides[i]);}
    if (input.continuous) output.local=local_geometry(input,output.grid,options);
    std::array<double,2> densities;
    for (std::size_t i=0;i<2;++i)
        densities[i]=property(0,inlets[i],input.kinds.sides[i],"unbound","unbound",records);
    for (std::size_t i=0;i<2;++i) {
        if (!input.physical_depth_m || !std::isfinite(*input.physical_depth_m) || *input.physical_depth_m<=0.)
            throw std::invalid_argument("2D total mass flow requires a positive physical Lz_m");
        if (input.geometry.delta_levelset!=0.)
            throw std::invalid_argument("2D fixed-flow optimization currently requires delta_levelset=0");
        const auto& side=output.sides[i];
        std::vector<double> epsilon(side.cross_widths.size(),output.material.geometry.epsilon);
        if (output.local) {
            const auto direction=side.inlet.port.direction;
            for (std::size_t j=0;j<epsilon.size();++j) {
                const auto index=direction==0?j:direction==1?(output.grid.nx-1)*output.grid.ny+j:
                    direction==2?j*output.grid.ny:j*output.grid.ny+output.grid.ny-1;
                epsilon[j]=output.local->epsilon[index];
            }
        }
        const auto field=[](const std::vector<double>& values) {return FlowValues{{values.data(),values.size()},64,1};};
        flow.capacities[i]=inlet_capacity_2d(field(epsilon),field(side.inlet_profile),field(side.inlet_geometry),
            field(side.cross_widths),g::weak(densities[i]),flow_scalar(*input.physical_depth_m,depth_kind));
        if (!std::isfinite(flow.capacities[i].value) || flow.capacities[i].value<=0.)
            throw std::invalid_argument("side "+std::string(i?"B":"A")+
                ": inlet density times open pore area must be finite and positive");
    }
    flow.have_capacities=true;finish_warnings(records);return output;
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

void resolve_speeds(const InletFlowRequest2D& request,const std::array<std::optional<double>,2>& targets,
                    InletFlow2D& flow) {
    for (std::size_t i=0;i<2;++i) {
        auto& inlet=flow.input.sides[i];auto& kind=flow.input.kinds.sides[i].velocity;
        if (targets[i]) {
            const auto target_kind=request.target_kinds[i];
            flow.speeds[i]=inlet_speed(flow_scalar(*targets[i],target_kind),flow.capacities[i]);
            inlet.velocity_m_s=flow.speeds[i].value;
            kind={flow.speeds[i].precision,flow.speeds[i].strong,flow.speeds[i].strong?1u:0u};
        } else flow.speeds[i]={inlet.velocity_m_s,kind.precision,kind.strong};
    }
    validate(flow.input,flow_scope(flow.input));
}
}  // namespace

PreparedCase2D prepare_case_2d(const CaseInput2D& input,const PreparationOptions& options,
    const PreparationCallbacks& callbacks,CaseScope scope) {
    return prepare_case(input,options,callbacks,scope);
}

InletFlow2D prepare_inlet_mass_capacities_2d(const CaseInput2D& input,ScalarKind depth_kind,
    const PreparationOptions& options,const PreparationCallbacks& callbacks) {
    FloatingEnvironment floating_environment;
    InletFlow2D output;output.input=input;
    prepare_inlet_geometry(input,depth_kind,options,callbacks,output);
    return output;
}

InletFlow2D resolve_inlet_flow_2d(const InletFlowRequest2D& request,
    const PreparationOptions& options,const PreparationCallbacks& callbacks) {
    FloatingEnvironment floating_environment;
    InletFlow2D output;const auto targets=flow_targets(request,output.input);
    if (!targets[0] && !targets[1]) return output;
    prepare_inlet_geometry(output.input,request.physical_depth_kind,options,callbacks,output);
    resolve_speeds(request,targets,output);return output;
}

PreparedFlowCase2D prepare_flow_case_2d(const InletFlowRequest2D& request,
    const PreparationOptions& options,const PreparationCallbacks& callbacks) {
    FloatingEnvironment floating_environment;
    PreparedFlowCase2D output;const auto targets=flow_targets(request,output.flow.input);
    if (!targets[0] && !targets[1]) {
        output.prepared=prepare_case(output.flow.input,options,callbacks,flow_scope(output.flow.input));
        return output;
    }
    const auto inlet_geometry=prepare_inlet_geometry(output.flow.input,request.physical_depth_kind,
        options,callbacks,output.flow);
    resolve_speeds(request,targets,output.flow);
    output.prepared=prepare_case(output.flow.input,options,callbacks,flow_scope(output.flow.input),&inlet_geometry);
    return output;
}

namespace {

g::Port checked_port_3d(g::Port port,const GridInput3D& input,const std::string& side) {
    const auto prefix="ComputeConfig.bc_"+side;
    if (!port.active) throw std::invalid_argument("native typed 3D preparation requires both fluid ports");
    const auto cross=port.direction<2?input.lengths[1]:input.lengths[0];
    auto width0=port.ends[0].width.value_or(g::weak(0.));
    auto width1=port.ends[1].width.value_or(g::weak(0.));
    if ((width0.value<=0.)!=(width1.value<=0.))
        throw std::invalid_argument(prefix+".in_w and out_w must both be positive, or both be <= 0 for a full-face port");
    if (!std::isfinite(width0.value) || !std::isfinite(width1.value))
        throw std::invalid_argument("port width must be finite before full-face normalization");
    if (width0.value<=0. && width1.value<=0.) for (auto& end:port.ends) {
        end.center=g::divide(cross,g::weak(2.));end.width=cross;
    }
    if (port.direction<0 || port.direction>5)
        throw std::invalid_argument(prefix+" is invalid: [error] pipe_bad_dir: pipe direction "+
                                    std::to_string(port.direction)+" not in 0..5");
    std::vector<std::string> errors;
    for (std::size_t end=0;end<2;++end) {
        auto& window=port.ends[end];
        window.center=window.center.value_or(g::weak(0.));window.width=window.width.value_or(g::weak(0.));
        const auto center=window.center->value,width=window.width->value;
        const std::string name=end?"out":"in";
        if (!std::isfinite(center) || !std::isfinite(width))
            errors.push_back("[error] pipe_"+name+"_invalid: "+name+" centre and width must be finite numbers");
        else if (center-width/2.<0. || center+width/2.>cross.value)
            errors.push_back("[error] pipe_"+name+"_out_of_domain: "+name+"_ctr ± "+name+"_w/2 = ["+
                significant(center-width/2.,3)+", "+significant(center+width/2.,3)+
                "] m leaves the cross-axis range [0, "+significant(cross.value,3)+"].");
    }
    const auto cross2=port.direction<4?input.lengths[2]:input.lengths[1];
    for (std::size_t end=0;end<2;++end) {
        const auto& window=port.ends[end];const std::string name=end?"out":"in";
        if (!window.center2 && !window.width2) continue;
        if (!window.center2 || !window.width2) {
            errors.push_back("[error] pipe_"+name+"_z_incomplete: "+name+" second-cross-axis centre and width must be set together");
            continue;
        }
        const auto center=window.center2->value,width=window.width2->value;
        if (!std::isfinite(center) || !std::isfinite(width))
            errors.push_back("[error] pipe_"+name+"_z_invalid: "+name+" second-cross-axis centre and width must be finite numbers");
        else if (width<=0.)
            errors.push_back("[error] pipe_"+name+"_z_w_nonpos: "+name+"_z_w = "+decimal(width)+" must be > 0");
        else if (center-width/2.<0. || center+width/2.>cross2.value)
            errors.push_back("[error] pipe_"+name+"_z_out_of_domain: "+name+"_z_ctr ± "+name+"_z_w/2 = ["+
                significant(center-width/2.,3)+", "+significant(center+width/2.,3)+"] m leaves "+
                (port.direction<4?"Z":"Y")+"-range [0, "+significant(cross2.value,3)+"].");
    }
    if (!errors.empty()) {
        std::string text=prefix+" is invalid: ";
        for (std::size_t i=0;i<errors.size();++i) {if (i) text+="; ";text+=errors[i];}
        throw std::invalid_argument(text);
    }
    return port;
}

CaseInput3D validate_3d(CaseInput3D input,bool allow_mass=false,bool velocities=true) {
    if (input.continuous) {
        if (input.geometry_mode!=1)
            throw std::invalid_argument("native continuous 3D preparation requires geometry_mode=1");
        validate_controls(*input.continuous,input.continuous->nz.value_or(1));
    } else if (input.geometry_mode || input.geometry.delta_levelset!=0.)
        throw std::invalid_argument("native 3D preparation currently requires symmetric uniform geometry");
    validate_nu(input.sco2_nu);
    if (input.continuous && input.geometry.delta_levelset!=0.)
        throw std::invalid_argument("Continuous spatial fields require delta_levelset=0");
    if (input.df_mode>1) throw std::invalid_argument("native 3D preparation DF mode must be CFD or experimental");
    if (allow_mass) for (std::size_t i=0;i<2;++i) if (input.sides[i].mass_flow_kg_s)
        positive(*input.sides[i].mass_flow_kg_s,std::string("fluid_")+(i?"B":"A")+".mass_flow_kg_s");
    const char* dimensions[]{"geometry.L_dom_m","geometry.H_dom_m","geometry.Lz_m"};
    for (std::size_t axis=0;axis<2;++axis) {
        input.grid.lengths[axis]=g::checked(input.grid.lengths[axis]);
        positive(input.grid.lengths[axis].value,dimensions[axis]);
    }
    const auto& model=input.geometry;
    positive(model.cell_length_mm,"geometry.L_cell_mm");
    positive(model.wall_thickness_mm,"geometry.t_wall_mm");
    positive(model.solid_conductivity_W_mK,"geometry.k_s_W_mK");
    input.grid.lengths[2]=g::checked(input.grid.lengths[2]);
    positive(input.grid.lengths[2].value,dimensions[2]);
    // The original 3D parser converts only depth to a Python float.
    input.grid.lengths[2]=g::weak(input.grid.lengths[2].value);
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
    if (model.cell_length_mm<df_data::df_L_nodes.front() || model.cell_length_mm>df_data::df_L_nodes.back()
        || model.wall_thickness_mm<df_data::df_t_nodes.front() || model.wall_thickness_mm>df_data::df_t_nodes.back())
        throw std::invalid_argument("V2 geometry must lie inside the CFD grid: 4 <= L <= 8 mm, 0.3 <= t <= 0.6 mm");
    for (std::size_t i=0;i<2;++i) {
        const auto& inlet=input.sides[i];fluid_name(inlet.fluid);
        if (inlet.fluid==Fluid::sco2) {
            if (!(data::sco2_temperature_range[0]<=inlet.temperature_K && inlet.temperature_K<=data::sco2_temperature_range[1]))
                throw PreparationError(1,std::string("sCO2 fluid ")+(i?"B":"A")+" temperature must be 280..700 K",1,static_cast<std::uint32_t>(i));
            if (!(data::sco2_pressure_range[0]<=inlet.pressure_Pa && inlet.pressure_Pa<=data::sco2_pressure_range[1]))
                throw PreparationError(1,std::string("sCO2 fluid ")+(i?"B":"A")+" pressure must be 7.9..16 MPa",1,static_cast<std::uint32_t>(i));
        }
    }
    if (velocities) for (std::size_t i=0;i<2;++i) positive(input.sides[i].velocity_m_s,std::string("fluid_")+(i?"B":"A")+".u_mps");
    if (velocities && input.continuous && input.df_mode) {
        const bool shanghai=model.topology==Topology::gyroid && input.sides[0].fluid==Fluid::air
            && input.sides[1].fluid==Fluid::water && std::abs(model.cell_length_mm-7.)<=1e-12
            && std::abs(model.wall_thickness_mm-.6)<=1e-12;
        if (!shanghai && (input.sides[0].fluid!=Fluid::co2 || input.sides[1].fluid!=Fluid::co2))
            throw std::invalid_argument("experimental calibration currently requires uniform L/t; "
                "continuous Shanghai Gyroid air/water fields may use "
                "the 7/0.6 calibration as an exploratory extrapolation");
    }
    if (velocities && input.df_mode) for (std::size_t i=0;i<2;++i) if (input.sides[i].fluid!=Fluid::co2) {
        const auto selected=experiment_selection(input,input.sides[i],i,input.continuous.has_value()).first;
        if (selected.scope) for (std::size_t axis=0;axis<3;++axis) {
            const auto length=input.grid.lengths[axis].value,target=df_data::hx_domain_m[axis];
            if (std::abs(length-target)>1e-9*std::max(std::abs(length),std::abs(target)))
                throw PreparationError(1,"experimental calibration side "+std::string(i?"B":"A")+
                    " is HX-effective and requires delta=0 with the matching 0.182 x 0.042 x 0.042 m campaign domain",1,static_cast<std::uint32_t>(i));
        }
    }
    for (std::size_t axis=0;axis<3;++axis) if (input.grid.lengths[axis].value>10.) {
        const char* names[]{"L","H","Lz"};
        throw std::invalid_argument(std::string("Domain dimension '")+names[axis]+"'="+
            decimal(input.grid.lengths[axis].value)+" m exceeds 10.0 m. Likely unit slip — GUI expects meters here, while L_cell and t use millimeters. Re-check input.");
    }
    topology_name(model.topology);
    scalar(model.cell_length_mm,input.kinds.cell_length);scalar(model.wall_thickness_mm,input.kinds.wall_thickness);
    scalar(model.solid_conductivity_W_mK,input.kinds.solid_conductivity);
    for (std::size_t i=0;i<2;++i) {
        const auto& inlet=input.sides[i];const auto& kinds=input.kinds.sides[i];
        if (velocities) scalar(inlet.velocity_m_s,kinds.velocity);
        scalar(inlet.temperature_K,kinds.temperature);scalar(inlet.pressure_Pa,kinds.pressure);
    }
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

void physical_grid_3d(PreparedCase3D& output) {
    const auto& input=output.input.grid;
    const g::Scalars lengths(input.lengths.begin(),input.lengths.end());
    const std::vector<g::Port> ports{output.input.sides[0].port,output.input.sides[1].port};
    for (std::size_t axis=0;axis<3;++axis) {
        if (!input.port_wall_refine) output.widths[axis]=g::uniform(input.counts[axis],lengths[axis]);
        else {
            const auto knots=unique(g::port_edges(lengths,ports,axis));
            g::Scalars outer{g::weak(0.)};outer.insert(outer.end(),knots.begin(),knots.end());outer.push_back(lengths[axis]);
            const auto keep=g::aligned_filter(lengths[axis],knots);
            g::Scalars bulk{g::weak(0.),lengths[axis]};
            for (std::size_t i=0;i<knots.size();++i) if (keep[i]) bulk.push_back(knots[i]);
            std::size_t minimum=0;
            output.widths[axis]=g::port_wall_axis(3,input.counts[axis],outer,unique(std::move(bulk)),minimum,axis);
        }
    }
    const auto cells=count(count(output.widths[0].size(),output.widths[1].size()),output.widths[2].size());
    if (cells>input.max_cells)
        throw std::invalid_argument("3D grid "+std::to_string(output.widths[0].size())+"x"+
            std::to_string(output.widths[1].size())+"x"+std::to_string(output.widths[2].size())+
            " exceeds the "+std::to_string(input.max_cells)+"-cell cap");
}

void continuous_geometry_3d(PreparedCase3D& output) {
    const auto& input=output.input;const auto& controls=*input.continuous;
    const auto nx=output.widths[0].size(),ny=output.widths[1].size(),nz=output.widths[2].size();
    const auto dimension=controls.nz?3u:2u;
    const std::size_t counts[]{controls.nx,controls.ny,controls.nz.value_or(1)};
    const std::size_t sizes[]{nx,ny,nz};
    std::array<std::vector<double>,3> axes,centres;
    for (std::size_t axis=0;axis<dimension;++axis) {
        const auto length=input.grid.lengths[axis];const auto& widths=output.widths[axis];
        const double total=0.+tpmshx::detail::contiguous_sum({widths.data(),widths.size()});
        if (!(std::abs(total-length.value)<=g::multiply(g::weak(1e-12),length).value))
            throw std::invalid_argument("cell widths must be finite, positive and cover the field domain");
        axes[axis]=control_axis(counts[axis],length);
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
    output.length_kinds={ScalarKind{64,1,2},ScalarKind{64,1,2}};
}

void air_spatial_ranges_3d(const PreparedCase3D& output,std::size_t side,Records& records) {
    const auto& input=output.input;const auto& inlet=input.sides[side];const auto& kinds=input.kinds.sides[side];
    const auto name=std::string(side?"B":"A");
    const auto mu=property(1,inlet,kinds,name,"inlet",records,"scalar-zoned-call");
    property(2,inlet,kinds,name,"inlet",records,"scalar-zoned-call");
    const auto rho=property(0,inlet,kinds,name,"inlet",records,"scalar-zoned-call");
    property(3,inlet,kinds,name,"inlet",records,"scalar-zoned-call");
    PropertyResult re;re.values.reserve(output.hydraulic_diameter.size());
    for (const auto diameter:output.hydraulic_diameter)
        re.values.push_back(reynolds_point({g::weak(rho)},
            {scalar(inlet.velocity_m_s,kinds.velocity),0.,0,kinds.velocity.layout},
            {{diameter,64,1},0.,0,3},{g::weak(mu)},re.events).real.value);
    records.floating(re.events);
    const auto topology=std::string(topology_name(input.geometry.topology));
    for (const auto value:re.values)
        records.range({"nu","air",topology},name,"inlet","scalar-zoned-call","[Nu extrap] "+topology,
            "Re","-",re_range(Fluid::air),value);
    records.range({"nu_raw","air",topology},name,"inlet","real-cell(x,y,z)-bulk-Re","[air Nu raw] "+topology,
        "Re","-",re_range(Fluid::air),re.values,{output.widths[0].size(),output.widths[1].size(),output.widths[2].size()});
}

void prepare_geometry_3d(PreparedCase3D& output,Records& records,bool check_speed) {
    const auto& input=output.input;const auto& model=input.geometry;const auto& options=output.options;
    output.uniform_geometry=material_geometry(input,options);
    for (std::size_t i=0;i<2;++i) water_inlet_3d(input.sides[i],i,"pipeline inlet");
    if (check_speed) preflight(input,options,output.uniform_geometry.geometry,input.sides,records);
    physical_grid_3d(output);
    const auto cells=count(count(output.widths[0].size(),output.widths[1].size()),output.widths[2].size());
    const auto& uniform=output.uniform_geometry.geometry;
    if (input.continuous) continuous_geometry_3d(output);
    else {
        output.total_porosity.assign(cells,uniform.epsilon);
        output.side_porosity.assign(cells,uniform.epsilon_a);
        const auto drag=fixed_df_batch(static_cast<std::uint32_t>(model.topology),
            {&model.cell_length_mm,1},{&model.wall_thickness_mm,1}).front();
        output.permeability.assign(cells,drag.K);output.forchheimer.assign(cells,drag.cF);
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
            side.properties[j]=property(order[j],inlet,input.kinds.sides[i],"unbound","unbound",records);
    }
    const auto calibration=geometry::calibration(model.topology);
    if (input.continuous) {
        output.solid_conductivity=geometry::solid_conductivity(calibration.solid_tortuosity,
            {output.total_porosity.data(),cells},model.solid_conductivity_W_mK,options.chi_override,64);
    } else {
        output.cell_length.assign(cells,g::multiply(scalar(model.cell_length_mm,input.kinds.cell_length),g::weak(1e-3)).value);
        output.wall_thickness.assign(cells,g::multiply(scalar(model.wall_thickness_mm,input.kinds.wall_thickness),g::weak(1e-3)).value);
        output.length_kinds={input.kinds.cell_length,input.kinds.wall_thickness};
        const auto solid=geometry::solid_conductivity(calibration.solid_tortuosity,uniform.epsilon,
            model.solid_conductivity_W_mK,options.chi_override,64);
        output.solid_conductivity.assign(cells,solid);
    }
}

void finish_case_3d(PreparedCase3D& output,Records& records) {
    const auto& input=output.input;
    const auto cells=output.total_porosity.size();
    for (std::size_t i=0;i<2;++i) if (input.sides[i].fluid==Fluid::air) {
        if (input.continuous) air_spatial_ranges_3d(output,i,records);
        else {
            std::array<ScalarKind,13> kinds{};
            inlet_properties(input,input.sides[i],i,output.uniform_geometry,records,kinds,"scalar-hv-bulk");
        }
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
    model_evidence(input,output.evidence,input.continuous.has_value());
    const std::vector<std::size_t> shape{output.widths[0].size(),output.widths[1].size(),output.widths[2].size()};
    if (input.continuous) {
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
            g::multiply(scalar(output.cell_length.front(),input.kinds.cell_length),g::weak(1e3)).value,shape);
        records.range({"geometry","t_field_m"},"shared","prepared-geometry","physical-cell","fixed geometry domain","wall thickness","mm",
            {df_data::df_t_nodes.front(),df_data::df_t_nodes.back()},
            g::multiply(scalar(output.wall_thickness.front(),input.kinds.wall_thickness),g::weak(1e3)).value,shape);
    }
    finish_warnings(records);
}

void capacities_3d(const PreparedCase3D& prepared,InletFlow3D& flow) {
    const std::array<std::size_t,3> shape{{prepared.widths[0].size(),prepared.widths[1].size(),prepared.widths[2].size()}};
    const auto field=[](const std::vector<double>& values) {return FlowValues{{values.data(),values.size()},64,1};};
    for (std::size_t i=0;i<2;++i) {
        const auto& side=prepared.sides[i];
        flow.capacities[i]=inlet_capacity_3d(field(prepared.side_porosity),shape,prepared.input.sides[i].port.direction,
            field(prepared.widths[static_cast<std::size_t>(side.axes[0])]),
            field(prepared.widths[static_cast<std::size_t>(side.axes[2])]),field(side.openings[0]),g::weak(side.properties[0]));
        if (!std::isfinite(flow.capacities[i].value) || flow.capacities[i].value<=0.)
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

void resolve_speeds(const InletFlowRequest3D& request,const std::array<std::optional<double>,2>& targets,
                    InletFlow3D& flow) {
    for (std::size_t i=0;i<2;++i) {
        auto& inlet=flow.input.sides[i];auto& kind=flow.input.kinds.sides[i].velocity;
        if (targets[i]) {
            flow.speeds[i]=inlet_speed(flow_scalar(*targets[i],request.target_kinds[i]),flow.capacities[i]);
            inlet.velocity_m_s=flow.speeds[i].value;
            kind={flow.speeds[i].precision,flow.speeds[i].strong,flow.speeds[i].strong?1u:0u};
        } else flow.speeds[i]={inlet.velocity_m_s,kind.precision,kind.strong};
    }
    flow.input=validate_3d(flow.input,true);
}
}  // namespace

PreparedCase3D prepare_case_3d(const CaseInput3D& requested,const PreparationOptions& options,
                             const PreparationCallbacks& callbacks) {
    FloatingEnvironment floating_environment;
    PreparedCase3D output{};output.input=validate_3d(requested);output.options=options;
    Records records{output.evidence,callbacks,{},{}};
    prepare_geometry_3d(output,records,true);finish_case_3d(output,records);
    return output;
}

InletFlow3D prepare_inlet_mass_capacities_3d(const CaseInput3D& input,const PreparationOptions& options,
                                          const PreparationCallbacks& callbacks) {
    FloatingEnvironment floating_environment;
    InletFlow3D output;output.input=input;
    PreparedCase3D prepared{};prepared.input=validate_3d(input,true,false);prepared.options=options;
    Records records{prepared.evidence,callbacks,{},{}};
    prepare_geometry_3d(prepared,records,false);capacities_3d(prepared,output);finish_warnings(records);
    output.evidence=std::move(prepared.evidence);return output;
}

InletFlow3D resolve_inlet_flow_3d(const InletFlowRequest3D& request,const PreparationOptions& options,
                               const PreparationCallbacks& callbacks) {
    FloatingEnvironment floating_environment;
    InletFlow3D output;const auto targets=flow_targets(request,output.input);
    if (!targets[0] && !targets[1]) return output;
    output=prepare_inlet_mass_capacities_3d(output.input,options,callbacks);
    resolve_speeds(request,targets,output);return output;
}

PreparedFlowCase3D prepare_flow_case_3d(const InletFlowRequest3D& request,const PreparationOptions& options,
                                     const PreparationCallbacks& callbacks) {
    FloatingEnvironment floating_environment;
    PreparedFlowCase3D output;const auto targets=flow_targets(request,output.flow.input);
    if (!targets[0] && !targets[1]) {
        output.prepared=prepare_case_3d(output.flow.input,options,callbacks);return output;
    }
    auto& prepared=output.prepared;
    prepared.input=validate_3d(output.flow.input,true,false);prepared.options=options;
    Records records{prepared.evidence,callbacks,{},{}};
    prepare_geometry_3d(prepared,records,false);capacities_3d(prepared,output.flow);
    output.flow.evidence=prepared.evidence;
    Records preliminary{output.flow.evidence,callbacks,records.warning_order,records.plain_warnings};
    finish_warnings(preliminary);
    resolve_speeds(request,targets,output.flow);
    prepared.input=output.flow.input;
    preflight(prepared.input,options,prepared.uniform_geometry.geometry,prepared.input.sides,records);
    finish_case_3d(prepared,records);return output;
}

}  // namespace tpmshx::preparation
