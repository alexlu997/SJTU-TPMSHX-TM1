#include "tpmshx/quick_design_stage_c_api.h"
#include "stage_entries.hpp"
#include "tpmshx/quick_design_driver.hpp"
#include "tpmshx/temperature_driver_c_api.h"
#include "../preprocess/preparation_c_boundary.hpp"
#include "closure_evidence_c_views.hpp"
#include "closure_ranges.hpp"
#include "stage_records.hpp"

#include <algorithm>
#include <array>
#include <cstring>
#include <cmath>
#include <string_view>
#include <memory>
#include <string>
#include <vector>

namespace {
namespace boundary=tpmshx::fields::c_api;
using tpmshx::preparation::c_api::require_disjoint;
using Array=tpmshx_result_array_v2;

template<class T> void version(const T* value,uint32_t expected=TPMSHX_QUICK_DESIGN_STAGE_ABI_VERSION) {
    boundary::require_buffer(value,1);
    if(value->abi_version!=expected || value->struct_size!=sizeof(T))
        throw std::invalid_argument("quick-design stage ABI version or struct size is invalid");
}
constexpr const char* names[]{"Ta","Tb","Ts","ucA","vcA","wcA","ucB","vcB","wcB",
    "K_ffA","K_ffB","K_ss","h_vA","h_vB","eps"};
constexpr const char* units[]{"K","K","K","m/s","m/s","m/s","m/s","m/s","m/s",
    "W/(m K)","W/(m K)","W/(m K)","W/(m3 K)","W/(m3 K)","1"};
struct PassRanges {
    std::vector<tpmshx::RangeObservation> samples;
    std::vector<tpmshx_range_observation_v1> views;
    tpmshx::stages::StageRangeRecords records;

    void capture(const tpmshx_qd_config_v1& config,const tpmshx_qd_pass_v1& pass,size_t index,size_t side) {
        const auto fluid=static_cast<tpmshx::Fluid>(config.sides[side].fluid);
        const auto topology=static_cast<tpmshx::Topology>(config.topology);
        const auto* stage=index?"design-mean-pass":"design-inlet-pass";
        const auto add=[&](tpmshx::RangeObservation row,double scalar) {
            tpmshx::observe_range_value(row,scalar,0);
            samples.push_back(std::move(row));
        };
        const auto properties=[&](const char* context,double temperature) {
            const auto property=[&](const char* name) {
                add(tpmshx::closure_ranges::property(fluid,name,side,"property",context,"scalar",{}),temperature);
            };
            if(fluid==tpmshx::Fluid::water)property("density");
            property("viscosity");property("conductivity");property("cp");
        };
        if(fluid==tpmshx::Fluid::air || fluid==tpmshx::Fluid::water)
            properties(stage,pass.sides[side].evaluation_temperature);
        if(fluid==tpmshx::Fluid::water)
            properties("design-nu-representative-pr",tpmshx::model_coefficients::water_nu_reference_state[0]);
        add(tpmshx::closure_ranges::nu(fluid,topology,side,"nu",stage,"scalar",{}),pass.sides[side].reynolds);
        for(const auto& sample:samples)views.push_back(tpmshx::range_observation_view(sample));
        records.capture(views.data(),views.size());
    }
};
struct Owner {
    std::string result_id;
    std::array<size_t,3> shape;
    std::array<std::vector<double>,3> widths;
    std::array<std::vector<double>,15> fields;
    std::vector<double> epsilon_a;
    std::array<Array,3> width_views{};
    std::array<tpmshx_stage_named_array_v1,15> field_views{};
    std::array<tpmshx_stage_field_declaration_v1,15> declarations{};
    std::array<std::array<double,8>,2> side_scalars{};
    PassRanges ranges[2][2];
    double diameter{};
    std::array<tpmshx_stage_pressure_v1,2> pressures{};
    tpmshx_quick_run_result_v1 value{};

    Owner(const tpmshx_quick_prepared_v1& prepared,const char* id):result_id(id),
        shape{prepared.shape[0],prepared.shape[1],prepared.shape[2]} {
        const size_t cells=boundary::product(boundary::product(shape[0],shape[1]),shape[2]);
        if(!cells)throw std::invalid_argument("quick-design state disagrees with prepared grid");
        const auto copy=[](std::vector<double>& target,tpmshx_preparation_array_v1 source,size_t expected) {
            boundary::require_buffer(source.data,source.size);
            if(source.size!=expected)throw std::invalid_argument("quick-design prepared array has the wrong extent");
            target.assign(source.data,source.data+source.size);
        };
        for(size_t axis=0;axis<3;++axis)copy(widths[axis],prepared.widths[axis],shape[axis]);
        for(size_t side=0;side<3;++side) {
            if(prepared.resolved.warm_start)copy(fields[side],prepared.initial[side],cells);
            else fields[side].assign(cells,0.);
        }
        copy(fields[14],prepared.epsilon,cells);copy(epsilon_a,prepared.epsilon_a,cells);
        copy(fields[11],prepared.solid_conductivity,cells);
        value.abi_version=TPMSHX_QUICK_DESIGN_STAGE_ABI_VERSION;value.struct_size=sizeof(value);value.owner=this;
    }
    Array array(const std::vector<double>& data,size_t rank,const size_t* dimensions) {
        return {data.data(),rank,dimensions};
    }
    void capture(const tpmshx_qd_config_v1& config) {
        const auto& raw=value.raw;
        const auto& pass=raw.passes[raw.completed_passes-1];
        const auto& a=pass.sides[0];const auto& b=pass.sides[1];
        const bool cross=config.arrangement==TPMSHX_CROSS;
        const size_t cells=fields[0].size();
        const double uniform[]{a.speed,0.,0.,cross?0.:-b.speed,cross?b.speed:0.,0.,a.conductivity,b.conductivity};
        for(size_t i=0;i<8;++i)fields[i+3].assign(cells,uniform[i]);
        fields[12].assign(cells,a.hv);fields[13].assign(cells,b.hv);
        auto& e=value.evidence;
        e.abi_version=TPMSHX_RESULT_STAGE_ABI_VERSION;e.struct_size=sizeof(e);e.result_id=result_id.c_str();
        e.dimension=3;e.quantity_basis="total";e.mode="quick_design";
        e.execution="completed";e.converged=raw.stop==TPMSHX_CONVERGED?1:0;
        e.quick_model="plug_ltne_analytic_dp_v1";e.arrangement=cross?"cross":"counter";
        for(size_t axis=0;axis<3;++axis) {
            width_views[axis]=array(widths[axis],1,&shape[axis]);
            e.grid.widths[axis]=&width_views[axis];
        }
        for(size_t i=0;i<fields.size();++i) {
            field_views[i]={names[i],array(fields[i],3,shape.data())};
            declarations[i]={names[i],units[i],"last quick-design thermal pass"};
        }
        e.fields=field_views.data();e.field_count=field_views.size();
        e.field_metadata=declarations.data();e.field_metadata_count=declarations.size();
        e.design_epsilon=&field_views[14].value;
        diameter=config.hydraulic_diameter;e.hydraulic_diameter=&diameter;
        for(size_t side=0;side<2;++side) {
            const auto& inlet=config.sides[side];const auto& s=pass.sides[side];
            side_scalars[side]={inlet.inlet_temperature,inlet.mass_flow,s.cp,
                s.rho,s.speed,s.mu,raw.pressure[side].inlet,raw.pressure[side].outlet};
            auto& v=side_scalars[side];
            e.quick[side]={&v[0],&v[1],&v[2],&v[3],&v[4],&v[5]};
            pressures[side].inlet_absolute=&v[6];pressures[side].outlet_absolute=&v[7];pressures[side].unit="Pa";
            e.pressure[side]=&pressures[side];e.inlet_temperature[side]=&v[0];e.active_fluids[side]=1;
        }
    }
};
}

static int run_quick_design(
    const tpmshx_quick_prepared_v1* prepared,const tpmshx_quick_run_control_v1* control,
    tpmshx_quick_run_result_v1* result,char* error,size_t capacity) {
    if(!boundary::error_buffer_valid(error,capacity))return TPMSHX_INVALID_ARGUMENT;
    bool report_safe=false;
    try {
        require_disjoint(error,capacity,result,result?1:0);
        const auto storage=[&](const auto* value,size_t size) {
            require_disjoint(error,capacity,value,size);
            require_disjoint(result,result?1:0,value,size);
        };
        storage(prepared,prepared?1:0);storage(control,control?1:0);
        version(prepared);boundary::require_buffer(control,1);
        if(control->result_id) {
            storage(control->result_id,1);
            storage(control->result_id,std::strlen(control->result_id)+1);
        }
        for(const auto values:prepared->widths)storage(values.data,values.size);
        for(const auto values:{prepared->epsilon,prepared->epsilon_a,prepared->solid_conductivity})storage(values.data,values.size);
        if(prepared->resolved.warm_start)for(const auto values:prepared->initial)storage(values.data,values.size);
        report_safe=true;
        version(result);
        if(result->owner)throw std::invalid_argument("release the previous quick-design run owner before reuse");
        if(!control->result_id)throw std::invalid_argument("quick-design run requires a result label");
        auto owner=std::make_unique<Owner>(*prepared,control->result_id);
        auto& o=*owner;
        std::array<std::vector<double>*,9> values{&o.widths[0],&o.widths[1],&o.widths[2],&o.fields[14],
            &o.epsilon_a,&o.fields[11],&o.fields[0],&o.fields[1],&o.fields[2]};
        std::array<double*,9> arrays;std::array<size_t,9> sizes;
        for(size_t i=0;i<values.size();++i) {arrays[i]=values[i]->data();sizes[i]=values[i]->size();}
        const auto status=tpmshx_solve_quick_design_v1(o.shape.data(),arrays.data(),sizes.data(),
            &prepared->resolved,&control->callbacks,&o.value.raw,error,capacity);
        if(status)return status;
        const auto& raw=o.value.raw;
        if(raw.stop==TPMSHX_CANCELLED) {
            boundary::message(error,capacity,"Solver cancelled by user");return TPMSHX_QUICK_STAGE_CANCELLED;
        }
        const size_t expected=prepared->resolved.property_mode==TPMSHX_MEAN?2:1;
        if(raw.stop>TPMSHX_BUDGET_EXHAUSTED || raw.completed_passes!=expected)
            throw std::runtime_error("native Quick Design returned an invalid pass/status contract");
        for(size_t pass=0;pass<raw.completed_passes;++pass)
            for(size_t side=0;side<2;++side)
                o.ranges[pass][side].capture(prepared->resolved,raw.passes[pass],pass,side);
        o.capture(prepared->resolved);*result=o.value;owner.release();boundary::message(error,capacity,"");return TPMSHX_OK;
    } catch(const std::invalid_argument& failure) {
        if(report_safe)boundary::message(error,capacity,failure.what());return TPMSHX_INVALID_ARGUMENT;
    } catch(const std::exception& failure) {
        if(report_safe)boundary::message(error,capacity,failure.what());return TPMSHX_NATIVE_ERROR;
    } catch(...) {
        if(report_safe)boundary::message(error,capacity,"unknown quick-design stage failure");return TPMSHX_NATIVE_ERROR;
    }
}
extern "C" tpmshx_quick_ranges_v2 TPMSHX_THERMAL_CALL tpmshx_quick_run_ranges_v2(
    const tpmshx_quick_run_result_v1* result,size_t pass,size_t side) {
    if(!result || result->abi_version!=1 || result->struct_size!=sizeof(*result) ||
       !result->owner || pass>=2 || side>=2)return {};
    const auto& rows=static_cast<const Owner*>(result->owner)->ranges[pass][side].records.rows;
    return {rows.data(),rows.size()};
}
extern "C" const char* TPMSHX_THERMAL_CALL tpmshx_quick_run_temperature_algorithm_v1(
    const tpmshx_quick_run_result_v1* result) {
    if(!result || result->abi_version!=TPMSHX_QUICK_DESIGN_STAGE_ABI_VERSION ||
       result->struct_size!=sizeof(*result) || !result->owner)return nullptr;
    const auto nz=static_cast<const Owner*>(result->owner)->shape[2];
    const auto scheme=tpmshx::quick_temperature_scheme(nz);
    return tpmshx_temperature_algorithm_v1(scheme==tpmshx::TemperatureScheme::cell_centered_2d
        ? TPMSHX_TEMPERATURE_CC_2D : TPMSHX_TEMPERATURE_CC_3D);
}
extern "C" int TPMSHX_THERMAL_CALL tpmshx_run_quick_design_v2(
    const tpmshx_quick_input_v2* input,const tpmshx_quick_prepared_v2* prepared,
    const tpmshx_quick_run_control_v1* control,tpmshx_quick_run_result_v1* result,char* error,size_t capacity) {
    if(!boundary::error_buffer_valid(error,capacity))return TPMSHX_INVALID_ARGUMENT;
    bool report_safe=false;
    try {
        require_disjoint(error,capacity,result,result?1:0);
        const auto storage=[&](const auto* pointer,size_t count) {
            boundary::require_buffer(pointer,count);
            require_disjoint(error,capacity,pointer,count);
            require_disjoint(result,result?1:0,pointer,count);
        };
        storage(input,1);storage(prepared,1);storage(control,1);
        version(input,2);version(prepared,2);
        if(control->result_id) {
            storage(control->result_id,1);
            storage(control->result_id,std::strlen(control->result_id)+1);
        }
        for(const auto label:{input->topology,input->arrangement,input->property_mode,input->fluids[0],input->fluids[1]})
            storage(label.data,label.size);
        for(size_t i=0;i<3;++i) {
            for(const auto array:{input->initial[i],prepared->initial[i],prepared->widths[i],prepared->edges[i]})
                storage(array.data,array.size);
        }
        for(const auto array:{prepared->epsilon,prepared->epsilon_a,prepared->solid_conductivity})
            storage(array.data,array.size);
        report_safe=true;
        const auto select=[](tpmshx_preparation_text_v1 label,std::initializer_list<std::string_view> choices,
                             const char* message) {
            const std::string_view name(label.data?label.data:"",label.size);
            const auto found=std::find(choices.begin(),choices.end(),name);
            if(found==choices.end())throw std::invalid_argument(message);
            return static_cast<uint32_t>(found-choices.begin());
        };
        tpmshx_quick_prepared_v1 view{};
        view.abi_version=1;view.struct_size=sizeof(view);
        std::copy_n(prepared->shape,3,view.shape);
        std::copy_n(prepared->widths,3,view.widths);
        std::copy_n(prepared->initial,3,view.initial);
        view.epsilon=prepared->epsilon;view.epsilon_a=prepared->epsilon_a;view.solid_conductivity=prepared->solid_conductivity;
        auto& c=view.resolved;
        const auto& settings=prepared->controls;
        if(input->warm_start>1 || input->have_height>1 || settings.have_chunk_iterations>1 ||
           settings.have_q_relative_tolerance>1)throw std::invalid_argument("quick-design flags require 0 or 1");
        c.warm_start=input->warm_start;
        c.topology=select(input->topology,{"Diamond","Gyroid"},"unsupported quick-design topology");
        c.arrangement=select(input->arrangement,{"cross","counter"},"unsupported quick-design arrangement or property model");
        c.property_mode=select(input->property_mode,{"const","mean"},"unsupported quick-design arrangement or property model");
        if(settings.dir_b!=(c.arrangement==TPMSHX_CROSS?2u:1u))
            throw std::invalid_argument("quick-design flow direction disagrees with arrangement");
        c.length=input->values[TPMSHX_QUICK_LENGTH];c.span=input->values[TPMSHX_QUICK_SPAN];
        c.height=input->have_height?input->values[TPMSHX_QUICK_HEIGHT]:c.span;
        c.cell_length=prepared->cell_length_m;c.area_density=prepared->geometry.area_density_per_m;
        c.hydraulic_diameter=prepared->geometry.hydraulic_diameter_m;
        for(size_t i=0;i<2;++i) {
            c.sides[i]={select(input->fluids[i],{"air","water","sco2"},"unsupported quick-design fluid"),
                input->values[TPMSHX_QUICK_TEMPERATURE_A+i],input->values[TPMSHX_QUICK_PRESSURE_A+i],
                input->values[TPMSHX_QUICK_MASS_A+i],prepared->fractions[i]};
        }
        if(settings.ny!=view.shape[1] || settings.nz!=view.shape[2])
            throw std::invalid_argument("quick-design state disagrees with prepared grid");
        if(c.warm_start)for(size_t axis=0;axis<3;++axis)
            if(input->initial_shape[axis]!=view.shape[axis])
                throw std::invalid_argument("quick-design warm start disagrees with prepared grid");
        const auto tol=input->values[TPMSHX_QUICK_TOLERANCE];
        if(!std::isfinite(tol) || tol<=0.)throw std::invalid_argument("quick-design tol must be finite and positive");
        const bool plane=prepared->shape[2]==1;
        c.q_relative_tolerance=settings.have_q_relative_tolerance?settings.q_relative_tolerance:
            (plane?std::min(tol*2e-3,1e-3):std::max(tol*10.,1e-4));
        c.chunk_iterations=settings.have_chunk_iterations?settings.chunk_iterations:(plane?500u:250u);
        c.max_iterations=settings.max_iterations;c.alpha=settings.alpha;
        return run_quick_design(&view,control,result,error,capacity);
    } catch(const std::invalid_argument& failure) {
        if(report_safe)boundary::message(error,capacity,failure.what());return TPMSHX_INVALID_ARGUMENT;
    } catch(const std::exception& failure) {
        if(report_safe)boundary::message(error,capacity,failure.what());return TPMSHX_NATIVE_ERROR;
    } catch(...) {
        if(report_safe)boundary::message(error,capacity,"unknown quick-design stage failure");return TPMSHX_NATIVE_ERROR;
    }
}
extern "C" void TPMSHX_THERMAL_CALL tpmshx_quick_run_release_v1(tpmshx_quick_run_result_v1* result) {
    if(!result)return;
    delete static_cast<Owner*>(result->owner);*result={};
}
