#include <tpmshx/stages.hpp>
#include <iostream>
#include <string>

int main() {
    using namespace tpmshx::stages;
    try {
        QuickDesignInputV2 input;
        const double values[]{7.,.5,.084,.025,.07,16.,1e-5,.03,.02,480.,320.,9e6,9e6};
        for(std::size_t n=0;n<TPMSHX_QUICK_VALUE_COUNT;++n)input.values[n].value=values[n];
        input.topology={"Diamond",7};input.arrangement={"counter",7};input.property_mode={"const",5};
        input.fluids[0]={"air",3};input.fluids[1]={"air",3};input.have_height=1;
        const auto pressure=pressure_fractions(input);
        auto prepared=prepare_quick_design(input);
        const auto& state=prepared.view();
        if(state.shape[0]!=60 || state.shape[1]!=1 || state.shape[2]!=2 ||
           state.controls.have_q_relative_tolerance || state.controls.have_chunk_iterations)
            throw std::runtime_error("stored Quick counter controls changed");
        for(std::size_t side=0;side<2;++side)if(pressure.fractions[side].value!=state.fractions[side].value)
            throw std::runtime_error("independent pressure query differs from full preparation");
        std::cout<<"Quick typed preparation: "<<state.epsilon.size<<" cells; pressure fractions "
                 <<pressure.fractions[0].value<<", "<<pressure.fractions[1].value<<'\n';
        return 0;
    } catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}
}
