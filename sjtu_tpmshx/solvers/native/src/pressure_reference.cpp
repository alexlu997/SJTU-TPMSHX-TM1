#include "tpmshx/pressure_reference.hpp"
#include "tpmshx/model_coefficients.hpp"
#include "contiguous_sum.hpp"

#include <algorithm>
#include <cmath>
#include <iomanip>
#include <limits>
#include <sstream>

namespace tpmshx {
namespace {
namespace mc = model_coefficients;

void require_size(ArrayView<const double> values, std::size_t size, const char* name) {
    if (values.size != size || (size && !values.data))
        throw std::invalid_argument(std::string(name) + " has incorrect extent");
}
void require_widths(ArrayView<const double> widths, std::size_t size) {
    require_size(widths, size, "cell widths");
    for (std::size_t i=0; i<size; ++i)
        if (!std::isfinite(widths[i]) || widths[i] <= 0)
            throw std::invalid_argument("cell widths must be finite and positive");
}
std::string number(double value, int precision=6, bool fixed=false) {
    std::ostringstream out;
    if (fixed) out << std::fixed;
    out << std::setprecision(precision) << value;
    return out.str();
}
}  // namespace

std::vector<double> port_overlap_1d(ArrayView<const double> widths,
                                  double lo, double hi, bool staggered) {
    if (!widths.size || !std::isfinite(lo) || !std::isfinite(hi))
        throw std::invalid_argument("port overlap requires nonempty widths and finite endpoints");
    require_widths(widths, widths.size);
    std::vector<double> edges(widths.size+1, 0.0);
    for (std::size_t i=0; i<widths.size; ++i) edges[i+1]=edges[i]+widths[i];
    const double length=edges.back();
    if (staggered) {
        for (std::size_t i=0; i<widths.size; ++i) edges[i+1]-=widths[i]/2;
        edges.push_back(length);
    }
    const double scale=std::max({std::abs(lo),std::abs(hi),std::abs(length)});
    const double roundoff=8*(std::nextafter(scale,std::numeric_limits<double>::infinity())-scale);
    std::vector<double> result(edges.size()-1);
    for (std::size_t i=0; i<result.size(); ++i) {
        double overlap=std::min(edges[i+1],hi)-std::max(edges[i],lo);
        if (std::abs(overlap)<=roundoff) overlap=0;
        const double width=staggered ? edges[i+1]-edges[i] : widths[i];
        result[i]=std::clamp(overlap/width,0.0,1.0);
    }
    return result;
}

std::pair<std::vector<double>,std::vector<double>> port_fractions_1d(
    ArrayView<const double> widths,double lo,double hi,bool uniform) {
    auto raw=port_overlap_1d(widths,lo,hi);
    auto profile=raw;
    if (!uniform) for (std::size_t i=0;i<raw.size();++i) if(raw[i]>0.99) {
        for (std::size_t d=1;d<5;++d) {
            if ((i>=d && raw[i-d]<0.01) || (i+d<raw.size() && raw[i+d]<0.01)) {
                profile[i]=1.0-0.8*std::exp(-static_cast<double>(d));
                break;
            }
        }
    }
    return {std::move(raw),std::move(profile)};
}

PressurePortState inlet_pressure_state(
    const GridView& grid, ArrayView<const double> pressure,
    ArrayView<const double> inlet_fraction, ArrayView<const double> outlet_fraction,
    double reference_Pa, double specified_Pa) {
    if (!grid.nx || !grid.ny || !grid.nz ||
        grid.nx>std::numeric_limits<std::size_t>::max()/grid.ny ||
        grid.nx*grid.ny>std::numeric_limits<std::size_t>::max()/grid.nz)
        throw std::invalid_argument("pressure grid extents must be positive and representable");
    require_widths(grid.dx,grid.nx);
    require_widths(grid.dy,grid.ny);
    require_widths(grid.dz,grid.nz);
    require_size(pressure,grid.nx*grid.ny*grid.nz,"pressure");
    require_size(inlet_fraction,grid.nx*grid.nz,"inlet fraction");
    require_size(outlet_fraction,grid.nx*grid.nz,"outlet fraction");
    const double ri=grid.ny>1 ? grid.dy[0]/(grid.dy[0]+grid.dy[1]) : 0;
    const double ro=grid.ny>1 ? grid.dy[grid.ny-1]/(grid.dy[grid.ny-2]+grid.dy[grid.ny-1]) : 0;
    std::vector<double> inlet_products,outlet_products,inlet_weights,outlet_weights;
    for (std::size_t i=0; i<grid.nx; ++i) for (std::size_t k=0; k<grid.nz; ++k) {
        const auto f=i*grid.nz+k, first=i*grid.ny*grid.nz+k;
        const auto last=first+(grid.ny-1)*grid.nz;
        if (!std::isfinite(inlet_fraction[f]) || !std::isfinite(outlet_fraction[f]) ||
            inlet_fraction[f]<0 || inlet_fraction[f]>1 ||
            outlet_fraction[f]<0 || outlet_fraction[f]>1)
            throw std::invalid_argument("geometric port fractions must be finite in [0,1]");
        const double pin=grid.ny>1 ? (1+ri)*pressure[first]-ri*pressure[first+grid.nz] : pressure[first];
        const double pout=grid.ny>1 ? (1+ro)*pressure[last]-ro*pressure[last-grid.nz] : pressure[last];
        const double area=grid.dx[i]*grid.dz[k];
        const double wi=inlet_fraction[f]*area;
        const double wo=outlet_fraction[f]*area;
        if (wi>0) { inlet_products.push_back(pin*wi); inlet_weights.push_back(wi); }
        if (wo>0) { outlet_products.push_back(pout*wo); outlet_weights.push_back(wo); }
    }
    // The reference takes a contiguous masked copy before np.average. Retain
    // its product and weight reductions before the coupled P-squared update.
    const double inlet_sum=detail::contiguous_sum({inlet_products.data(),inlet_products.size()});
    const double outlet_sum=detail::contiguous_sum({outlet_products.data(),outlet_products.size()});
    const double inlet_area=detail::contiguous_sum({inlet_weights.data(),inlet_weights.size()});
    const double outlet_area=detail::contiguous_sum({outlet_weights.data(),outlet_weights.size()});
    if (!(inlet_area>0) || !(outlet_area>0))
        throw std::invalid_argument("pressure state requires positive geometric port areas");
    const double inlet_gauge=inlet_sum/inlet_area, outlet_gauge=outlet_sum/outlet_area;
    double minimum=pressure[0];
    for (std::size_t i=1; i<pressure.size; ++i) {
        if (std::isnan(pressure[i])) { minimum=pressure[i]; break; }
        minimum=std::min(minimum,pressure[i]);
    }
    const double realized=reference_Pa+inlet_gauge;
    const double residual=(realized-specified_Pa)/specified_Pa;
    return {specified_Pa,realized,reference_Pa+outlet_gauge,outlet_gauge,
            reference_Pa+minimum,residual,mc::inlet_pressure_relative_tolerance,
            std::isfinite(residual) && std::abs(residual)<mc::inlet_pressure_relative_tolerance,
            "geometric open-area mean at physical port faces"};
}

double pressure_shooting_target_sq(const PressurePortState& state) {
    return state.specified_Pa*state.specified_Pa-
        (state.realized_Pa*state.realized_Pa-state.outlet_Pa*state.outlet_Pa);
}
double pressure_initial_reference(double outlet_squared_Pa, double inlet_Pa,
                                  std::vector<PressureIteration>& history) {
    if (!std::isfinite(outlet_squared_Pa) || !std::isfinite(inlet_Pa) ||
        inlet_Pa<=mc::pressure_floor_pa)
        throw std::invalid_argument("pressure initialization requires finite estimates and inlet pressure above the floor");
    const bool usable=outlet_squared_Pa>mc::pressure_floor_pa*mc::pressure_floor_pa;
    const double anchor=usable ? std::sqrt(outlet_squared_Pa) : inlet_Pa;
    history.push_back({"initialization",anchor,outlet_squared_Pa,std::nullopt,std::nullopt,
                       std::nullopt,usable ? "1d" : "inlet-pressure"});
    return anchor;
}
double pressure_shooting_reference(const PressurePortState& state,
                                   std::vector<PressureIteration>& history) {
    for (double value : {state.specified_Pa,state.realized_Pa,state.outlet_Pa,
                         state.outlet_gauge_Pa,state.minimum_Pa})
        if (!std::isfinite(value))
            throw std::runtime_error("pressure iteration received a non-finite pressure state");
    const double lower=std::max(mc::pressure_floor_pa,
        state.outlet_Pa-state.minimum_Pa+mc::pressure_floor_pa);
    const double target=pressure_shooting_target_sq(state);
    const double pout_sq=state.outlet_Pa*state.outlet_Pa,delta=target-pout_sq;
    double alpha=1;
    if (delta<0) {
        if (state.outlet_Pa<=lower)
            throw std::runtime_error("pressure iteration cannot lower an outlet already at the pressure floor");
        alpha=std::min(1.0,0.5*(pout_sq-lower*lower)/-delta);
    }
    const double next_sq=pout_sq+alpha*delta;
    if (next_sq<=lower*lower)
        throw std::runtime_error("pressure iteration has no positive admissible update");
    const double anchor=std::sqrt(next_sq)-state.outlet_gauge_Pa;
    history.push_back({"update",anchor,std::nullopt,state.relative_error,target,alpha,std::nullopt});
    return anchor;
}

double predict_outlet_p_sq(double inlet_Pa,double temperature_K,double drag_estimate,
                          double length_m,double gas_constant) {
    return inlet_Pa*inlet_Pa-2.0*gas_constant*temperature_K*drag_estimate*length_m;
}
double predict_outlet_p_sq(double inlet_Pa,double temperature_K,double drag_estimate,double length_m) {
    return predict_outlet_p_sq(inlet_Pa,temperature_K,drag_estimate,length_m,mc::envelope_r_air);
}
double mach(double speed,double temperature_K,double gas_constant,double gamma) {
    const double square=gamma*gas_constant*temperature_K;
    if (square<0) throw std::domain_error("math domain error");
    const double sound=std::sqrt(square);
    if (sound==0) throw std::domain_error("float division by zero");
    return speed/sound;
}
double mach(double speed,double temperature_K) {
    return mach(speed,temperature_K,mc::envelope_r_air,mc::envelope_gamma_air);
}
double mach_field_max(ArrayView<const double> speed,ArrayView<const double> temperature,
                      double gas_constant,double gamma) {
    if (!speed.size) return 0;
    if (!speed.data || !temperature.data || (temperature.size!=1 && temperature.size!=speed.size))
        throw std::invalid_argument("Mach temperature must be scalar or match speed extent");
    double maximum=-std::numeric_limits<double>::infinity();
    for (std::size_t i=0; i<speed.size; ++i) {
        const double temp=std::max(temperature[temperature.size==1 ? 0 : i],1.0);
        const double value=speed[i]/std::sqrt(gamma*gas_constant*temp);
        if (std::isnan(value)) return value;
        maximum=std::max(maximum,value);
    }
    return maximum;
}
double mach_field_max(ArrayView<const double> speed,ArrayView<const double> temperature) {
    return mach_field_max(speed,temperature,mc::envelope_r_air,mc::envelope_gamma_air);
}

EnvelopeAssessment assess_solution_validity(double minimum_Pa,double vmax,double reference_temperature_K,
    double mach_limit,double gas_constant,double gamma,std::optional<double> ma_max) {
    EnvelopeAssessment result{true,{}};
    if (!std::isfinite(minimum_Pa))
        result.reasons.push_back("non-finite absolute pressure (min P = "+number(minimum_Pa)+
            ") \xE2\x80\x94 the solver diverged (NaN/inf field)");
    else if (minimum_Pa<=mc::pressure_floor_pa*(1.0+1.0e-6))
        result.reasons.push_back("pressure clipped to the "+number(mc::pressure_floor_pa,0,true)+
            " Pa floor (min absolute P = "+number(minimum_Pa,1,true)+
            " Pa) \xE2\x80\x94 the solve left the compressible envelope");
    const double ma=ma_max ? *ma_max : mach(vmax,reference_temperature_K,gas_constant,gamma);
    if (!std::isfinite(ma))
        result.reasons.push_back("non-finite Mach (Ma = "+number(ma)+
            ") \xE2\x80\x94 the solver diverged (NaN/inf velocity or temperature field)");
    else if (ma>=mach_limit)
        result.reasons.push_back("supersonic: Ma_max = "+number(ma,2,true)+" >= "+number(mach_limit));
    result.valid=result.reasons.empty();
    return result;
}
EnvelopeAssessment assess_solution_validity(double minimum_Pa,double vmax,double reference_temperature_K,
    double mach_limit,std::optional<double> ma_max) {
    return assess_solution_validity(minimum_Pa,vmax,reference_temperature_K,mach_limit,
                                   mc::envelope_r_air,mc::envelope_gamma_air,ma_max);
}
EnvelopeAssessment gate_solution(double minimum_Pa,double vmax,double reference_temperature_K,
    const std::string& mode,const std::string& dimensions,double mach_limit,
    double gas_constant,double gamma,std::optional<double> ma_max) {
    if (mode!="raise" && mode!="warn" && mode!="off")
        throw std::invalid_argument("unknown envelope mode '"+mode+"'; expected one of ('raise', 'warn', 'off')");
    auto result=assess_solution_validity(minimum_Pa,vmax,reference_temperature_K,mach_limit,
                                         gas_constant,gamma,ma_max);
    if (mode=="raise" && !result.valid) {
        std::string message=dimensions+" solver returned a non-physical field (caught post-solve): ";
        for (std::size_t i=0; i<result.reasons.size(); ++i) {
            if (i) message+="; ";
            message+=result.reasons[i];
        }
        throw ChokedFlowError(message+". Reduce the inlet velocity, shorten the streamwise domain, or raise the inlet pressure.");
    }
    return result;
}
EnvelopeAssessment gate_solution(double minimum_Pa,double vmax,double reference_temperature_K,
    const std::string& mode,const std::string& dimensions,double mach_limit,std::optional<double> ma_max) {
    return gate_solution(minimum_Pa,vmax,reference_temperature_K,mode,dimensions,mach_limit,
                         mc::envelope_r_air,mc::envelope_gamma_air,ma_max);
}
}  // namespace tpmshx
