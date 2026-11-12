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
        values.sides[0].velocity_m_s=6.;values.sides[0].temperature_K=350.;values.sides[0].pressure_Pa=200000.;
        values.sides[1].fluid=1;values.sides[1].velocity_m_s=.02;
        values.sides[1].temperature_K=320.;values.sides[1].pressure_Pa=200000.;
        values.sides[1].port.direction=3;
        PreparationOptions options;options.allow_extrapolation=1;
        RunControl control;control.result_id="native-resumed-2d";control.cpu_threads=2;
        tpmshx_stage_application_2d_v1 application{};
        auto result=[&] {
            auto prepared=prepare_case(input,options);
            const auto& initial=prepared.view().values;
            for(size_t side=0;side<2;++side) {
                application.area_density_per_m[side]=initial.area_density_per_m;
                application.surface_htc_W_m2K[side]=initial.sides[side].properties.surface_transfer_W_m2K;
            }
            auto state=[&] {
                Run2D run(prepared,control);
                while(run.phase()!=TPMSHX_FULL2D_FLOW)run.advance_step();
                return run.snapshot();
            }();
            control.cpu_threads=1;
            Run2D restored(prepared,control,{},&state);
            while(restored.phase()!=TPMSHX_FULL2D_COMPLETED)restored.advance_step();
            return restored.take_result();
        }();
        const auto summary=capture_summary(result,application);
        if(!summary.model_h_available[0] || !summary.model_h_available[1]
            || summary.model_h_area_m2[0]<=0. || summary.application_hv[0]<=0.)
            throw std::runtime_error("native 2D capture summary is incomplete");
        auto performance=evaluate(result);
        std::cout<<performance.view().json<<'\n';
        return result.view().raw.converged?0:2;
    } catch(const std::exception& error) {
        std::cerr<<error.what()<<'\n';return 1;
    }
}
