#include "stage_capture_3d.hpp"
#include "field_c_boundary.hpp"
#include "tpmshx/fluid_properties.hpp"
#include "tpmshx/result_metrics.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <deque>
#include <iomanip>
#include <limits>
#include <locale>
#include <memory>
#include <sstream>
#include <string>
#include <type_traits>
#include <utility>
#include <vector>

namespace tpmshx::stages {
namespace {
using Array=tpmshx_result_array_v1;
using Named=tpmshx_stage_named_array_v1;
constexpr const char* labels[]{"A","B","solid"};
constexpr const char* fluids[]{"air","water","sco2","co2"};
constexpr const char* faces[]{"x-","x+","y-","y+","z-","z+"};
struct ArrayStorage {
    std::array<size_t,3> shape{};
    std::array<ptrdiff_t,3> strides{};
    Array value{};
};
struct EnergyStorage {
    tpmshx_stage_energy_v1 view{};
    std::array<tpmshx_stage_energy_phase_v1,3> phases{};
    std::array<std::array<Named,6>,3> advection{},diffusion{};
};
struct RangeStorage {
    std::vector<std::string> source;
    std::vector<const char*> source_view;
    std::string side,stage,layout,quantity,unit;
    std::vector<size_t> shape,minimum_index,maximum_index;
    double minimum=0.,maximum=0.;
    tpmshx_stage_range_sample_v1 value{};
    void finish(bool finite,size_t min_index,size_t max_index,bool captured=true) {
        for(const auto& s:source)source_view.push_back(s.c_str());
        value.captured=captured?1:0;value.side=side.c_str();value.stage=stage.c_str();value.layout=layout.c_str();
        value.quantity=quantity.c_str();value.unit=unit.c_str();
        value.constraint=!source.empty() && source.front()=="geometry"?"hard_bounds":nullptr;
        value.source=source_view.data();value.source_count=source_view.size();
        value.shape=shape.data();value.rank=shape.size();
        if(captured && finite) {
            value.minimum=&minimum;value.maximum=&maximum;
            minimum_index.resize(shape.size());maximum_index.resize(shape.size());
            for(size_t axis=shape.size();axis>0;--axis) {
                const auto i=axis-1;
                if(!shape[i])throw std::invalid_argument("captured range has an empty axis");
                minimum_index[i]=min_index%shape[i];min_index/=shape[i];
                maximum_index[i]=max_index%shape[i];max_index/=shape[i];
            }
            value.minimum_index=minimum_index.data();value.maximum_index=maximum_index.data();
        }
    }
};
std::string text(tpmshx_preparation_text_v1 value) {
    fields::c_api::require_buffer(value.data,value.size);
    return value.size?std::string(value.data,value.size):std::string{};
}
bool inlet_stage(const std::string& value) {
    for(const char* stage:{"inlet","inlet-preflight","prepared-df","df-application","asym-ratio",
                          "main-inlet","richardson-inlet","fallback-inlet"})if(value==stage)return true;
    return false;
}
bool final_stage(const std::string& value) {
    for(const char* stage:{"main","main-hv","property-refresh","final","main-duty",
                          "richardson-duty","richardson-return"})if(value==stage)return true;
    return false;
}
}

class Capture3D {
public:
    tpmshx_full3d_result_v1 raw{};
    tpmshx_stage_capture_3d_v1 summary{};
    std::array<uint32_t,2> fluid{};
    std::array<std::vector<double>,2> audit_outlet;
    void capture_scalars(const tpmshx_full3d_input_v1& input) {
        namespace boundary=tpmshx::fields::c_api;
        summary.model_h_cell_count=boundary::product(boundary::product(input.shape[0],input.shape[1]),input.shape[2]);
        summary.q_net=tpmshx::result::arithmetic::python_float_sum({raw.solid_exchange[0],raw.solid_exchange[1]});
        for(size_t side=0;side<2;++side) {
            fluid[side]=input.sides[side].fluid;
            const auto& nu=raw.nu_observations[side];summary.nu_available[side]=nu.available;
            if(nu.available) {
                if(!nu.cells)throw std::runtime_error("native Nu observation has no cells");
                summary.nu_floor[side]=nusselt_floor(static_cast<Fluid>(fluid[side]));
                summary.nu_floor_fraction[side]=static_cast<double>(nu.floor_cells)/static_cast<double>(nu.cells);
            }
            const auto& flow=raw.flow[side];if(!flow.widths[0].size)continue;
            const auto clips=flow.last.pressure_clip_hits;
            if(clips>std::numeric_limits<size_t>::max()-summary.pressure_clip_hits)
                throw std::overflow_error("native pressure clip count exceeds size_t");
            summary.pressure_clip_hits+=clips;
        }
    }
    tpmshx_stage_capture_3d_v1 capture_summary(bool include_audit) {
        auto value=summary;
        if(!include_audit)return value;
        for(size_t side=0;side<2;++side) {
            const auto& flow=raw.flow[side];if(!flow.widths[0].size)continue;
            if(audit_outlet[side].empty()) {
                const size_t nx=flow.widths[0].size,nz=flow.widths[2].size;
                auto& values=audit_outlet[side];values.assign(flow.outlet_opening.data,flow.outlet_opening.data+flow.outlet_opening.size);
                if(fluid[side]<2)for(size_t i=0;i<nx;++i)for(size_t k=0;k<nz;++k) {
                    double taper=1.;
                    for(const auto item:{std::array<size_t,2>{i,nx},std::array<size_t,2>{k,nz}}) {
                        const auto distance=std::min(item[0]+1,item[1]-item[0]);
                        if(distance<=std::min(size_t{8},item[1]/2))
                            taper=std::min(taper,std::max(.2,1.-.8*std::exp(-static_cast<double>(distance))));
                    }
                    values[i*nz+k]*=taper;
                }
            }
            value.audit_outlet[side]={audit_outlet[side].data(),audit_outlet[side].size()};
        }
        return value;
    }

    tpmshx_full3d_control_v1 resolved{};
    tpmshx_result_evidence_v1 evidence{};
    tpmshx_stage_input_v2 evaluation{};
    std::vector<const void*> none_values;
    std::string result_id,table_directory;
    std::array<size_t,3> shape{};
    int dimension=3,outer_index=0,energy_version=0;
    std::array<int,2> direction{};
    std::deque<ArrayStorage> arrays;
    std::deque<tpmshx_result_scalar_v1> scalars;
    std::deque<std::vector<double>> copies;
    std::vector<Named> result_fields;
    std::vector<tpmshx_stage_field_declaration_v1> declarations;
    std::array<tpmshx_stage_pressure_v1,2> pressures{};
    std::array<std::array<Array,3>,2> masses{},true_h_masses{};
    EnergyStorage energy,temperature;
    tpmshx_stage_model_certificate_v1 model{};
    std::array<std::array<Named,6>,2> model_power{},true_h_power{};
    tpmshx_stage_model_level_v1 model_level{};
    tpmshx_stage_true_h_v1 true_h{};
    tpmshx_stage_true_h_certificate_v1 true_h_certificate{};
    tpmshx_full3d_energy_effective_settings_v1 energy_settings{};
    tpmshx_full3d_energy_evidence_v1 energy_evidence{};
    tpmshx_physical_heat_ledger_v1 ledger{};
    tpmshx_model_enthalpy_evidence_v1 temperature_ledger{};
    std::array<tpmshx_stage_gate_v1,5> gates{};
    std::array<tpmshx_stage_execution_side_v1,2> execution{};
    std::deque<RangeStorage> ranges;
    std::vector<tpmshx_stage_range_sample_v1> inlet_ranges,final_ranges;
    std::deque<std::array<const char*,3>> required_sources;
    std::vector<tpmshx_stage_required_range_v1> required;
    std::vector<std::string> notices;
    std::vector<const char*> notice_views;
    tpmshx_stage_applicability_v1 applicability{};

    ~Capture3D() {tpmshx_full_3d_release_v1(&raw);}
    template<class Value> const Array* array(const Value* data,size_t size,std::initializer_list<size_t> dimensions) {
        static_assert(std::is_same_v<Value,double> || std::is_same_v<Value,uint64_t>);
        if(dimensions.size()>3)throw std::invalid_argument("stage capture rank exceeds three");
        size_t count=1;
        for(auto n:dimensions)count=fields::c_api::product(count,n);
        if(count!=size)throw std::invalid_argument("native 3D evidence has an inconsistent array shape");
        fields::c_api::require_buffer(data,size);
        arrays.emplace_back();auto& stored=arrays.back();
        std::copy(dimensions.begin(),dimensions.end(),stored.shape.begin());
        size_t stride=sizeof(Value);
        for(size_t axis=dimensions.size();axis>0;--axis) {
            stored.strides[axis-1]=static_cast<ptrdiff_t>(stride);
            stride=fields::c_api::product(stride,stored.shape[axis-1]);
        }
        stored.value={data,fields::c_api::product(size,sizeof(Value)),0,
            std::is_same_v<Value,double>?TPMSHX_RESULT_F64:TPMSHX_RESULT_U64,
            static_cast<uint32_t>(dimensions.size()?TPMSHX_RESULT_NUMPY_ARRAY:TPMSHX_RESULT_PYTHON_FLOAT),
            TPMSHX_RESULT_NATIVE_ENDIAN,0,dimensions.size(),stored.shape.data(),stored.strides.data()};
        return &stored.value;
    }
    template<class View> const Array* array(View value,std::initializer_list<size_t> dimensions) {
        return array(value.data,value.size,dimensions);
    }
    template<class View> const Array* cell_array(View value) {
        return array(value,{shape[0],shape[1],shape[2]});
    }
    template<class View> const Array* face_array(View value,size_t axis) {
        return array(value,{shape[0]+(axis==0),shape[1]+(axis==1),shape[2]+(axis==2)});
    }
    template<class View> const Array* boundary_array(View value,size_t face) {
        if(face<2)return array(value,{shape[1],shape[2]});
        if(face<4)return array(value,{shape[0],shape[2]});
        return array(value,{shape[0],shape[1]});
    }
    template<class View> const Array* copy(View value,std::initializer_list<size_t> dimensions) {
        fields::c_api::require_buffer(value.data,value.size);
        copies.emplace_back();auto& stored=copies.back();
        if(value.size)stored.assign(value.data,value.data+value.size);
        return array(stored.data(),stored.size(),dimensions);
    }
    const Array* constant(double value) {
        copies.emplace_back(1,value);return array(copies.back().data(),1,{});
    }
    const tpmshx_result_scalar_v1* scalar(double value) {
        scalars.emplace_back();auto& stored=scalars.back();
        stored.dtype=TPMSHX_RESULT_F64;stored.origin=TPMSHX_RESULT_PYTHON_FLOAT;
        stored.byte_order=TPMSHX_RESULT_NATIVE_ENDIAN;std::memcpy(stored.data,&value,sizeof(value));
        return &stored;
    }
    void field(const char* name,const Array* value,const char* unit,const char* state) {
        result_fields.push_back({name,*value});declarations.push_back({name,unit,state});
    }
    const Array* gauge(const tpmshx_full3d_side_v1& side,const tpmshx_full3d_flow_v1& flow) {
        const auto& axes=side.solver_axes;
        for(size_t axis=0;axis<3;++axis)
            if(axes[axis]>2 || flow.widths[axis].size!=shape[axes[axis]])
                throw std::runtime_error("native 3D pressure axes do not match the physical grid");
        const std::array<size_t,3> local{flow.widths[0].size,flow.widths[1].size,flow.widths[2].size};
        array(flow.pressure,{local[0],local[1],local[2]});
        copies.emplace_back(flow.pressure.size);auto& out=copies.back();
        for(size_t i=0;i<local[0];++i)for(size_t j=0;j<local[1];++j)for(size_t k=0;k<local[2];++k) {
            std::array<size_t,3> p{};
            p[axes[0]]=i;p[axes[1]]=side.direction%2?local[1]-1-j:j;p[axes[2]]=k;
            out[(p[0]*shape[1]+p[1])*shape[2]+p[2]]=flow.pressure.data[(i*local[1]+j)*local[2]+k];
        }
        return array(out.data(),out.size(),{shape[0],shape[1],shape[2]});
    }
    template<class Ledger> void make_energy(EnergyStorage& out,const Ledger& native,const char* definition) {
        if(!native.available)return;
        if(native.available!=1 || native.physical_dimension!=3 || native.boundary_complete>1)
            throw std::runtime_error("native 3D heat ledger has invalid state flags");
        out.view.definition=definition;out.view.power_units="W";out.view.physical_dimension=3;
        out.view.physical_boundary_complete=static_cast<int>(native.boundary_complete);
        out.view.phases=out.phases.data();out.view.phase_count=3;
        out.view.prescribed_b_power=constant(native.prescribed_b_power);
        for(size_t phase=0;phase<3;++phase) {
            if(native.solved[phase]>1)throw std::runtime_error("native 3D heat ledger has an invalid solved flag");
            auto& row=out.phases[phase];row.name=labels[phase];row.solved=static_cast<int>(native.solved[phase]);
            if(!native.solved[phase])continue;
            row.residual=cell_array(native.residual[phase]);row.source_integral=constant(native.source_integral[phase]);
            for(size_t face=0;face<6;++face) {
                out.advection[phase][face]={faces[face],*boundary_array(native.advective_out[phase][face],face)};
                out.diffusion[phase][face]={faces[face],*boundary_array(native.diffusive_out[phase][face],face)};
            }
            row.advective_out=out.advection[phase].data();row.advective_count=6;
            row.diffusive_out=out.diffusion[phase].data();row.diffusive_count=6;
        }
    }
    void make_model() {
        const auto& audit=raw.model_h.volume;
        // The portable 3D certificate has no recorded passed key.
        model.passed=-1;model.physical_boundary_complete=static_cast<int>(audit.boundary_complete);
        for(size_t side=0;side<2;++side) {
            const auto& s=audit.sides[side];auto& row=model.sides[side];
            row.physical_boundary_complete=static_cast<int>(s.boundary_complete);
            for(size_t face=0;face<6;++face)
                model_power[side][face]={faces[face],*boundary_array(s.boundaries[face].enthalpy_faces,face)};
            row.boundary_power=model_power[side].data();row.boundary_count=6;
            evidence.strict_ratios[side*2]=&s.global_ratio;evidence.strict_ratios[side*2+1]=&s.cell_ratio;
        }
        evidence.thermal.model_h=&model;
        model_level.level="main";model_level.value.passed=-1;
        model_level.value.physical_boundary_complete=model.physical_boundary_complete;
        for(size_t side=0;side<2;++side)
            model_level.value.sides[side].physical_boundary_complete=model.sides[side].physical_boundary_complete;
        evidence.model_certificates=&model_level;evidence.model_certificate_count=1;
    }
    void make_true_h() {
        if(tpmshx_full_3d_get_energy_evidence_v1(&raw,&energy_evidence))
            throw std::runtime_error("native full 3D energy evidence query failed");
        const auto& settings=energy_settings.last;const auto& native=energy_evidence;
        if(!raw.has_true_h || settings.available!=1 || native.available!=1
            || native.energy.has_temperature_update!=1 || native.energy.algorithm!=TPMSHX_ENERGY_TEMPERATURE_SOU
            || native.outer_count!=raw.outer_count)
            throw std::runtime_error("native conservative energy omitted its executed state");
        if(!std::isfinite(native.energy.temperature_update) || native.energy.temperature_update<0.
            || !std::isfinite(native.energy.picard_relaxation) || native.energy.picard_relaxation<=0.
            || native.energy.picard_relaxation>1.)
            throw std::runtime_error("native energy returned an invalid temperature update or relaxation");
        energy_version=static_cast<int>(tpmshx_energy_algorithm_version_v1(native.energy.algorithm));
        if(energy_version!=1 && energy_version!=2)
            throw std::runtime_error("native energy returned an unsupported algorithm version");
        true_h.energy_algorithm="temperature_sou";true_h.energy_algorithm_version=&energy_version;
        true_h.boundary_power_units="W";true_h.physical_boundary_complete=1;
        for(size_t side=0;side<2;++side) {
            true_h.enthalpy[side]=cell_array(raw.enthalpy[side]);
            true_h.inlet_enthalpy[side]=scalar(raw.true_h.inlet_enthalpy[side]);
            for(size_t axis=0;axis<3;++axis)true_h_masses[side][axis]=*face_array(raw.mass[side][axis],axis);
            true_h.mass[side]=true_h_masses[side].data();true_h.mass_count[side]=3;
            for(size_t face=0;face<6;++face)
                true_h_power[side][face]={faces[face],*boundary_array(native.boundary_power[side][face],face)};
            true_h.boundary_power[side]=true_h_power[side].data();true_h.boundary_count[side]=6;
        }
        true_h_certificate.converged=static_cast<int>(raw.thermal_ok);
        true_h_certificate.clip_counts=array(raw.true_h.total_clips,2,{2});
        true_h_certificate.tolerances[0]=scalar(settings.coupled_energy_tolerance);
        true_h_certificate.tolerances[1]=scalar(settings.equation_energy_tolerance);
        if(raw.true_h.audit_available) {
            true_h_certificate.ratios[0]=scalar(raw.true_h.audit.coupled_ratio);
            if(raw.true_h.audit.fluid_equations_computed)
                true_h_certificate.ratios[1]=scalar(raw.true_h.audit.equation_ratio);
        }
        evidence.thermal.true_h=&true_h;evidence.true_h_certificate=&true_h_certificate;
    }
    void make_thermal() {
        if(tpmshx_full_3d_get_energy_effective_settings_v1(&raw,&energy_settings))
            throw std::runtime_error("native full 3D effective settings query failed");
        if(energy_settings.outer_count!=raw.outer_count)
            throw std::runtime_error("native full 3D effective settings do not match the thermal history");
        if(raw.thermal_mode==2 || energy_settings.last.available) {
            make_true_h();evidence.thermal_mode="conservative_energy";
        }
        if(raw.has_model_h)make_model();
        else if(raw.thermal_mode==0)for(size_t side=0;side<2;++side) {
            const auto& s=raw.staggered[side];
            if(s.available && s.residual_available) {
                evidence.strict_ratios[side*2]=&s.global_ratio;evidence.strict_ratios[side*2+1]=&s.cell_ratio;
            }
        }
        const bool temperature_transport=raw.thermal_mode==0
            && (shape[2]==1 || (!resolved.conservative && resolved.force_cell_centered));
        if(raw.thermal_mode==1 || temperature_transport) {
            if(tpmshx_full_3d_get_model_enthalpy_evidence_v1(&raw,&temperature_ledger))
                throw std::runtime_error("native full 3D temperature evidence query failed");
            if(temperature_transport || temperature_ledger.available || temperature_ledger.algorithm) {
                if(temperature_ledger.available!=1 || temperature_ledger.physical_dimension!=3 || !temperature_ledger.algorithm)
                    throw std::runtime_error("native full 3D model enthalpy identity or ledger is invalid");
            }
        }
        if(temperature_transport) {
            for(size_t side=0;side<2;++side)if(temperature_ledger.solved[side])
                for(double coefficient:temperature_ledger.cp_coefficients[side])
                    if(!std::isfinite(coefficient))throw std::runtime_error("native temperature evidence has invalid enthalpy coefficients");
            make_energy(temperature,temperature_ledger,"model_enthalpy_temperature_v1");
            evidence.thermal.temperature=&temperature.view;
            evidence.temperature_transport="model_enthalpy_temperature_v1";
        } else {
            if(tpmshx_full_3d_get_physical_heat_ledger_v1(&raw,&ledger))
                throw std::runtime_error("native full 3D heat ledger query failed");
            make_energy(energy,ledger,"physical_heat_ledger_v1");
            if(ledger.available)evidence.thermal.energy=&energy.view;
        }
    }
    void prepared_ranges(const tpmshx_stage_saved_case_3d_v1& saved) {
        const auto& p=saved.preparation;
        fields::c_api::require_buffer(p.ranges,p.range_count);
        if(saved.range_captured)fields::c_api::require_buffer(saved.range_captured,p.range_count);
        for(size_t i=0;i<p.range_count;++i) {
            const auto& r=p.ranges[i];ranges.emplace_back();auto& out=ranges.back();
            fields::c_api::require_buffer(r.source,r.source_count);fields::c_api::require_buffer(r.shape,r.rank);
            for(size_t j=0;j<r.source_count;++j)out.source.push_back(text(r.source[j]));
            out.side=text(r.side);out.stage=text(r.stage);out.layout=text(r.layout);
            out.quantity=text(r.quantity);out.unit=text(r.unit);
            const bool captured=!saved.range_captured || saved.range_captured[i];
            const auto& sample=r.sample;auto& row=out.value;
            if(captured) {
                if(r.rank)out.shape.assign(r.shape,r.shape+r.rank);
                row.bounds[0]=r.bounds[0];row.bounds[1]=r.bounds[1];
                row.size=sample.size;row.low=sample.low;row.high=sample.high;row.nonfinite=sample.nonfinite;
                out.minimum=sample.minimum;out.maximum=sample.maximum;
            }
            out.finish(sample.have_finite!=0,sample.minimum_index,sample.maximum_index,captured);
            inlet_ranges.push_back(out.value);
        }
    }
    void final_state_ranges() {
        tpmshx_range_observations_view_v1 last{};
        if(tpmshx_full_3d_get_last_closure_ranges_v1(&raw,&last))
            throw std::runtime_error("native last closure range query failed");
        fields::c_api::require_buffer(last.data,last.size);
        for(size_t i=0;i<last.size;++i) {
            const auto& r=last.data[i];
            if(!r.stage || !r.view || !r.model || !r.layout || r.side>1 || r.ndim>3)
                throw std::runtime_error("native last closure range has invalid metadata");
            const std::string stage=r.stage,view=r.view;
            const bool inlet=inlet_stage(stage);
            const bool final=final_stage(stage) && (view!="property_state" || stage=="final" || stage=="richardson-return");
            if(!inlet && !final)continue;
            ranges.emplace_back();auto& out=ranges.back();
            const bool nu=view=="nu" || view=="nu_raw" || view=="nu_pr";
            out.source={r.view,r.model};
            if(nu) {
                if(!r.topology)throw std::runtime_error("native Nu range has no topology");
                out.source.emplace_back(r.topology);
            }
            out.side=labels[r.side];out.stage=stage;out.layout=r.layout;
            out.quantity=view=="nu_pr"?"Pr":nu?"Re":"T";out.unit=nu?"-":"K";
            out.shape.assign(r.shape,r.shape+r.ndim);out.minimum=r.minimum;out.maximum=r.maximum;
            auto& row=out.value;row.bounds[0]=r.lower;row.bounds[1]=r.upper;row.size=r.size;
            row.low=r.low;row.high=r.high;row.nonfinite=r.nonfinite;
            out.finish(r.have_finite!=0,r.minimum_index,r.maximum_index);
            (inlet?inlet_ranges:final_ranges).push_back(out.value);
        }
    }
    void required_ranges(const tpmshx_full3d_input_v1& input) {
        const auto add=[&](const char* group,const char* side,const char* source,const char* model_name,const char* topology=nullptr) {
            required_sources.push_back({source,model_name,topology});
            required.push_back({group,side,required_sources.back().data(),topology?size_t{3}:size_t{2}});
        };
        add("inlet","shared","geometry","L_field_m");add("inlet","shared","geometry","t_field_m");
        for(size_t side=0;side<2;++side) {
            if(!raw.flow[side].widths[0].size)continue;
            const auto fluid=input.sides[side].fluid;const char* topology=input.topology?"Gyroid":"Diamond";
            add("inlet",labels[side],"nu",fluids[fluid],topology);
            add("final",labels[side],"nu_raw",fluids[fluid],topology);
            if(fluid==3)add("final",labels[side],"nu_pr",fluids[fluid],topology);
            if(fluid<2 && raw.thermal_mode!=2)add("final",labels[side],"property_state",fluid?"water_cp":"air_cp");
        }
        applicability.version="applicability_evidence_v1";
        applicability.inlet=inlet_ranges.data();applicability.inlet_count=inlet_ranges.size();
        applicability.final_state=final_ranges.data();applicability.final_count=final_ranges.size();
        applicability.required=required.data();applicability.required_count=required.size();
    }
    void scope_notes(const tpmshx_stage_saved_case_3d_v1& saved) {
        const auto add=[&](std::string message) {
            if(std::find(notices.begin(),notices.end(),message)==notices.end())notices.push_back(std::move(message));
        };
        fields::c_api::require_buffer(saved.notices,saved.notice_count);
        for(size_t i=0;i<saved.notice_count;++i)add(text(saved.notices[i]));
        const auto& input=*saved.input;
        for(size_t side=0;side<2;++side) {
            if(input.sides[side].fluid!=2 || !raw.flow[side].widths[0].size)continue;
            const auto pressure=input.sides[side].inlet_pressure;
            std::ostringstream message;message.imbue(std::locale::classic());message<<std::setprecision(6);
            message<<"[sCO2 Nu evidence] 3D h_v property refresh, side="<<labels[side]<<", "
                <<(input.topology?"Gyroid":"Diamond")<<", ";
            if(input.spatial) {
                const auto extrema=[](const double* data,size_t count) {
                    fields::c_api::require_buffer(data,count);
                    if(!count)throw std::invalid_argument("spatial scope evidence has an empty geometry field");
                    const auto values=std::minmax_element(data,data+count);
                    return std::array<double,2>{*values.first*1e3,*values.second*1e3};
                };
                const auto length=extrema(input.cell_length.data,input.cell_length.size);
                const auto wall=extrema(saved.wall_thickness_m.data,saved.wall_thickness_m.size);
                message<<"zoned L=["<<length[0]<<","<<length[1]<<"] mm, t=["<<wall[0]<<","<<wall[1]<<"] mm";
            } else message<<"L="<<saved.nominal_cell_length_mm<<" mm, t="<<saved.nominal_wall_thickness_mm<<" mm";
            message<<"; Nu uses scalar P_in="<<pressure<<" Pa. "
                "Joint qualification remains unverified: the old CFD evidence uses "
                "heating at Twall=Tref+50 K and period-2/3 bulk properties. "
                "The reported subset requires P>=10 MPa AND Tb>=Tpc(P)-2 K within "
                "that campaign; Tpc, joint Pr/P/T coverage, actual wall temperature "
                "and heating/cooling qualification are not established here. "
                "Pressure or Re-window membership alone is not a PASS.";
            if(pressure<10e6)message<<" P_in<10 MPa does not meet the subset necessary pressure condition.";
            if(pressure>15e6)message<<" P_in>15 MPa exceeds the old campaign pressure envelope (8/10/12/15 MPa).";
            add(message.str());
        }
        for(const auto& notice:notices)notice_views.push_back(notice.c_str());
        applicability.scope_notes=notice_views.data();applicability.scope_note_count=notice_views.size();
    }
    void populate(const tpmshx_stage_saved_case_3d_v1& saved) {
        fields::c_api::require_buffer(saved.input,1);const auto& input=*saved.input;
        if(raw.stop>1 || raw.thermal_mode>2)throw std::runtime_error("native full 3D returned an invalid completed state");
        if(raw.thermal_outer_index>static_cast<size_t>(std::numeric_limits<int>::max()))
            throw std::runtime_error("native full 3D outer index exceeds the evidence range");
        std::copy(input.shape,input.shape+3,shape.begin());
        for(const auto& side:input.sides)
            if(side.fluid>3 || side.direction>5)throw std::invalid_argument("3D capture has an invalid fluid or direction");
        auto& e=evidence;e.abi_version=TPMSHX_RESULT_STAGE_ABI_VERSION;e.struct_size=sizeof(e);e.result_id=result_id.c_str();
        e.dimension=3;e.metadata_dimension=&dimension;e.quantity_basis="total";e.mass_unit="kg/s";
        e.mode="full";e.thermal_mode=raw.thermal_mode==0?"temperature":raw.thermal_mode==1?"model_h":"true_h";
        e.thermal_state="last thermal input";e.execution="completed";e.converged=static_cast<int>(raw.converged);
        outer_index=static_cast<int>(raw.thermal_outer_index);e.outer_index=&outer_index;
        for(size_t axis=0;axis<3;++axis)e.grid.widths[axis]=copy(input.widths[axis],{shape[axis]});
        for(size_t phase=0;phase<3;++phase)
            field(phase==0?"Ta":phase==1?"Tb":"Ts",cell_array(raw.temperature[phase]),"K","last thermal solve");
        for(size_t side=0;side<2;++side)
            field(side?"h_vB":"h_vA",cell_array(raw.hv[side]),"W/(m3 K)","last thermal solve");
        field("K_ss",copy(input.solid_conductivity,{shape[0],shape[1],shape[2]}),"W/(m K)","last thermal solve");
        for(size_t side=0;side<2;++side)if(raw.thermal_pressure[side].size)
            field(side?"P_thermal_B":"P_thermal_A",cell_array(raw.thermal_pressure[side]),"Pa","last thermal solve");
        for(size_t phase=0;phase<3;++phase)
            field(phase==0?"Ta_display":phase==1?"Tb_display":"Ts_display",cell_array(raw.temperature[phase]),"K","display");
        e.parameter_epsilon=constant(saved.nominal_porosity);
        e.design_epsilon=copy(input.epsilon,{shape[0],shape[1],shape[2]});
        for(size_t side=0;side<2;++side) {
            const auto& s=input.sides[side];const auto& flow=raw.flow[side];
            const bool active=flow.widths[0].size!=0;
            direction[side]=static_cast<int>(s.direction);
            e.inlet_temperature[side]=scalar(s.inlet_temperature);e.active_fluids[side]=active?1:0;
            evaluation.inlet_temperature[side]=constant(s.inlet_temperature);
            execution[side]={labels[side],fluids[s.fluid],active?1:0};
            e.source_power[side]=&raw.solid_exchange[side];
            if(raw.mass[side][0].size) {
                for(size_t axis=0;axis<3;++axis)masses[side][axis]=*face_array(raw.mass[side][axis],axis);
                e.thermal.mass[side]=masses[side].data();e.thermal.mass_count[side]=3;
            } else {
                e.thermal.mass[side]=masses[side].data();none_values.push_back(e.thermal.mass[side]);
            }
            if(!active)continue;
            e.thermal.report_direction[side]=&direction[side];
            field(side?"P_gauge_B":"P_gauge_A",gauge(s,flow),"Pa","final SIMPLE flow");
            field(side?"P_report_B":"P_report_A",cell_array(flow.pressure_real),"Pa","final SIMPLE flow");
            field(side?"P_fB_display":"P_fA_display",cell_array(flow.pressure_real),"Pa","display");
            field(side?"ucB":"ucA",cell_array(flow.velocity_real[0]),"m/s","final flow/report");
            field(side?"vcB":"vcA",cell_array(flow.velocity_real[1]),"m/s","final flow/report");
            field(side?"wcB":"wcA",cell_array(flow.velocity_real[2]),"m/s","final flow/report");
            field(side?"vmag_B":"vmag_A",cell_array(flow.speed_real),"m/s","final flow/report");
            const auto nx=flow.widths[0].size,ny=flow.widths[1].size,nz=flow.widths[2].size;
            auto& p=pressures[side];p.pressure=array(flow.pressure,{nx,ny,nz});
            for(size_t axis=0;axis<3;++axis)p.grid.widths[axis]=array(flow.widths[axis],{flow.widths[axis].size});
            p.inlet_fraction=array(flow.inlet_opening,{nx,nz});p.outlet_fraction=array(flow.outlet_opening,{nx,nz});
            p.reference=scalar(flow.pressure_reference);p.unit="Pa";e.pressure[side]=&p;
        }
        e.fields=result_fields.data();e.field_count=result_fields.size();e.field_metadata=declarations.data();e.field_metadata_count=declarations.size();
        e.model_active_b=input.solve_b?1:0;e.richardson_extrapolated=-1;
        make_thermal();
        gates={{{"simple_ok",static_cast<int>(raw.simple_ok),nullptr,nullptr},
            {"ltne_ok",static_cast<int>(raw.thermal_ok),nullptr,nullptr},
            {"outer_converged",static_cast<int>(raw.outer_ok),nullptr,nullptr},
            {"fields_finite",static_cast<int>(raw.finite_fields),nullptr,nullptr},
            {"envelope_ok",static_cast<int>(raw.envelope_ok),nullptr,nullptr}}};
        e.convergence_gates=gates.data();e.convergence_gate_count=gates.size();
        e.execution_version="full_execution_v1";e.executed_sides=execution.data();e.executed_side_count=2;
        prepared_ranges(saved);final_state_ranges();required_ranges(input);scope_notes(saved);
        applicability.inlet_recorded=saved.inlet_recorded?1:0;e.applicability=&applicability;
        evaluation.abi_version=2;evaluation.struct_size=sizeof(evaluation);evaluation.evidence=&e;
        evaluation.none_values=none_values.data();evaluation.none_count=none_values.size();
        evaluation.physical_dimension_index=evaluation.physical_dimension_slice=&dimension;
    }
};

Capture3D* capture_3d(const tpmshx_stage_saved_case_3d_v1& saved,tpmshx_full3d_result_v1& raw,
    const tpmshx_full3d_control_v1& resolved,const char* result_id) {
    auto owner=std::make_unique<Capture3D>();owner->raw=raw;raw={};owner->resolved=resolved;
    if(!result_id)throw std::invalid_argument("3D capture requires a result identifier");
    owner->result_id=result_id;
    if(resolved.table_directory) {owner->table_directory=resolved.table_directory;owner->resolved.table_directory=owner->table_directory.c_str();}
    if(owner->raw.stop!=2) {owner->populate(saved);owner->capture_scalars(*saved.input);}
    return owner.release();
}
tpmshx_stage_run_result_3d_v1 stage_view(Capture3D& owner) {
    return {TPMSHX_STAGE_RUN_3D_ABI_VERSION,sizeof(tpmshx_stage_run_result_3d_v1),&owner,owner.raw,owner.evidence,owner.resolved,owner.evaluation};
}
void release_capture_3d(Capture3D* owner) noexcept {delete owner;}
}  // namespace tpmshx::stages

extern "C" uint32_t TPMSHX_THERMAL_CALL tpmshx_stage_capture_3d_abi_version(void) {
    return TPMSHX_STAGE_CAPTURE_3D_ABI_VERSION;
}

extern "C" int TPMSHX_THERMAL_CALL tpmshx_stage_run_3d_get_capture_v1(
    const tpmshx_stage_run_result_3d_v1* result,uint32_t include_audit,tpmshx_stage_capture_3d_v1* output) {
    namespace boundary=tpmshx::fields::c_api;
    try {
        boundary::require_buffer(result,1);boundary::require_buffer(output,1);
        const auto first=reinterpret_cast<uintptr_t>(result),second=reinterpret_cast<uintptr_t>(output);
        if(first<=second+sizeof(*output)-1 && second<=first+sizeof(*result)-1)return 1;
        if(include_audit>1 || result->abi_version!=TPMSHX_STAGE_RUN_3D_ABI_VERSION
            || result->struct_size!=sizeof(*result) || !result->owner || result->raw.stop>1)return 1;
        auto& owner=*static_cast<tpmshx::stages::Capture3D*>(result->owner);
        const auto value=owner.capture_summary(include_audit!=0);*output=value;return 0;
    } catch(const std::invalid_argument&) {return 1;}
    catch(...) {return 4;}
}
