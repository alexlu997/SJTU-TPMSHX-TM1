#include <tpmshx/stages.hpp>
#include <iostream>

int main() {
    using namespace tpmshx::stages;
    try {
        ContinuousInput2D input;
        auto& flow=input.values;
        auto& values=flow.values.values;
        values.length_m=.182;values.height_m=.042;values.physical_depth_m=.042;
        values.have_physical_depth=1;values.requested_nx=6;values.requested_ny=8;
        values.topology=1;values.cell_length_mm=7.;values.wall_thickness_mm=.6;
        values.solid_conductivity_W_mK=16.;
        values.sides[0].fluid=0;values.sides[0].temperature_K=350.;values.sides[0].pressure_Pa=200000.;
        values.sides[1].fluid=1;values.sides[1].temperature_K=320.;values.sides[1].pressure_Pa=200000.;
        values.sides[1].port.direction=3;
        const double decisions[]{4.5,6.,7.5,5.4,.31,.42,.59,.36};
        input.controls={2,2,1,0,{4.,8.},{.3,.6},{decisions,8}};
        auto capacities=prepare_inlet_mass_capacities(input);
        flow.have_explicit_targets=1;
        flow.explicit_targets_kg_s[0]=capacities.view().flow.capacities[0].value*6.;
        flow.explicit_targets_kg_s[1]=capacities.view().flow.capacities[1].value*.02;
        PreparationOptions options;options.allow_extrapolation=1;
        RunControl control;control.result_id="native-continuous-2d";control.cpu_threads=2;
        auto result=[&] {auto prepared=prepare_case(input,options);return run_case(prepared,control);}();
        auto performance=evaluate(result);
        std::cout<<performance.view().json<<'\n';
        return result.view().raw.converged?0:2;
    } catch(const std::exception& error) {
        std::cerr<<error.what()<<'\n';return 1;
    }
}
