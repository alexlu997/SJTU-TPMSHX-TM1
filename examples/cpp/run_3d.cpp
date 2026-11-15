#include <tpmshx/stages.hpp>
#include <iostream>

int main() {
    using namespace tpmshx::stages;
    try {
        CaseInput3D input;
        input.lengths_m[0].value=.182;input.lengths_m[1].value=.042;input.lengths_m[2].value=.031;
        input.counts[0]=6;input.counts[1]=5;input.counts[2]=4;
        input.topology=1;input.cell_length_mm=7.;input.wall_thickness_mm=.6;input.solid_conductivity_W_mK=16.;
        input.sides[0].velocity_m_s=6.;input.sides[0].temperature_K=350.;input.sides[0].pressure_Pa=200000.;
        input.sides[1].fluid=1;input.sides[1].velocity_m_s=.02;
        input.sides[1].temperature_K=320.;input.sides[1].pressure_Pa=200000.;input.sides[1].port.direction=3;
        PreparationOptions options;options.allow_extrapolation=1;
        RunRequest3D request;request.max_iter_simple={1,12};request.max_outer_ltne={1,2};
        request.model_h={9,.5,1e-3};
        RunControl3D control;control.cpu_threads=2;control.result_id="native-3d-example";
        auto result=[&] {
            auto prepared=prepare_case(input,options);
            Run3D run(prepared,control,request);
            run.advance_step();
            auto state=run.snapshot();
            control.cpu_threads=1;
            Run3D resumed(prepared,control,request,&state);
            while(resumed.phase()!=TPMSHX_FULL3D_COMPLETED)resumed.advance_step();
            return resumed.take_result();
        }();
        auto report=evaluate(result);
        std::cout<<report.view().json<<'\n';
        // This small iteration budget can give an ineligible result.
        return result.view().raw.stop>1 || result.view().evidence.dimension!=3;
    } catch(const std::exception& error) {
        std::cerr<<error.what()<<'\n';return 1;
    }
}
