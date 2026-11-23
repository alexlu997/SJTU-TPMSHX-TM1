#include "tpmshx/stage_run_c_api.h"
#include "stage_capture_2d.hpp"
#include "enthalpy_c_views.hpp"
#include "tpmshx/preparation_flow.hpp"
#include "tpmshx/preparation_df.hpp"
#include "tpmshx/grid.hpp"
#include "stage_saved_models.hpp"
#include "../geometry/field_c_boundary.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <string_view>
#include <type_traits>
#include <vector>

namespace {
namespace boundary=tpmshx::fields::c_api;
bool overlaps(const void* a,size_t a_bytes,const void* b,size_t b_bytes) {
    if(!a_bytes || !b_bytes)return false;
    const auto first=reinterpret_cast<uintptr_t>(a),second=reinterpret_cast<uintptr_t>(b);
    return first<=second+b_bytes-1 && second<=first+a_bytes-1;
}
void flag(uint32_t value) {
    if (value>1) throw std::invalid_argument("stage run option flags require 0 or 1");
}
double number(tpmshx_stage_double_option_v1 option,double fallback,const char* name) {
    flag(option.present);
    if (!option.present) return fallback;
    if (!std::isfinite(option.value) || option.value<=0.)
        throw std::invalid_argument(std::string(name)+" must be positive and finite");
    return option.value;
}
size_t count(tpmshx_stage_size_option_v1 option,size_t fallback,size_t minimum,const char* name) {
    flag(option.present);
    if (!option.present) return fallback;
    if (option.value<minimum) throw std::invalid_argument(std::string(name)+" is below its minimum");
    return option.value;
}
void array(tpmshx_preparation_array_v1 input,size_t size) {
    boundary::require_buffer(input.data,input.size);
    if (input.size!=size) throw std::invalid_argument("prepared stage array has the wrong extent");
}
template<class Storage> void preparation_storage(const Storage& storage,
    const tpmshx_preparation_case_2d_v1*& prepared,const tpmshx_preparation_case_2d_v2*& uniform,
    const tpmshx_stage_saved_case_2d_v1* saved,const tpmshx_stage_saved_case_2d_v2* saved_v2) {
    storage(saved_v2,1);
    if(saved_v2->abi_version!=TPMSHX_STAGE_RUN_ABI_VERSION_V2 || saved_v2->struct_size!=sizeof(*saved_v2))
        throw std::invalid_argument("saved stage v2 ABI version or struct size is invalid");
    flag(saved_v2->have_side_geometry);
    storage(saved,1);
    if(saved->abi_version!=TPMSHX_STAGE_RUN_ABI_VERSION || saved->struct_size!=sizeof(*saved))
        throw std::invalid_argument("saved stage ABI version or struct size is invalid");
    uniform=saved->prepared;flag(saved->inlet_recorded);
    for(const auto value:{saved->area_density_per_m,saved->hydraulic_diameter_m,
            saved->fluid_conductivity[0],saved->fluid_conductivity[1]})storage(value.data,value.size);
    storage(uniform,1);
    if(uniform->abi_version!=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2 || uniform->struct_size!=sizeof(*uniform))
        throw std::invalid_argument("prepared stage v2 ABI version or struct size is invalid");
    prepared=&uniform->values;
    storage(uniform->notices,uniform->notice_count);
    for(size_t i=0;i<uniform->notice_count;++i)storage(uniform->notices[i].data,uniform->notices[i].size);
    storage(prepared,1);
    if(prepared->abi_version!=TPMSHX_PREPARATION_CASE_ABI_VERSION || prepared->struct_size!=sizeof(*prepared))
        throw std::invalid_argument("prepared stage ABI version or struct size is invalid");
    for(const auto value:{prepared->dx,prepared->dy,prepared->total_porosity,prepared->solid_conductivity})
        storage(value.data,value.size);
    if(prepared->input.geometry_mode==1 || prepared->input.geometry_mode==2)
        storage(prepared->cell_length.data,prepared->cell_length.size);
    for(const auto& side:prepared->sides)
        for(const auto value:{side.row_permeability,side.row_forchheimer,side.permeability,side.forchheimer,side.inlet_geometry,
            side.outlet_geometry,side.inlet_profile,side.outlet_profile,side.outlet_u_fraction})
            storage(value.data,value.size);
    storage(prepared->ranges,prepared->range_count);
    if(saved->range_captured) {
        storage(saved->range_captured,prepared->range_count);
        for(size_t i=0;i<prepared->range_count;++i)flag(saved->range_captured[i]);
    }
    for(size_t i=0;i<prepared->range_count;++i) {
        const auto& range=prepared->ranges[i];storage(range.source,range.source_count);storage(range.shape,range.rank);
        for(size_t j=0;j<range.source_count;++j)storage(range.source[j].data,range.source[j].size);
        for(const auto value:{range.side,range.stage,range.layout,range.quantity,range.unit})storage(value.data,value.size);
    }
}
template<class Storage> void saved_v3_storage(const Storage& storage,const tpmshx_stage_saved_case_2d_v3& saved) {
    storage(&saved,1);
    for (const auto& grid:saved.flow_grid) {
        storage(grid.cross.data,grid.cross.size);
        storage(grid.stream.data,grid.stream.size);
    }
    const auto& prepared=*saved.values.values.prepared;
    for (const auto field:{prepared.values.cell_length,prepared.values.wall_thickness,
                           prepared.values.hydraulic_radius}) storage(field.data,field.size);
    storage(saved.additional_fields,saved.additional_count);
    for (size_t i=0;i<saved.additional_count;++i) {
        const auto& item=saved.additional_fields[i];
        storage(item.name.data,item.name.size);
        storage(item.values.data,item.values.size);
    }
    const auto check_text=[&](tpmshx_preparation_text_v1 value){storage(value.data,value.size);};
    for (const auto& model:prepared.values.models) {check_text(model.name);check_text(model.version);}
    check_text(saved.resource_topology);
    for (const auto& fluid:saved.resource_fluids) check_text(fluid);
    for (const auto* nu:{&prepared.sco2_nu,&saved.resource_nu[0],&saved.resource_nu[1]}) {
        check_text(nu->parameter_version);check_text(nu->source);check_text(nu->applicability);
    }
}
using tpmshx::stages::text_view;

void validate_saved_design(const tpmshx_stage_saved_case_2d_v3& saved,
                           const tpmshx_preparation_case_2d_v2& uniform,size_t cells) {
    const auto& p=uniform.values;
    const bool spatial=p.input.geometry_mode!=0;
    const auto field=[&](const char* name,tpmshx_preparation_array_v1 data,size_t index,double reference,bool length) {
        if (spatial && index==4 && !data.size) return;
        array(data,cells);
        const double expected=length?reference*1e3:reference;
        for (size_t i=0;i<cells;++i) {
            const double value=length?data.data[i]*1e3:data.data[i];
            if (!std::isfinite(value))
                throw std::invalid_argument(std::string("prepared design field ")+name+" does not match the physical grid");
            if (spatial && length && value<=0.)
                throw std::invalid_argument(std::string("prepared zoned 2D case requires a positive ")+name+
                    "; prepare the original configuration again");
            if (!spatial && (value!=expected || !std::isfinite(expected)))
                throw std::invalid_argument(std::string("uniform design field ")+name+" disagrees with its scalar input");
        }
    };
    field("L_field",p.cell_length,0,p.cell_length_m,true);
    field("t_field",p.wall_thickness,1,p.wall_thickness_m,true);
    field("eps_arr",p.total_porosity,2,p.epsilon,false);
    field("r_h_arr",p.hydraulic_radius,4,p.hydraulic_radius_m,false);
    for (size_t i=0;i<cells;++i) {
        const auto k=p.solid_conductivity.data[i];
        if (!std::isfinite(k)) throw std::invalid_argument("prepared design field K_ss_arr does not match the physical grid");
        if (!spatial && (k<=0. || k!=p.solid_conductivity.data[0]))
            throw std::invalid_argument("uniform solid conductivity must be positive and uniform");
    }
    for (size_t i=0;i<saved.additional_count;++i) {
        const auto& item=saved.additional_fields[i];array(item.values,cells);
        if (!std::all_of(item.values.data,item.values.data+cells,[](double x){return std::isfinite(x);}))
            throw std::invalid_argument("prepared design field "+std::string(text_view(item.name))+
                " does not match the physical grid");
    }
}

void validate_saved_drag(const tpmshx_preparation_side_2d_v1& side,const std::string& label,
                         size_t stream,size_t cells,bool continuous) {
    const auto valid=[](double value,bool positive) {
        return std::isfinite(value) && (positive ? value>0. : value>=0.);
    };
    const auto values=[&](tpmshx_preparation_array_v1 data,size_t size,bool positive,const char* key,bool local) {
        if (data.size!=size || !std::all_of(data.data,data.data+data.size,[&](double v){return valid(v,positive);}))
            throw std::invalid_argument(std::string("invalid prepared ")+(local?"local ":"")+"flow "+label+" "+key);
    };
    values(side.row_permeability,stream,true,"K_m2",false);
    values(side.row_forchheimer,stream,false,"cF_per_m",false);
    if (!valid(side.seed_permeability_m2,true)) throw std::invalid_argument("invalid prepared flow "+label+" seed_K_m2");
    if (!valid(side.seed_forchheimer_per_m,false)) throw std::invalid_argument("invalid prepared flow "+label+" seed_cF_per_m");
    if (continuous) {
        values(side.permeability,cells,true,"K_field_m2",true);
        values(side.forchheimer,cells,false,"cF_field_per_m",true);
    }
}

std::vector<double> saved_outlet(const tpmshx_preparation_case_2d_v1& prepared,
    const tpmshx_stage_saved_flow_grid_2d_v3& grid, size_t index) {
    const auto& side = prepared.sides[index];
    const auto direction = grid.direction;
    if (direction > 3 || direction != static_cast<uint32_t>(side.inlet.port.direction))
        throw std::invalid_argument("prepared flow direction disagrees with the solver direction");
    const auto cross = direction < 2 ? prepared.dy : prepared.dx;
    const auto stream = direction < 2 ? prepared.dx : prepared.dy;
    const std::string label = index ? "B" : "A";
    const bool reverse = direction == 1 || direction == 3;
    if (grid.cross.size != cross.size || grid.stream.size != stream.size ||
        !std::equal(cross.data, cross.data + cross.size, grid.cross.data))
        throw std::invalid_argument("prepared flow " + label + " grid disagrees with the thermal grid");
    for (size_t i = 0; i < stream.size; ++i)
        if (grid.stream.data[i] != stream.data[reverse ? stream.size - 1 - i : i])
            throw std::invalid_argument("prepared flow " + label + " grid disagrees with the thermal grid");
    const auto bound = [&](size_t i) {
        const auto& value = grid.bounds[i];
        const double expected = i < 2 ? side.inlet_bounds[i] : side.outlet_bounds[i-2];
        if (value != expected) throw std::invalid_argument("saved port bounds disagree");
        return value;
    };
    const tpmshx::ArrayView<const double> widths{cross.data,cross.size};
    for (size_t end = 0; end < 2; ++end) {
        const auto expected = tpmshx::port_fractions_1d_unchecked(widths,
            bound(2*end),bound(2*end+1),end == 0 && side.inlet.port.uniform_inlet);
        const auto check = [&](tpmshx_preparation_array_v1 saved,const std::vector<double>& wanted,const char* kind) {
            if (saved.size != wanted.size() || !std::equal(wanted.begin(),wanted.end(),saved.data,
                [](double reference,double actual) {return std::abs(actual-reference) <= 1e-15+1e-12*std::abs(reference);}))
                throw std::invalid_argument("prepared Fluid " + label + (end ? " out_" : " in_") + kind +
                    "_frac disagrees with its grid and port geometry");
        };
        check(end ? side.outlet_geometry : side.inlet_geometry,expected.first,"geom");
        check(end ? side.outlet_profile : side.inlet_profile,expected.second,"profile");
    }
    return tpmshx::port_overlap_1d_unchecked(widths,bound(2),bound(3),true);
}
struct Packed2D {
    std::array<size_t,2> shape;
    std::array<std::vector<double>,6> fields;
    std::array<std::vector<double>,2> outlets;
    std::array<const double*,29> arrays;
    std::array<size_t,29> sizes;
    double depth=1.;
    tpmshx_full_2d_config_v2 config{};
    tpmshx_energy_options_v1 energy = tpmshx::default_stage_energy_options();
    tpmshx_full_2d_energy_control_v4 partial_energy{};
    const tpmshx_full_2d_energy_control_v4* explicit_energy=nullptr;
    Packed2D(const tpmshx_preparation_case_2d_v1& p,const tpmshx_stage_run_request_2d_v1& request,
             const tpmshx_stage_run_control_v1& control,const tpmshx_preparation_case_2d_v2* uniform,
             const char* envelope,const tpmshx_stage_run_request_2d_v3* partial,
             const tpmshx_stage_saved_case_2d_v1* saved,const tpmshx_stage_saved_case_2d_v2* saved_v2,
             const tpmshx_stage_saved_case_2d_v3* saved_v3):shape{p.nx,p.ny} {
        if (p.abi_version!=TPMSHX_PREPARATION_CASE_ABI_VERSION || p.struct_size!=sizeof(p))
            throw std::invalid_argument("prepared stage ABI version or struct size is invalid");
        if (!p.nx || !p.ny) throw std::invalid_argument("prepared stage requires nonempty physical axes");
        const auto cells=boundary::product(p.nx,p.ny);
        const bool spatial=p.input.geometry_mode==1 || p.input.geometry_mode==2;
        if (p.input.geometry_mode>2u || p.input.df_mode>1u
            || p.sides[0].inlet.fluid>3u || p.sides[1].inlet.fluid>3u)
            throw std::invalid_argument("stage run requires supported uniform symmetric preparation");
        array(p.dx,p.nx);array(p.dy,p.ny);array(p.total_porosity,cells);array(p.solid_conductivity,cells);
        {
            tpmshx::stages::validate_saved_models(p.models,uniform->sco2_nu,saved_v3->resource_nu,
                saved_v3->resource_fluids,saved_v3->resource_topology,
                {p.sides[0].inlet.fluid,p.sides[1].inlet.fluid},p.input.topology,false);
            validate_saved_design(*saved_v3,*uniform,cells);
            const tpmshx_preparation_array_v1 widths[]{p.dx,p.dy};
            for (size_t axis=0; axis<2; ++axis) {
                double length=0.;
                for (size_t i=0; i<widths[axis].size; ++i) length+=widths[axis].data[i];
                const auto expected=saved_v3->lengths_m[axis];
                if (!std::isfinite(expected) || !(std::abs(length-expected)<=1e-15+1e-12*std::abs(expected)))
                    throw std::invalid_argument(std::string("prepared ")+(axis?"y":"x")+" grid does not cover the physical domain");
            }
        }
        if (p.input.topology>1) throw std::invalid_argument("stage run requires Diamond or Gyroid");
        if (request.convergence_mode && std::strcmp(request.convergence_mode,"f2")!=0)
            throw std::invalid_argument("convergence_mode must be 'f2'; the legacy mass/velocity exit has been retired");
        auto set=[&](size_t i,tpmshx_preparation_array_v1 value) {arrays[i]=value.data;sizes[i]=value.size;};
        set(0,p.dx);set(1,p.dy);arrays[2]=&depth;sizes[2]=1;
        const double reference=p.cell_length_m*1e3;
        std::vector<double> cell_mm(cells,reference);
        const auto area=saved->area_density_per_m;
        const auto diameter=saved->hydraulic_diameter_m;
        if(spatial) {
            const auto conductivity_a=saved->fluid_conductivity[0];
            const auto conductivity_b=saved->fluid_conductivity[1];
            for(const auto value:{p.cell_length,area,diameter,conductivity_a,conductivity_b})array(value,cells);
            fields[4].resize(cells);
            for(size_t i=0;i<cells;++i) {
                cell_mm[i]=p.cell_length.data[i]*1e3;
                fields[4][i]=cell_mm[i]*1e-3;
            }
            set(3,conductivity_a);set(4,conductivity_b);set(7,area);set(8,diameter);
        } else {
            const double values[]{p.sides[0].properties.fluid_conductivity_W_mK,
                p.sides[1].properties.fluid_conductivity_W_mK,p.area_density_per_m,
                p.hydraulic_diameter_m,reference*1e-3};
            for (size_t i=0;i<5;++i) fields[i].assign(cells,values[i]);
            set(3,{fields[0].data(),cells});set(4,{fields[1].data(),cells});
            set(7,{fields[2].data(),cells});set(8,{fields[3].data(),cells});
            if(saved->fluid_conductivity[0].size || saved->fluid_conductivity[1].size)
                throw std::invalid_argument("saved uniform stage uses inlet conductivity properties");
            if(area.size || diameter.size) {
                array(area,cells);array(diameter,cells);set(7,area);set(8,diameter);
            }
        }
        fields[5]=tpmshx::preparation::closure_geometry_ratio({arrays[8],cells},{cell_mm.data(),cells});
        set(5,p.solid_conductivity);set(6,p.total_porosity);
        set(9,{fields[4].data(),cells});
        set(28,{fields[5].data(),cells});
        auto& c=config;
        const bool eos=(p.sides[0].inlet.fluid>=2 || p.sides[1].inlet.fluid>=2) && p.input.geometry_mode!=2;
        const bool water=p.sides[0].inlet.fluid==1 || p.sides[1].inlet.fluid==1;
        c.asymmetric=p.input.delta_levelset!=0.;
        c.topology=p.input.topology;c.thermal_mode=eos?2:!c.asymmetric && p.input.geometry_mode!=2?1:0;
        c.spatial_geometry=spatial?1:0;
        c.reference_cell_length=reference*1e-3;
        c.reference_porosity=!spatial?p.total_porosity.data[0]:p.epsilon;c.split_a=p.split_a;c.sco2_nu_multiplier=1.;
        if(eos && uniform->sco2_nu.mode)c.sco2_nu_multiplier=uniform->sco2_nu.alpha[p.input.topology];
        flag(request.solid_seed_K.present);c.have_solid_seed=request.solid_seed_K.present;
        c.solid_seed=number(request.solid_seed_K,0.,"solid_seed_K");
        flag(request.have_pressure_shooting);flag(request.pressure_shooting);
        c.pressure_shooting=request.have_pressure_shooting?request.pressure_shooting:1;
        for (size_t side=0;side<2;++side) {
            const auto& s=p.sides[side];const auto& port=s.inlet.port;
            if (port.direction<0 || port.direction>3) throw std::invalid_argument("invalid 2D stage direction");
            flag(port.uniform_inlet);
            const size_t cross=port.direction<2?p.ny:p.nx,stream=port.direction<2?p.nx:p.ny;
            validate_saved_drag(s,side?"B":"A",stream,cells,p.input.geometry_mode==1);
            array(s.row_permeability,stream);array(s.row_forchheimer,stream);
            array(s.inlet_geometry,cross);array(s.outlet_geometry,cross);
            array(s.inlet_profile,cross);array(s.outlet_profile,cross);auto outlet = s.outlet_u_fraction;
            if (outlet.size) throw std::invalid_argument("saved v3 computes its staggered outlet");
            outlets[side] = saved_outlet(p,saved_v3->flow_grid[side],side);
            outlet = {outlets[side].data(),outlets[side].size()};
            array(outlet,cross+1);
            const std::array<tpmshx_preparation_array_v1,9> side_arrays{s.row_permeability,s.row_forchheimer,
                s.permeability,s.forchheimer,s.inlet_geometry,s.outlet_geometry,s.inlet_profile,s.outlet_profile,
                outlet};
            for(size_t i=0;i<9;++i)set(10+9*side+i,side_arrays[i]);
            c.sides[side]={s.inlet.fluid,static_cast<uint32_t>(port.direction),port.uniform_inlet,
                s.inlet.temperature_K,s.inlet.pressure_Pa,s.inlet.velocity_m_s,s.properties.mu,
                s.seed_permeability_m2,s.seed_forchheimer_per_m,s.inlet_bounds[0],s.inlet_bounds[1],
                s.outlet_bounds[0],s.outlet_bounds[1],0.,0.,0.,0.};
            if(saved_v2->have_side_geometry) {
                const auto* geometry=saved_v2->side_geometry[side];
                c.sides[side].side_area_density=geometry[0];c.sides[side].side_hydraulic_diameter=geometry[1];
                c.sides[side].reference_area_density=geometry[2];c.sides[side].reference_hydraulic_diameter=geometry[3];
            }
        }
        c.f2={number(request.mom_tol,1e-4,"mom_tol"),number(request.mass_local_tol,1e-6,"mass_local_tol"),
            number(request.mass_global_tol,1e-6,"mass_global_tol"),.01,1e-4,1e-3,2,5,60};
        c.simple_iterations=count(request.max_iter_simple,10000,1,"max_iter_simple");c.simple_sweeps=2;
        c.outer_iterations=count(request.max_outer_ltne,10,2,"max_outer_ltne");
        c.outer_temperature_tolerance=number(request.outer_tol_K,1.,"outer_tol_K");
        c.outer_density_tolerance=.01;c.outer_relaxation=.7;
        if(request.energy)energy=*request.energy;
        if(eos) {
            tpmshx_energy_effective_settings_v1 defaults{};
            if(tpmshx_full_enthalpy_defaults_v1(2,energy.algorithm,water?1:0,&defaults))
                throw std::invalid_argument("invalid native full enthalpy defaults request");
            c.thermal_iterations=defaults.max_iterations;c.enthalpy_update_tolerance=defaults.update_tolerance;
            c.thermal_chunk=3;c.thermal_q_tolerance=.1*2e-3;
        } else {
            c.thermal_iterations=water?12000:5000;c.thermal_chunk=500;c.thermal_q_tolerance=1e-3;
            c.enthalpy_update_tolerance=water?.01:.005;
        }
        c.alpha_velocity=number(request.simple_velocity_relaxation,.7,"simple_velocity_relaxation");
        if(c.alpha_velocity>1.)throw std::invalid_argument("simple_velocity_relaxation must be in (0, 1]");
        c.alpha_pressure=.3;c.alpha_density=.3;c.gas_constant=287.05;c.cf_anisotropy=0.;
        c.massflux_inlet=1;c.close_outlet_on_exit=1;c.envelope_mode=envelope?envelope:"raise";c.table_directory=control.table_directory;
        if(request.explicit_energy && !eos)
            throw std::invalid_argument("explicit full 2D energy controls require the existing true-h route");
        explicit_energy=request.explicit_energy;
        if(partial) {
            flag(partial->require_enthalpy_update_on_temperature);
            for(const auto present:{partial->energy_iterations.present,partial->energy_sweeps.present,
                    partial->energy_omega.present,partial->energy_update_tolerance.present,
                    partial->energy_coupled_tolerance.present,partial->energy_equation_tolerance.present})flag(present);
            if(partial->energy_iterations.present || partial->energy_sweeps.present || partial->energy_omega.present
                || partial->energy_update_tolerance.present || partial->energy_coupled_tolerance.present
                || partial->energy_equation_tolerance.present || partial->require_enthalpy_update_on_temperature) {
                if(explicit_energy)throw std::invalid_argument("conflicting full energy options");
                if(!eos)throw std::invalid_argument("explicit full 2D energy controls require the existing true-h route");
                tpmshx_energy_effective_settings_v1 defaults{};
                if(tpmshx_full_enthalpy_defaults_v1(2,energy.algorithm,water?1:0,&defaults))
                    throw std::invalid_argument("invalid native full enthalpy defaults request");
                partial_energy={count(partial->energy_iterations,defaults.max_iterations,1,"energy_iterations"),
                    count(partial->energy_sweeps,defaults.sweeps,0,"energy_sweeps"),
                    number(partial->energy_omega,defaults.omega,"energy_omega"),
                    number(partial->energy_update_tolerance,defaults.update_tolerance,"energy_update_tolerance"),
                    {energy.algorithm,energy.temperature_update_tolerance,
                     number(partial->energy_coupled_tolerance,defaults.coupled_energy_tolerance,"energy_coupled_tolerance"),
                     number(partial->energy_equation_tolerance,defaults.equation_energy_tolerance,"energy_equation_tolerance"),
                     partial->require_enthalpy_update_on_temperature}};
                explicit_energy=&partial_energy;
            }
        }
    }
};
struct StageRun2D {
    void* run=nullptr;
    const tpmshx_preparation_case_2d_v1* prepared;
    const tpmshx_preparation_case_2d_v2* uniform;
    const tpmshx_stage_saved_case_2d_v1* saved;
    const tpmshx_stage_saved_case_2d_v2* saved_v2;
    const tpmshx_stage_saved_case_2d_v3* saved_v3;
    tpmshx_full_2d_config_v2 config;
    std::string result_id,table_directory,envelope_mode;
    StageRun2D(const tpmshx_preparation_case_2d_v1* p,const tpmshx_preparation_case_2d_v2* u,
        const tpmshx_full_2d_config_v2& c,const char* id,
        const tpmshx_stage_saved_case_2d_v1* saved_case,const tpmshx_stage_saved_case_2d_v2* saved_case_v2,const tpmshx_stage_saved_case_2d_v3* saved_case_v3)
        :prepared(p),uniform(u),saved(saved_case),saved_v2(saved_case_v2),saved_v3(saved_case_v3),config(c),result_id(id),
        table_directory(c.table_directory?c.table_directory:""),envelope_mode(c.envelope_mode?c.envelope_mode:"") {
        config.table_directory=c.table_directory?table_directory.c_str():nullptr;
        config.envelope_mode=c.envelope_mode?envelope_mode.c_str():nullptr;
    }
    ~StageRun2D() {tpmshx_full_2d_run_release_v1(&run);}
};
void validate_saved_experiment(const tpmshx_stage_experiment_2d_v4& settings,
    const tpmshx_preparation_case_2d_v1* prepared=nullptr) {
    namespace preparation=tpmshx::preparation;
    const auto positive=[](double value) {return std::isfinite(value) && value>0.;};
    if (settings.topology>1 || settings.geometry_mode>2 || settings.domain_count<2 || settings.domain_count>3
            || settings.fluids[0]>3 || settings.fluids[1]>3
            || !positive(settings.cell_length_mm) || !positive(settings.wall_thickness_mm)
            || !std::isfinite(settings.delta_levelset)
            || !std::all_of(settings.domain_m,settings.domain_m+settings.domain_count,positive))
        throw std::invalid_argument("invalid saved experimental settings");
    if (prepared && (settings.topology!=prepared->input.topology
            || settings.fluids[0]!=prepared->sides[0].inlet.fluid
            || settings.fluids[1]!=prepared->sides[1].inlet.fluid))
        throw std::invalid_argument("saved experimental topology or fluids disagree with the prepared case");
    const auto geometry_mode=prepared?prepared->input.geometry_mode:settings.geometry_mode;
    const auto scope=preparation::df_experiment_scope(settings.topology,settings.fluids[0],settings.fluids[1],
        geometry_mode,settings.delta_levelset==0.,settings.cell_length_mm,settings.wall_thickness_mm,
        {settings.domain_m,settings.domain_count});
    if (!(scope&TPMSHX_DF_EXPERIMENT_LAYOUT))
        throw std::invalid_argument(preparation::experimental_layout_error);
    for (std::size_t side=0;side<2;++side) {
        flag(settings.configured_flow[side]);
        if (settings.configured_flow[side] && !prepared) continue;
        const double speed=prepared?prepared->sides[side].inlet.velocity_m_s:settings.velocity_m_s[side];
        if (!positive(speed)) throw std::invalid_argument("invalid saved experimental inlet velocity");
        if (settings.fluids[side]==3) continue;
        try {
            const auto selected=preparation::df_experiment_side(settings.topology,settings.fluids[side],
                settings.cell_length_mm,settings.wall_thickness_mm,speed,
                (scope&TPMSHX_DF_HX_TRANSFER)!=0).first;
            if (selected.scope && !(scope&TPMSHX_DF_HX_DOMAIN))
                throw std::invalid_argument(preparation::experimental_domain_error(side));
        } catch (const preparation::DfExperimentError& problem) {
            throw preparation::DfExperimentError("experimental calibration unavailable for active side "+
                std::string(side?"B":"A")+": "+problem.what(),problem.velocity_window);
        }
    }
}

bool same_experimental_reference(double mm,double m) {
    const double expected=mm*1e-3;
    // The archive's SI round trip can change a double by a few ULPs.
    return std::isfinite(m) && std::isfinite(expected)
        && std::abs(expected-m)<=8.*std::numeric_limits<double>::epsilon()*std::abs(expected);
}

struct StartRun {
    const tpmshx_stage_run_request_2d_v3* request;
    void** output;
    const tpmshx_run_state_field_v1* fields=nullptr;
    size_t count=0;
    bool restore=false;
    const tpmshx_stage_saved_case_2d_v1* saved=nullptr;
    const tpmshx_stage_saved_case_2d_v2* saved_v2=nullptr;
    const tpmshx_stage_saved_case_2d_v3* saved_v3=nullptr;
    const tpmshx_stage_saved_case_2d_v4* saved_v4=nullptr;
};
}

namespace {
// Each public entry supplies one saved v4 descriptor. The run either returns a
// handle (create and restore) or runs to completion and transfers the result.
int run(const tpmshx_stage_run_control_v1* control,tpmshx_stage_run_result_2d_v1* result,
    char* error,size_t capacity,const StartRun& start) {
    if(!boundary::error_buffer_valid(error,capacity))return 1;
    bool report_safe=false;
    try {
        const bool return_handle=start.output!=nullptr;
        if(return_handle)boundary::require_buffer(start.output,1);
        else boundary::require_buffer(result,1);
        const void* output=return_handle?static_cast<void*>(start.output):result;
        const size_t output_size=return_handle?sizeof(*start.output):sizeof(*result);
        if(overlaps(output,output_size,error,capacity)) {
            report_safe=false;throw std::invalid_argument("stage run error storage overlaps output");
        }
        const auto storage=[&](const auto* value,size_t count) {
            using Element=std::remove_cv_t<std::remove_pointer_t<decltype(value)>>;
            boundary::require_buffer(value,count);
            const auto bytes=boundary::product(count,sizeof(Element));
            if(overlaps(value,bytes,error,capacity)) {
                report_safe=false;throw std::invalid_argument("stage run error storage overlaps input or output");
            }
            if(overlaps(value,bytes,output,output_size))
                throw std::invalid_argument("stage run output overlaps input");
        };
        storage(start.saved_v4,1);
        if(start.saved_v4->abi_version!=TPMSHX_STAGE_RUN_ABI_VERSION_V4 || start.saved_v4->struct_size!=sizeof(*start.saved_v4))
            throw std::invalid_argument("saved stage v4 ABI version or struct size is invalid");
        storage(start.saved_v3,1);
        if(start.saved_v3->abi_version!=3 || start.saved_v3->struct_size!=sizeof(*start.saved_v3))
            throw std::invalid_argument("saved stage v3 ABI version or struct size is invalid");
        const tpmshx_stage_run_request_2d_v2* request_v2=nullptr;
        const tpmshx_stage_run_request_2d_v1* request=nullptr;
        if(start.request) {
            storage(start.request,1);
            if(start.request->abi_version!=TPMSHX_STAGE_RUN_ABI_VERSION_V3
                || start.request->struct_size!=sizeof(*start.request))
                throw std::invalid_argument("stage run request v3 ABI version or struct size is invalid");
            request_v2=&start.request->values;
        }
        storage(start.fields,start.count);
        for(size_t i=0;i<start.count;++i) {
            const auto& field=start.fields[i];storage(field.name,1);storage(field.name,std::strlen(field.name)+1);
            if(field.type>TPMSHX_RUN_STATE_UTF8)throw std::invalid_argument("invalid stage run state field type");
            const auto bytes=boundary::product(field.count,field.type<=TPMSHX_RUN_STATE_I64?8:1);
            storage(static_cast<const unsigned char*>(field.data),bytes);
        }
        const tpmshx_preparation_case_2d_v1* prepared=nullptr;
        const tpmshx_preparation_case_2d_v2* uniform=nullptr;
        preparation_storage(storage,prepared,uniform,start.saved,start.saved_v2);
        saved_v3_storage(storage,*start.saved_v3);
        if(request_v2) {
            storage(request_v2,1);
            if(request_v2->abi_version!=TPMSHX_STAGE_RUN_ABI_VERSION_V2 || request_v2->struct_size!=sizeof(*request_v2))
                throw std::invalid_argument("stage run request v2 ABI version or struct size is invalid");
            request=&request_v2->values;
        }
        storage(control,1);
        if(request) {
            storage(request,1);
            if(request->abi_version!=TPMSHX_STAGE_RUN_ABI_VERSION || request->struct_size!=sizeof(*request))
                throw std::invalid_argument("stage run request ABI version or struct size is invalid");
        }
        if(request && request->energy)storage(request->energy,1);
        if(request && request->explicit_energy)storage(request->explicit_energy,1);
        const auto text_storage=[&](const char* value) {
            if(value) {storage(value,1);storage(value,std::strlen(value)+1);}
        };
        text_storage(control->result_id);text_storage(control->table_directory);
        if(request)text_storage(request->convergence_mode);
        if(request_v2)text_storage(request_v2->envelope_mode);
        report_safe=true;

        if(return_handle && *start.output)throw std::invalid_argument("stage run output handle must be null");
        if(!return_handle && (result->abi_version!=TPMSHX_STAGE_RUN_ABI_VERSION || result->struct_size!=sizeof(*result) || result->owner))
            throw std::invalid_argument("stage run output must be an initialized empty owner");
        if(!control->cpu_threads || !control->result_id)
            throw std::invalid_argument("stage run requires a positive CPU limit and result label");
        const tpmshx_stage_run_request_2d_v1 defaults{};
        const auto& selected=request?*request:defaults;
        if(prepared->input.df_mode==1) {
            const auto& settings=start.saved_v4->experiment;
            validate_saved_experiment(settings);
            validate_saved_experiment(settings,prepared);
            if (settings.delta_levelset!=prepared->input.delta_levelset
                    || !same_experimental_reference(settings.cell_length_mm,prepared->cell_length_m)
                    || !same_experimental_reference(settings.wall_thickness_mm,prepared->wall_thickness_m))
                throw std::invalid_argument("saved experimental nominal geometry disagrees with the prepared case");
        }
        Packed2D packed(*prepared,selected,*control,uniform,request_v2?request_v2->envelope_mode:nullptr,
            start.request,start.saved,start.saved_v2,start.saved_v3);
        const auto& h=selected.model_h;
        const auto* model_h=(h.max_iterations || h.temperature_tolerance || h.q_relative_tolerance)?&h:nullptr;
        const auto* energy=model_h || packed.explicit_energy?selected.energy:&packed.energy;
        if(model_h) {
            if(packed.explicit_energy || packed.config.thermal_mode==2)
                throw std::invalid_argument("model-h iteration controls require an integral h(T) route");
            tpmshx_energy_effective_settings_v1 values{};
            const auto& sides=packed.config.sides;
            if(tpmshx_full_enthalpy_defaults_v1(2,packed.energy.algorithm,
                    sides[0].fluid==1 || sides[1].fluid==1,&values))
                throw std::invalid_argument("invalid native full enthalpy defaults request");
            energy=nullptr;
        }
        if(packed.explicit_energy==&packed.partial_energy)energy=nullptr;
        auto owner=std::make_unique<StageRun2D>(prepared,uniform,packed.config,control->result_id,
            start.saved,start.saved_v2,start.saved_v3);
        const auto status=start.restore?tpmshx_full_2d_run_restore_v2(
            packed.shape.data(),packed.arrays.data(),packed.sizes.data(),&packed.config,energy,
            packed.explicit_energy,model_h,control->cpu_threads,&control->callbacks,
            start.fields,start.count,&owner->run,error,capacity):tpmshx_full_2d_run_create_v2(
            packed.shape.data(),packed.arrays.data(),packed.sizes.data(),&packed.config,energy,
            packed.explicit_energy,model_h,control->cpu_threads,&control->callbacks,&owner->run,error,capacity);
        if(status)return status;
        if(return_handle) {
            *start.output=owner.release();return 0;
        }
        const int finish=tpmshx_stage_run_2d_finish_v1(owner.get(),error,capacity);
        if(finish)return finish;
        return tpmshx_stage_run_2d_take_result_v1(owner.get(),result,error,capacity);
    } catch(const tpmshx::preparation::DfExperimentError& failure) {
        if(report_safe)boundary::message(error,capacity,failure.what());
        return failure.velocity_window?8:7;
    } catch(const std::invalid_argument& failure) {
        if(report_safe)boundary::message(error,capacity,failure.what());return 1;
    } catch(const std::bad_alloc&) {
        if(report_safe)boundary::message(error,capacity,"stage run allocation failed");return 5;
    } catch(const std::exception& failure) {
        if(report_safe)boundary::message(error,capacity,failure.what());return 5;
    } catch(...) {
        if(report_safe)boundary::message(error,capacity,"unknown native stage run failure");return 5;
    }
}
}
extern "C" void tpmshx_stage_run_2d_release_v1(tpmshx_stage_run_result_2d_v1* result) {
    if(!result)return;
    tpmshx::stages::release_capture_2d(static_cast<tpmshx::stages::Capture2D*>(result->owner));
    *result={};
}
extern "C" int tpmshx_stage_port_windows_fit_2d_v1(double cross_length,double inlet_center,
    double inlet_width,double outlet_center,double outlet_width) {
    const auto fits=[&](double center,double width) {
        return std::isfinite(center) && std::isfinite(width) && width>0.
            && tpmshx::grid::port_window_within(cross_length,center,width);
    };
    return std::isfinite(cross_length) && cross_length>0.
        && fits(inlet_center,inlet_width) && fits(outlet_center,outlet_width);
}
extern "C" int tpmshx_stage_run_2d_check_experiment_v4(const tpmshx_stage_experiment_2d_v4* settings,
    char* error,size_t capacity) {
    if(!boundary::error_buffer_valid(error,capacity))return 1;
    if(overlaps(settings,sizeof(*settings),error,capacity))return 1;
    try {
        boundary::require_buffer(settings,1);
        validate_saved_experiment(*settings);
        boundary::message(error,capacity,"");return 0;
    } catch(const tpmshx::preparation::DfExperimentError& failure) {
        boundary::message(error,capacity,failure.what());return failure.velocity_window?8:7;
    } catch(const std::invalid_argument& failure) {
        boundary::message(error,capacity,failure.what());return 1;
    } catch(const std::exception& failure) {
        boundary::message(error,capacity,failure.what());return 5;
    } catch(...) {
        boundary::message(error,capacity,"unknown native experiment check failure");return 5;
    }
}
namespace {
StartRun saved_start(const tpmshx_stage_saved_case_2d_v4* saved,const tpmshx_stage_run_request_2d_v3* request,
    void** handle,const tpmshx_run_state_field_v1* fields=nullptr,size_t count=0,bool restore=false) {
    const auto* previous=saved?&saved->values:nullptr;
    return {request,handle,fields,count,restore,previous?&previous->values.values:nullptr,
        previous?&previous->values:nullptr,previous,saved};
}
}
extern "C" int tpmshx_run_saved_case_2d_v4(const tpmshx_stage_saved_case_2d_v4* saved,
    const tpmshx_stage_run_request_2d_v3* request,const tpmshx_stage_run_control_v1* control,
    tpmshx_stage_run_result_2d_v1* result,char* error,size_t capacity) {
    const auto start=saved_start(saved,request,nullptr);
    return run(control,result,error,capacity,start);
}
extern "C" int tpmshx_stage_run_2d_create_saved_v4(const tpmshx_stage_saved_case_2d_v4* saved,
    const tpmshx_stage_run_request_2d_v3* request,const tpmshx_stage_run_control_v1* control,
    void** output,char* error,size_t capacity) {
    const auto start=saved_start(saved,request,output);
    return run(control,nullptr,error,capacity,start);
}
extern "C" int tpmshx_stage_run_2d_restore_saved_v4(const tpmshx_stage_saved_case_2d_v4* saved,
    const tpmshx_stage_run_request_2d_v3* request,const tpmshx_stage_run_control_v1* control,
    const tpmshx_run_state_field_v1* fields,size_t count,void** output,char* error,size_t capacity) {
    const auto start=saved_start(saved,request,output,fields,count,true);
    return run(control,nullptr,error,capacity,start);
}
extern "C" int tpmshx_stage_run_2d_advance_step_v1(void* run,uint32_t* phase,char* error,size_t capacity) {
    return tpmshx_full_2d_run_advance_step_v1(run?static_cast<StageRun2D*>(run)->run:nullptr,phase,error,capacity);
}
extern "C" int tpmshx_stage_run_2d_finish_v1(void* run,char* error,size_t capacity) {
    if(!boundary::error_buffer_valid(error,capacity))return 1;
    auto* owner=static_cast<StageRun2D*>(run);
    if(!owner || overlaps(owner,sizeof(*owner),error,capacity))return 1;
    try {
        const auto storage=[&](const auto* value,size_t count) {
            using Element=std::remove_cv_t<std::remove_pointer_t<decltype(value)>>;
            boundary::require_buffer(value,count);
            if(overlaps(value,boundary::product(count,sizeof(Element)),error,capacity))
                throw std::invalid_argument("stage error storage overlaps preparation");
        };
        if(owner->prepared) {
            preparation_storage(storage,owner->prepared,owner->uniform,owner->saved,owner->saved_v2);
            saved_v3_storage(storage,*owner->saved_v3);
        }
    } catch(...) {return 1;}
    uint32_t phase=0;
    int status=tpmshx_full_2d_run_phase_v1(owner->run,&phase);
    while(!status && phase!=TPMSHX_FULL2D_COMPLETED && phase!=TPMSHX_FULL2D_CANCELLED)
        status=tpmshx_full_2d_run_advance_step_v1(owner->run,&phase,error,capacity);
    if(!status)boundary::message(error,capacity,"");
    return status;
}
extern "C" int tpmshx_stage_run_2d_phase_v1(const void* run,uint32_t* phase) {
    return tpmshx_full_2d_run_phase_v1(run?static_cast<const StageRun2D*>(run)->run:nullptr,phase);
}
extern "C" int tpmshx_stage_run_2d_snapshot_v1(const void* run,tpmshx_run_state_v1* state,char* error,size_t capacity) {
    return tpmshx_full_2d_run_snapshot_v1(run?static_cast<const StageRun2D*>(run)->run:nullptr,state,error,capacity);
}
extern "C" int tpmshx_stage_run_2d_take_result_v1(void* run,
    tpmshx_stage_run_result_2d_v1* result,char* error,size_t capacity) {
    if(!boundary::error_buffer_valid(error,capacity))return 1;
    tpmshx_full_2d_result_v2 raw{};
    bool report_safe=false;
    try {
        boundary::require_buffer(result,1);boundary::require_buffer(static_cast<StageRun2D*>(run),1);
        if(overlaps(result,sizeof(*result),error,capacity) || overlaps(run,sizeof(StageRun2D),error,capacity)
            || overlaps(run,sizeof(StageRun2D),result,sizeof(*result)))return 1;
        auto& owner=*static_cast<StageRun2D*>(run);
        uint32_t phase=0;
        const auto phase_status=tpmshx_full_2d_run_phase_v1(owner.run,&phase);
        if(phase_status)return phase_status;
        if(owner.prepared) {
            const auto storage=[&](const auto* value,size_t count) {
                using Element=std::remove_cv_t<std::remove_pointer_t<decltype(value)>>;
                boundary::require_buffer(value,count);
                const auto bytes=boundary::product(count,sizeof(Element));
                if(overlaps(value,bytes,error,capacity) || overlaps(value,bytes,result,sizeof(*result)))
                    throw std::invalid_argument("stage result storage overlaps preparation");
            };
            preparation_storage(storage,owner.prepared,owner.uniform,owner.saved,owner.saved_v2);
            saved_v3_storage(storage,*owner.saved_v3);
        }
        report_safe=true;
        if(result->abi_version!=TPMSHX_STAGE_RUN_ABI_VERSION || result->struct_size!=sizeof(*result) || result->owner)
            throw std::invalid_argument("stage run output must be an initialized empty owner");
        if(phase==TPMSHX_FULL2D_CANCELLED) {
            boundary::message(error,capacity,"compute cancelled by user");return 6;
        }
        const auto status=tpmshx_full_2d_run_take_result_v1(owner.run,&raw,error,capacity);
        if(status)return status;
        std::unique_ptr<tpmshx::stages::Capture2D,decltype(&tpmshx::stages::release_capture_2d)> captured(
            tpmshx::stages::capture_2d(*owner.prepared,raw,owner.config,owner.result_id.c_str(),owner.uniform,
                owner.saved->inlet_recorded,owner.saved->range_captured),
            &tpmshx::stages::release_capture_2d);
        *result=tpmshx::stages::stage_view(*captured.release());
        owner.prepared=nullptr;owner.uniform=nullptr;owner.saved=nullptr;owner.saved_v2=nullptr;owner.saved_v3=nullptr;
        boundary::message(error,capacity,"");return 0;
    } catch(const std::invalid_argument& failure) {
        tpmshx_full_2d_release_v2(&raw);if(report_safe)boundary::message(error,capacity,failure.what());return 1;
    } catch(const std::exception& failure) {
        tpmshx_full_2d_release_v2(&raw);if(report_safe)boundary::message(error,capacity,failure.what());return 5;
    } catch(...) {
        tpmshx_full_2d_release_v2(&raw);if(report_safe)boundary::message(error,capacity,"unknown native stage capture failure");return 5;
    }
}
extern "C" void tpmshx_stage_run_2d_release_run_v1(void** run) {
    if(run) {delete static_cast<StageRun2D*>(*run);*run=nullptr;}
}
