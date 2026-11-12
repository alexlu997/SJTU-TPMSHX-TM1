#include <tpmshx/stages.hpp>
#include <iostream>

int main() {
    using namespace tpmshx::stages;
    try {
        QuickDesignInput input;
        input.topology=TPMSHX_DIAMOND;input.arrangement=TPMSHX_CROSS;input.property_mode=TPMSHX_CONSTANT;
        input.cell_length_mm=7.;input.wall_thickness_mm=.5;input.span_m=.084;input.length_m=.05;
        input.have_height=1;input.height_m=.07;
        input.sides[0]={TPMSHX_AIR,688.23,1088700.,.2855};
        input.sides[1]={TPMSHX_WATER,320.,200000.,.5};
        auto prepared=prepare_quick_design(input);
        tpmshx_quick_run_control_v1 control{};control.result_id="quick-design-example";
        auto result=run_case(prepared,control);
        auto performance=evaluate(result);
        std::cout<<performance.view().json<<'\n';
        return result.view().raw.stop==TPMSHX_CONVERGED?0:2;
    } catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}
}
