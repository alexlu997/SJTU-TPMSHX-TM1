#include <tpmshx/stages.hpp>
#include <iostream>

int main() {
    using namespace tpmshx::stages;
    try {
        CaseInput2D input;
        input.length_m=.182;input.height_m=.042;input.requested_nx=20;input.requested_ny=40;
        input.topology=1;input.cell_length_mm=7.;input.wall_thickness_mm=.4;
        input.solid_conductivity_W_mK=16.;
        input.sides[0].velocity_m_s=10.;input.sides[0].temperature_K=600.;input.sides[0].pressure_Pa=101325.;
        input.sides[1].velocity_m_s=10.;input.sides[1].temperature_K=300.;input.sides[1].pressure_Pa=101325.;
        input.sides[1].port.direction=3;
        RunControl control;control.result_id="native-air-2d";control.cpu_threads=2;
        auto prepared=prepare_case(input);
        auto result=run_case(prepared,control);
        auto performance=evaluate(result);
        std::cout<<performance.view().json<<'\n';
        return result.view().raw.converged?0:2;
    } catch(const std::exception& error) {
        std::cerr<<error.what()<<'\n';return 1;
    }
}
