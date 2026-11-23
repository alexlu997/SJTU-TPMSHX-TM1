#include <tpmshx/stages.hpp>
#include <iostream>

int main() {
    using namespace tpmshx::stages;
    try {
        QuickDesignInputV2 input;
        // Cell, wall, span, length, height, k_s, tolerance, mass A/B, temperature A/B, pressure A/B.
        const double values[]{7.,.5,.084,.05,.07,16.,1e-5,.2855,.5,688.23,320.,1088700.,200000.};
        for(std::size_t n=0;n<TPMSHX_QUICK_VALUE_COUNT;++n)input.values[n].value=values[n];
        input.topology={"Diamond",7};input.arrangement={"cross",5};input.property_mode={"const",5};
        input.fluids[0]={"air",3};input.fluids[1]={"water",5};input.have_height=1;
        auto prepared=prepare_quick_design(input);
        tpmshx_quick_run_control_v1 control{};control.result_id="quick-design-example";
        auto result=run_case(input,prepared,control);
        auto performance=evaluate(result);
        std::cout<<performance.view().json<<'\n';
        return result.view().raw.stop==TPMSHX_CONVERGED?0:2;
    } catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}
}
