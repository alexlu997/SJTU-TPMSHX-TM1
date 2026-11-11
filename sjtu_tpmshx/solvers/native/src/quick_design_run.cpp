#include "tpmshx/quick_design_stage_c_api.h"
#include "preparation_c_boundary.hpp"

#include <algorithm>
#include <array>
#include <cstring>
#include <memory>
#include <string>
#include <vector>

namespace {
namespace boundary=tpmshx::fields::c_api;
using tpmshx::preparation::c_api::require_disjoint;
using Array=tpmshx_result_array_v1;
using Scalar=tpmshx_result_scalar_v1;

template<class T> void version(const T* value) {
    boundary::require_buffer(value,1);
    if(value->abi_version!=TPMSHX_QUICK_DESIGN_STAGE_ABI_VERSION || value->struct_size!=sizeof(T))
        throw std::invalid_argument("quick-design stage ABI version or struct size is invalid");
}
Scalar scalar(double value) {
    Scalar result{};result.dtype=TPMSHX_RESULT_F64;result.origin=TPMSHX_RESULT_PYTHON_FLOAT;
    result.byte_order=TPMSHX_RESULT_NATIVE_ENDIAN;std::memcpy(result.data,&value,sizeof(value));return result;
}
constexpr const char* names[]{"Ta","Tb","Ts","ucA","vcA","wcA","ucB","vcB","wcB",
    "K_ffA","K_ffB","K_ss","h_vA","h_vB","eps"};
constexpr const char* units[]{"K","K","K","m/s","m/s","m/s","m/s","m/s","m/s",
    "W/(m K)","W/(m K)","W/(m K)","W/(m3 K)","W/(m3 K)","1"};
struct Owner {
    std::string result_id;
    std::array<size_t,3> shape;
    std::array<ptrdiff_t,3> strides;
    ptrdiff_t width_stride=sizeof(double);
    std::array<std::vector<double>,3> widths;
    std::array<std::vector<double>,15> fields;
    std::vector<double> epsilon_a;
    std::array<Array,3> width_views{};
    std::array<tpmshx_stage_named_array_v1,15> field_views{};
    std::array<tpmshx_stage_field_declaration_v1,15> declarations{};
    std::array<std::array<Scalar,8>,2> side_scalars{};
    Scalar diameter{};
    std::array<tpmshx_stage_pressure_v1,2> pressures{};
    tpmshx_quick_run_result_v1 value{};

    Owner(const tpmshx_quick_prepared_v1& prepared,const char* id):result_id(id),
        shape{prepared.shape[0],prepared.shape[1],prepared.shape[2]} {
        const size_t cells=boundary::product(boundary::product(shape[0],shape[1]),shape[2]);
        if(!cells)throw std::invalid_argument("quick-design state disagrees with prepared grid");
        size_t stride=sizeof(double);
        for(size_t axis=3;axis>0;--axis) {
            if(stride>static_cast<size_t>(PTRDIFF_MAX))throw std::invalid_argument("quick-design field stride overflows ptrdiff_t");
            strides[axis-1]=static_cast<ptrdiff_t>(stride);stride=boundary::product(stride,shape[axis-1]);
        }
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
    Array array(const std::vector<double>& data,size_t rank,const size_t* dimensions,const ptrdiff_t* steps) {
        return {data.data(),boundary::product(data.size(),sizeof(double)),0,TPMSHX_RESULT_F64,
            TPMSHX_RESULT_NUMPY_ARRAY,TPMSHX_RESULT_NATIVE_ENDIAN,0,rank,dimensions,steps};
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
            width_views[axis]=array(widths[axis],1,&shape[axis],&width_stride);
            e.grid.widths[axis]=&width_views[axis];
        }
        for(size_t i=0;i<fields.size();++i) {
            field_views[i]={names[i],array(fields[i],3,shape.data(),strides.data())};
            declarations[i]={names[i],units[i],"last quick-design thermal pass"};
        }
        e.fields=field_views.data();e.field_count=field_views.size();
        e.field_metadata=declarations.data();e.field_metadata_count=declarations.size();
        e.design_epsilon=&field_views[14].value;
        diameter=scalar(config.hydraulic_diameter);e.hydraulic_diameter=&diameter;
        for(size_t side=0;side<2;++side) {
            const auto& inlet=config.sides[side];const auto& s=pass.sides[side];
            side_scalars[side]={scalar(inlet.inlet_temperature),scalar(inlet.mass_flow),scalar(s.cp),
                scalar(s.rho),scalar(s.speed),scalar(s.mu),scalar(raw.pressure[side].inlet),scalar(raw.pressure[side].outlet)};
            auto& v=side_scalars[side];
            e.quick[side]={&v[0],&v[1],&v[2],&v[3],&v[4],&v[5]};
            pressures[side].inlet_absolute=&v[6];pressures[side].outlet_absolute=&v[7];pressures[side].unit="Pa";
            e.pressure[side]=&pressures[side];e.inlet_temperature[side]=&v[0];e.active_fluids[side]=1;
        }
    }
};
}

extern "C" int TPMSHX_THERMAL_CALL tpmshx_run_quick_design_v1(
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
        o.capture(prepared->resolved);*result=o.value;owner.release();boundary::message(error,capacity,"");return TPMSHX_OK;
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
