#include <tpmshx/stages.hpp>
#include <iostream>

int main() {
    using namespace tpmshx::stages;
    try {
        CaseInput2D input;
        input.length_m=.182;input.height_m=.042;input.requested_nx=6;input.requested_ny=8;
        input.topology=1;input.cell_length_mm=7.;input.wall_thickness_mm=.6;
        input.solid_conductivity_W_mK=16.;
        input.sides[0].fluid=3;input.sides[0].velocity_m_s=.7;
        input.sides[0].temperature_K=340.;input.sides[0].pressure_Pa=9e6;
        input.sides[1].fluid=1;input.sides[1].velocity_m_s=.2;
        input.sides[1].temperature_K=325.;input.sides[1].pressure_Pa=2e5;
        input.sides[1].port.direction=3;
        RunControl control;control.result_id="native-uniform-2d";control.cpu_threads=2;
        auto result=[&] {auto prepared=prepare_case(input);return run_case(prepared,control);}();
        auto performance=evaluate(result);
        std::cout<<performance.view().json<<'\n';
        return result.view().raw.converged?0:2;
    } catch(const std::exception& error) {
        std::cerr<<error.what()<<'\n';return 1;
    }
}
