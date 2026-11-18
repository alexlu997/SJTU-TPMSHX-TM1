#include <tpmshx/stages.hpp>
#include <cmath>
#include <iostream>

int main() {
    try {
        tpmshx::stages::CaseInput2Dv2 input;
        auto& values=input.values;
        values.length_m=.182;values.height_m=.042;
        values.requested_nx=6;values.requested_ny=8;
        values.topology=1;values.cell_length_mm=7.;values.wall_thickness_mm=.6;
        values.solid_conductivity_W_mK=16.;
        values.sides[0].fluid=3;values.sides[0].velocity_m_s=.15;
        values.sides[0].temperature_K=400.;values.sides[0].pressure_Pa=8e6;
        values.sides[1].fluid=1;values.sides[1].velocity_m_s=.02;
        values.sides[1].temperature_K=320.;values.sides[1].pressure_Pa=200000.;
        values.sides[1].port.direction=1;
        tpmshx::stages::PreparationOptions options;options.allow_extrapolation=1;
        auto prepared=tpmshx::stages::prepare_case(input,options);
        const auto& state=prepared.view();
        if (!state.co2.active || !state.co2.sides[0] || state.co2.sides[1]
            || state.values.input.sides[1].fluid!=1
            || state.values.cell_length.size!=state.values.nx*state.values.ny
            || !std::isfinite(state.values.sides[0].properties.nu)
            || state.values.sides[1].drag_evidence.scale_forchheimer!=1.) return 1;
        std::cout<<"Prepared CO2/water: "<<state.values.nx<<" x "<<state.values.ny<<" cells\n";
        tpmshx::stages::InletPropertyQuery query;
        query.inlet.geometry.topology=values.topology;
        query.inlet.geometry.cell_length_mm=values.cell_length_mm;
        query.inlet.geometry.wall_thickness_mm=values.wall_thickness_mm;
        query.hydraulic_diameter_m=state.values.hydraulic_diameter_m;
        query.epsilon_a=state.values.epsilon_a;
        const char* fluids[]={"air","water","sco2","co2"};
        const double temperatures[]={380.,320.,480.,300.};
        const double pressures[]={160000.,200000.,9000000.,4500000.};
        query.inlet.velocity_m_s=6.;
        for (std::uint32_t fluid=0;fluid<4;++fluid) {
            query.inlet.fluid=fluid;query.inlet.temperature_K=temperatures[fluid];
            query.inlet.pressure_Pa=pressures[fluid];query.exact_co2_drag=fluid==3;
            const auto properties=tpmshx::stages::query_inlet_properties(query);
            for (const auto& scalar:properties.values)
                if (!std::isfinite(scalar.real) || scalar.imaginary!=0. || scalar.category!=0) return 1;
            if (properties.values[0].real<=0. || properties.values[7].real<=0.) return 1;
            std::cout<<"Queried "<<fluids[fluid]<<": rho="<<properties.values[0].real<<" kg/m3\n";
        }
        return 0;
    } catch (const std::exception& error) {
        std::cerr<<error.what()<<'\n';return 1;
    }
}
