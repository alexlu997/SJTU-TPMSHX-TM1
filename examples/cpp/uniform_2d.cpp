#include <tpmshx/stages.hpp>
#include <iostream>

int main() {
    using namespace tpmshx::stages;
    try {
        CaseInput2Dv2 input;
        auto& values=input.values;
        values.length_m=.182;values.height_m=.042;values.requested_nx=6;values.requested_ny=8;
        values.topology=1;values.cell_length_mm=7.;values.wall_thickness_mm=.6;
        values.solid_conductivity_W_mK=16.;
        values.sides[0].fluid=3;values.sides[0].velocity_m_s=.7;
        values.sides[0].temperature_K=340.;values.sides[0].pressure_Pa=9e6;
        values.sides[1].fluid=1;values.sides[1].velocity_m_s=.2;
        values.sides[1].temperature_K=325.;values.sides[1].pressure_Pa=2e5;
        values.sides[1].port.direction=3;
        RunControl control;control.result_id="native-uniform-2d";control.cpu_threads=2;
        auto result=[&] {auto prepared=prepare_case(input);return run_case(prepared,control);}();
        auto performance=evaluate(result);
        std::cout<<performance.view().json<<'\n';
        return result.view().raw.converged?0:2;
    } catch(const std::exception& error) {
        std::cerr<<error.what()<<'\n';return 1;
    }
}
