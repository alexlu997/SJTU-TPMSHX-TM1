#include "stage_capture_2d.hpp"
#include "field_c_boundary.hpp"

#include <algorithm>
#include <array>
#include <cstring>
#include <deque>
#include <string>
#include <utility>
#include <vector>

namespace tpmshx::stages {
namespace {
using Array=tpmshx_result_array_v1;
using Named=tpmshx_stage_named_array_v1;
constexpr const char* labels[]{"A","B","solid"};
constexpr const char* faces[]{"x-","x+","y-","y+","z-","z+"};
struct ArrayStorage {
    std::array<size_t,3> shape{};
    std::array<ptrdiff_t,3> strides{};
    Array value{};
};
struct RangeStorage {
    std::vector<std::string> source;
    std::vector<const char*> source_view;
    std::string side,stage,layout,quantity,unit;
    std::vector<size_t> shape,minimum_index,maximum_index;
    double minimum=0.,maximum=0.;
    tpmshx_stage_range_sample_v1 value{};
    void finish(bool finite,size_t min_index,size_t max_index) {
        for(const auto& s:source)source_view.push_back(s.c_str());
        value.captured=1;value.side=side.c_str();value.stage=stage.c_str();value.layout=layout.c_str();
        value.quantity=quantity.c_str();value.unit=unit.c_str();
        value.constraint=!source.empty() && source[0]=="geometry"?"hard_bounds":nullptr;
        value.source=source_view.data();value.source_count=source_view.size();
        value.shape=shape.data();value.rank=shape.size();
        if(finite) {
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
struct EnergyStorage {
    tpmshx_stage_energy_v1 view{};
    std::array<tpmshx_stage_energy_phase_v1,3> phases{};
    std::array<std::array<Named,6>,3> advection{},diffusion{};
};
struct ModelStorage {
    tpmshx_stage_model_certificate_v1 view{};
    std::array<std::array<Array,2>,2> power{};
};
std::string text(tpmshx_preparation_text_v1 value) {
    if(!value.size)return {};
    fields::c_api::require_buffer(value.data,value.size);
    return {value.data,value.size};
}
bool inlet_stage(const std::string& value) {
    for(const char* stage:{"inlet","inlet-preflight","prepared-df","df-application","asym-ratio",
                          "main-inlet","richardson-inlet","fallback-inlet"})if(value==stage)return true;
    return false;
}
bool final_stage(const std::string& value) {
    for(const char* stage:{"main","main-hv","property-refresh","final","main-duty","richardson-duty",
                          "richardson-return"})if(value==stage)return true;
    return false;
}
}

class Capture2D {
public:
    tpmshx_full_2d_result_v2 raw{};
    tpmshx_full_2d_config_v2 resolved{};
    tpmshx_result_evidence_v1 evidence{};
    std::string result_id,table_directory;
    int dimension=2,outer_index=0;
    std::array<int,2> direction{};
    std::deque<ArrayStorage> arrays;
    std::deque<tpmshx_result_scalar_v1> scalars;
    std::deque<std::vector<double>> copies;
    std::vector<Named> main_fields,fine_fields;
    std::vector<tpmshx_stage_field_declaration_v1> declarations;
    std::array<tpmshx_stage_pressure_v1,2> pressures{};
    std::array<std::array<Array,2>,2> masses{},fine_masses{};
    std::array<EnergyStorage,2> energy;
    std::array<ModelStorage,2> model;
    std::array<tpmshx_stage_model_level_v1,2> model_levels{};
    std::array<tpmshx_stage_gate_v1,5> gates{};
    std::array<tpmshx_stage_execution_side_v1,2> execution{};
    tpmshx_stage_fine_v1 fine{};
    tpmshx_full_2d_physical_heat_ledger_v1 ledgers{};
    std::deque<RangeStorage> ranges;
    std::vector<tpmshx_stage_range_sample_v1> inlet_ranges,final_ranges;
    std::array<tpmshx_stage_required_range_v1,8> required{};
    std::array<std::array<const char*,3>,8> required_sources{};
    tpmshx_stage_applicability_v1 applicability{};

    ~Capture2D() {tpmshx_full_2d_release_v2(&raw);}
    const Array* array(const double* data,size_t size,std::initializer_list<size_t> shape) {
        if(shape.size()>3)throw std::invalid_argument("stage capture rank exceeds three");
        size_t count=1;
        for(auto n:shape)count=fields::c_api::product(count,n);
        if(count!=size)throw std::invalid_argument("native stage evidence has an inconsistent array shape");
        fields::c_api::require_buffer(data,size);
        arrays.emplace_back();auto& stored=arrays.back();
        std::copy(shape.begin(),shape.end(),stored.shape.begin());
        size_t stride=sizeof(double);
        for(size_t axis=shape.size();axis>0;--axis) {
            stored.strides[axis-1]=static_cast<ptrdiff_t>(stride);
            stride=fields::c_api::product(stride,stored.shape[axis-1]);
        }
        stored.value={data,fields::c_api::product(size,sizeof(double)),0,TPMSHX_RESULT_F64,
            shape.size()?TPMSHX_RESULT_NUMPY_ARRAY:TPMSHX_RESULT_PYTHON_FLOAT,
            TPMSHX_RESULT_NATIVE_ENDIAN,0,shape.size(),stored.shape.data(),stored.strides.data()};
        return &stored.value;
    }
    template<class View> const Array* array(View value,std::initializer_list<size_t> shape) {
        return array(value.data,value.size,shape);
    }
    const Array* copy(tpmshx_preparation_array_v1 value) {
        fields::c_api::require_buffer(value.data,value.size);
        copies.emplace_back(value.data,value.data+value.size);
        return array(copies.back().data(),copies.back().size(),{value.size});
    }
    const Array* constant(double value) {
        copies.emplace_back(1,value);return array(copies.back().data(),1,{});
    }
    const tpmshx_result_scalar_v1* scalar(double value) {
        scalars.emplace_back();auto& s=scalars.back();
        s.dtype=TPMSHX_RESULT_F64;s.origin=TPMSHX_RESULT_PYTHON_FLOAT;s.byte_order=TPMSHX_RESULT_NATIVE_ENDIAN;
        std::memcpy(s.data,&value,sizeof(value));return &s;
    }
    void field(const char* name,tpmshx_model_h_array_v1 value,const char* unit,const char* state) {
        main_fields.push_back({name,*array(value,{raw.main.nx,raw.main.ny})});
        declarations.push_back({name,unit,state});
    }
    void make_energy(EnergyStorage& out,const tpmshx_physical_heat_ledger_v1& native,size_t nx,size_t ny) {
        if(!native.available)return;
        out.view.definition="physical_heat_ledger_v1";out.view.power_units="W/m";
        out.view.physical_dimension=2;out.view.physical_boundary_complete=static_cast<int>(native.boundary_complete);
        out.view.phases=out.phases.data();out.view.phase_count=3;
        out.view.prescribed_b_power=constant(native.prescribed_b_power);
        for(size_t phase=0;phase<3;++phase) {
            auto& p=out.phases[phase];p.name=labels[phase];p.solved=static_cast<int>(native.solved[phase]);
            if(!native.solved[phase])continue;
            p.residual=array(native.residual[phase],{nx,ny});p.source_integral=constant(native.source_integral[phase]);
            for(size_t face=0;face<6;++face) {
                const std::array<size_t,2> shape=face<2?std::array<size_t,2>{ny,1}:
                    face<4?std::array<size_t,2>{nx,1}:std::array<size_t,2>{nx,ny};
                out.advection[phase][face]={faces[face],*array(native.advective_out[phase][face],{shape[0],shape[1]})};
                out.diffusion[phase][face]={faces[face],*array(native.diffusive_out[phase][face],{shape[0],shape[1]})};
            }
            p.advective_out=out.advection[phase].data();p.advective_count=6;
            p.diffusive_out=out.diffusion[phase].data();p.diffusive_count=6;
        }
    }
    void make_model(ModelStorage& out,const tpmshx_full_2d_thermal_v2& native) {
        const auto& audit=native.model_h.plane;
        out.view.passed=static_cast<int>(audit.passed);out.view.physical_boundary_complete=static_cast<int>(audit.boundary_complete);
        for(size_t side=0;side<2;++side) {
            out.view.sides[side].physical_boundary_complete=audit.sides[side].unknown_inflow_faces==0?1:0;
            out.power[side]={*array(audit.sides[side].h_faces[0],{native.nx+1,native.ny}),
                             *array(audit.sides[side].h_faces[1],{native.nx,native.ny+1})};
            out.view.sides[side].staggered_power=out.power[side].data();out.view.sides[side].staggered_count=2;
        }
    }
    void prepared_ranges(const tpmshx_preparation_case_2d_v1& prepared) {
        for(size_t i=0;i<prepared.range_count;++i) {
            const auto& r=prepared.ranges[i];ranges.emplace_back();auto& out=ranges.back();
            for(size_t j=0;j<r.source_count;++j)out.source.push_back(text(r.source[j]));
            out.side=text(r.side);out.stage=text(r.stage);out.layout=text(r.layout);
            out.quantity=text(r.quantity);out.unit=text(r.unit);out.shape.assign(r.shape,r.shape+r.rank);
            const auto& sample=r.sample;auto& v=out.value;
            v.bounds[0]=r.bounds[0];v.bounds[1]=r.bounds[1];v.size=sample.size;
            v.low=sample.low;v.high=sample.high;v.nonfinite=sample.nonfinite;
            out.minimum=sample.minimum;out.maximum=sample.maximum;
            out.finish(sample.have_finite!=0,sample.minimum_index,sample.maximum_index);
            inlet_ranges.push_back(out.value);
        }
    }
    void final_state_ranges() {
        tpmshx_range_observations_view_v1 last{};
        if(tpmshx_full_2d_get_last_closure_ranges_v1(&raw,&last))
            throw std::runtime_error("native last closure range query failed");
        for(size_t i=0;i<last.size;++i) {
            const auto& r=last.data[i];const std::string stage=r.stage,view=r.view;
            const bool inlet=inlet_stage(stage);
            const bool final=final_stage(stage) && (view!="property_state" || stage=="final" || stage=="richardson-return");
            if(!inlet && !final)continue;
            ranges.emplace_back();auto& out=ranges.back();
            const bool nu=view=="nu" || view=="nu_raw" || view=="nu_pr";
            out.source={r.view,r.model};if(nu)out.source.emplace_back(r.topology);
            out.side=labels[r.side];out.stage=stage;out.layout=r.layout;
            out.quantity=view=="nu_pr"?"Pr":nu?"Re":"T";out.unit=nu?"-":"K";
            out.shape.assign(r.shape,r.shape+r.ndim);out.minimum=r.minimum;out.maximum=r.maximum;
            auto& v=out.value;v.bounds[0]=r.lower;v.bounds[1]=r.upper;v.size=r.size;
            v.low=r.low;v.high=r.high;v.nonfinite=r.nonfinite;
            out.finish(r.have_finite!=0,r.minimum_index,r.maximum_index);
            (inlet?inlet_ranges:final_ranges).push_back(out.value);
        }
    }
    void required_ranges(const char* topology) {
        required_sources[0]={"geometry","L_field_m",nullptr};required_sources[1]={"geometry","t_field_m",nullptr};
        for(size_t i=0;i<2;++i)required[i]={"inlet","shared",required_sources[i].data(),2};
        for(size_t side=0;side<2;++side) {
            const auto offset=2+side*3;
            required_sources[offset]={"nu","air",topology};required_sources[offset+1]={"nu_raw","air",topology};
            required_sources[offset+2]={"property_state","air_cp",nullptr};
            required[offset]={"inlet",labels[side],required_sources[offset].data(),3};
            required[offset+1]={"final",labels[side],required_sources[offset+1].data(),3};
            required[offset+2]={"final",labels[side],required_sources[offset+2].data(),2};
        }
        applicability.version="applicability_evidence_v1";applicability.inlet_recorded=1;
        applicability.inlet=inlet_ranges.data();applicability.inlet_count=inlet_ranges.size();
        applicability.final_state=final_ranges.data();applicability.final_count=final_ranges.size();
        applicability.required=required.data();applicability.required_count=required.size();
    }
    void populate(const tpmshx_preparation_case_2d_v1& p) {
        auto& e=evidence;const auto& main=raw.main;
        e.abi_version=TPMSHX_RESULT_STAGE_ABI_VERSION;e.struct_size=sizeof(e);e.result_id=result_id.c_str();
        e.dimension=2;e.metadata_dimension=&dimension;e.quantity_basis="per_unit_depth";e.mass_unit="kg/(s m)";
        e.mode="full";e.thermal_mode="model_h";e.thermal_state="last main thermal input";
        e.execution="completed";e.converged=static_cast<int>(raw.converged);outer_index=static_cast<int>(raw.iterations)-1;e.outer_index=&outer_index;
        e.grid.widths[0]=array(main.dx,{main.nx});e.grid.widths[1]=array(main.dy,{main.ny});
        for(size_t i=0;i<3;++i)field(i==0?"Ta":i==1?"Tb":"Ts",main.temperature[i],"K","raw last main thermal return");
        for(size_t side=0;side<2;++side) {
            field(side?"P_thermal_B":"P_thermal_A",main.pressure[side],"Pa","last thermal input");
            field(side?"P_report_B":"P_report_A",raw.flow[side].absolute_pressure,"Pa","final flow/report");
            field(side?"h_vB":"h_vA",main.hv[side],"W/(m3 K)","last thermal input");
        }
        field("K_ss",main.solid_conductivity,"W/(m K)","last thermal input");
        for(size_t i=0;i<3;++i)field(i==0?"Ta_display":i==1?"Tb_display":"Ts_display",main.temperature[i],"K","display");
        for(size_t side=0;side<2;++side) {
            field(side?"P_fB_display":"P_fA_display",raw.flow[side].absolute_pressure,"Pa","display");
            field(side?"ucB":"ucA",raw.flow[side].uc,"m/s","final flow/report");
            field(side?"vcB":"vcA",raw.flow[side].vc,"m/s","final flow/report");
        }
        e.fields=main_fields.data();e.field_count=main_fields.size();e.field_metadata=declarations.data();e.field_metadata_count=declarations.size();
        e.split_a=scalar(p.split_a);e.parameter_epsilon=array(main.epsilon,{main.nx,main.ny});e.design_epsilon=e.parameter_epsilon;
        for(size_t side=0;side<2;++side) {
            const auto& s=p.sides[side];const auto& flow=raw.flow[side];direction[side]=s.inlet.port.direction;
            e.direction[side]=&direction[side];e.inlet_temperature[side]=scalar(s.inlet.temperature_K);
            e.inlet_geom_fraction[side]=copy(s.inlet_geometry);e.outlet_geom_fraction[side]=copy(s.outlet_geometry);
            e.rho_cp[side]=array(main.rho_cp[side],{main.nx,main.ny});
            masses[side]={*array(flow.mass_x,{main.nx+1,main.ny}),*array(flow.mass_y,{main.nx,main.ny+1})};
            e.thermal.mass[side]=masses[side].data();e.thermal.mass_count[side]=2;
            auto& pressure=pressures[side];pressure.pressure=array(flow.pressure,{flow.dx.size,flow.dy.size});
            pressure.grid.widths[0]=array(flow.dx,{flow.dx.size});pressure.grid.widths[1]=array(flow.dy,{flow.dy.size});
            pressure.inlet_fraction=array(main.inlet_profile[side],{main.inlet_profile[side].size});
            pressure.outlet_fraction=array(main.outlet_profile[side],{main.outlet_profile[side].size});
            pressure.outlet_geom_fraction=e.outlet_geom_fraction[side];pressure.reference=scalar(flow.reference_pressure);
            pressure.unit="Pa";e.pressure[side]=&pressure;e.active_fluids[side]=1;
            execution[side]={labels[side],"air",1};
        }
        if(tpmshx_full_2d_get_physical_heat_ledger_v1(&raw,&ledgers))throw std::runtime_error("native full 2D heat ledger query failed");
        make_energy(energy[0],ledgers.main,main.nx,main.ny);if(ledgers.main.available)e.thermal.energy=&energy[0].view;
        make_model(model[0],main);e.thermal.model_h=&model[0].view;model_levels[0]={"main",model[0].view};
        e.model_certificates=model_levels.data();e.model_certificate_count=1;e.model_active_b=-1;
        e.richardson_extrapolated=raw.have_fine?static_cast<int>(raw.fine_extrapolated):-1;
        if(raw.have_fine) {
            const auto& f=raw.fine;fine.grid.widths[0]=array(f.dx,{f.nx});fine.grid.widths[1]=array(f.dy,{f.ny});
            for(size_t i=0;i<3;++i)fine_fields.push_back({i==0?"Ta":i==1?"Tb":"Ts",*array(f.temperature[i],{f.nx,f.ny})});
            for(size_t side=0;side<2;++side) {
                fine_fields.push_back({side?"ucB":"ucA",*array(f.uc[side],{f.nx,f.ny})});
                fine_fields.push_back({side?"vcB":"vcA",*array(f.vc[side],{f.nx,f.ny})});
                fine.rho_cp[side]=array(f.rho_cp[side],{f.nx,f.ny});
                fine.inlet_fraction[side]=array(f.inlet_profile[side],{f.inlet_profile[side].size});
                fine.outlet_fraction[side]=array(f.outlet_profile[side],{f.outlet_profile[side].size});
            }
            fine.fields=fine_fields.data();fine.field_count=fine_fields.size();fine.epsilon=array(f.epsilon,{f.nx,f.ny});
            make_energy(energy[1],ledgers.fine,f.nx,f.ny);if(ledgers.fine.available)fine.thermal.energy=&energy[1].view;
            make_model(model[1],f);fine.thermal.model_h=&model[1].view;model_levels[1]={"fine",model[1].view};
            e.model_certificate_count=2;e.fine=&fine;
        }
        gates={{{"simple_ok",static_cast<int>(raw.simple_ok),nullptr,nullptr},{"ltne_ok",static_cast<int>(raw.thermal_ok),nullptr,nullptr},
            {"outer_converged",static_cast<int>(raw.outer_converged),nullptr,nullptr},
            {"richardson_ok",raw.have_fine?(raw.fine.stop==0 && raw.fine_extrapolated?1:0):-1,nullptr,nullptr},
            {"envelope_ok",static_cast<int>(raw.envelope_ok),nullptr,nullptr}}};
        e.convergence_gates=gates.data();e.convergence_gate_count=gates.size();
        e.execution_version="full_execution_v1";e.executed_sides=execution.data();e.executed_side_count=2;
        prepared_ranges(p);final_state_ranges();required_ranges(p.input.topology?"Gyroid":"Diamond");e.applicability=&applicability;
    }
};

Capture2D* capture_2d(const tpmshx_preparation_case_2d_v1& prepared,
    tpmshx_full_2d_result_v2& raw,const tpmshx_full_2d_config_v2& resolved,const char* result_id) {
    auto owner=std::make_unique<Capture2D>();owner->raw=raw;raw={};owner->resolved=resolved;
    owner->result_id=result_id;
    if(resolved.table_directory) {owner->table_directory=resolved.table_directory;owner->resolved.table_directory=owner->table_directory.c_str();}
    owner->populate(prepared);return owner.release();
}
tpmshx_stage_run_result_2d_v1 stage_view(Capture2D& owner) {
    return {TPMSHX_STAGE_RUN_ABI_VERSION,sizeof(tpmshx_stage_run_result_2d_v1),&owner,owner.raw,owner.evidence,owner.resolved};
}
void release_capture_2d(Capture2D* owner) noexcept {delete owner;}
}  // namespace tpmshx::stages
