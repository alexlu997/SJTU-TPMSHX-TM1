#include "tpmshx/conservative_energy.hpp"
#include "tpmshx/model_h_2d.hpp"
#include "tpmshx/model_h_3d.hpp"
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <stdexcept>
#include <type_traits>

namespace {
using namespace tpmshx;
using Vector=std::vector<double>;
template<class T> ArrayView<const double> view(const T& values) { return {values.data(),values.size()}; }
void require(bool value,const char* message) { if(!value)throw std::runtime_error(message); }
bool equal(double a,double b) { return a==b || (std::isnan(a) && std::isnan(b)); }
template<class Error,class Action> void rejects(Action action) {
    bool rejected=false;
    try { action(); } catch(const Error&) { rejected=true; }
    require(rejected,"invalid run operation was accepted");
}
struct Callbacks {
    std::size_t calls=0,cancel_at=0;
    std::vector<std::size_t> progress;
};
bool cancel(void* context) {
    auto& state=*static_cast<Callbacks*>(context);
    ++state.calls;return state.cancel_at && state.calls>=state.cancel_at;
}
void progress(void* context,std::size_t done,std::size_t) {
    static_cast<Callbacks*>(context)->progress.push_back(done);
}

template<int dimension> struct Fixture {
    using Run=std::conditional_t<dimension==2,ModelHRun2D,ModelHRun3D>;
    using State=std::conditional_t<dimension==2,ModelHRunState2D,ModelHRunState3D>;
    using Result=std::conditional_t<dimension==2,ModelHResult2D,ModelHResult3D>;
    using Control=std::conditional_t<dimension==2,ModelHControl2D,ModelHControl3D>;
    using FluidType=std::conditional_t<dimension==2,ModelHFluid2D,ModelHFluid3D>;
    static constexpr std::size_t nz=dimension==2?1:2,n=6*nz;
    Vector dx{.1,.15,.2},dy{.08,.13},dz=Vector(nz,dimension==2?1.:.2);
    Vector k=Vector(n,.04),hv=Vector(n,30.),ks=Vector(n,.2),source=Vector(n,0.);
    Vector ax=Vector(8*nz,.02),ay=Vector(9*nz),az=Vector(6*(nz+1));
    Vector bx=Vector(8*nz),by=Vector(9*nz,.03),bz=Vector(6*(nz+1));
    std::array<Vector,3> temperature{Vector(n),Vector(n),Vector(n)};
    GridView grid{3,2,nz,view(dx),view(dy),view(dz)};
    Callbacks callbacks;
    Control control{};
    PhysicalHeatLedger ledger;
    bool prescribed=false;
    Vector fixed_b=Vector(n,360.);

    Fixture(bool accelerate,bool strict,bool red_black,bool warm,std::size_t budget,bool fixed=false,bool sources=false)
        :prescribed(fixed) {
        control.max_iterations=budget;control.chunk_iterations=77;
        control.q_relative_tolerance=0.;control.temperature_tolerance=.01;
        control.accelerate=accelerate;control.strict_energy_balance=strict;
        control.red_black=red_black;control.warm_start=warm;
        control.cancel=cancel;control.progress=progress;control.context=&callbacks;
        if constexpr(dimension==3) {
            control.alpha_a=.2;control.alpha_solid=1.;control.alpha_b=.2;
        }
        for(std::size_t i=0;i<n;++i) {
            temperature[0][i]=310.+static_cast<double>(i)/20.;
            temperature[1][i]=350.-static_cast<double>(i)/30.;
            temperature[2][i]=330.;
            if(sources)source[i]=2.;
        }
    }
    TemperatureStateView fields() {
        return {{temperature[0].data(),n},{temperature[1].data(),n},{temperature[2].data(),n}};
    }
    FluidType a() {
        if constexpr(dimension==2)return {Fluid::air,view(k),view(hv),view(ax),view(ay),{0,300.,{},{},{}}};
        else return {Fluid::air,view(k),view(hv),view(ax),view(ay),view(az),{0,300.,{},{},{}},view(source)};
    }
    FluidType b() {
        if constexpr(dimension==2)return {Fluid::water,view(k),view(hv),view(bx),view(by),{2,370.,{},{},{}}};
        else return {Fluid::water,view(k),view(hv),view(bx),view(by),view(bz),{2,370.,{},{},{}},{}};
    }
    ArrayView<const double> fixed() { return prescribed?view(fixed_b):ArrayView<const double>{}; }
    std::unique_ptr<Run> start() {
        if constexpr(dimension==2)return std::make_unique<Run>(grid,a(),b(),view(ks),fields(),control,fixed(),&ledger);
        else return std::make_unique<Run>(grid,a(),b(),view(ks),view(source),fields(),control,fixed(),&ledger);
    }
    std::unique_ptr<Run> restore(const State& state) {
        if constexpr(dimension==2)return std::make_unique<Run>(grid,a(),b(),view(ks),fields(),control,state,fixed(),&ledger);
        else return std::make_unique<Run>(grid,a(),b(),view(ks),view(source),fields(),control,state,fixed(),&ledger);
    }
    Result solve() {
        if constexpr(dimension==2)return solve_model_h_2d(grid,a(),b(),view(ks),fields(),control,fixed(),&ledger);
        else return solve_model_h_3d(grid,a(),b(),view(ks),view(source),fields(),control,fixed(),&ledger);
    }
};

template<class Result> void compare(const Result& actual,const Result& expected) {
    require(actual.stop==expected.stop && actual.iterations==expected.iterations
        && equal(actual.residual,expected.residual) && equal(actual.q_b,expected.q_b)
        && actual.audit_available==expected.audit_available
        && actual.physical_audit_available==expected.physical_audit_available
        && equal(actual.energy_error_ratio,expected.energy_error_ratio)
        && actual.finishing_checks.size()==expected.finishing_checks.size(),"resumed result differs");
    require(actual.audit.solid_residual==expected.audit.solid_residual,"resumed solid audit differs");
    for(std::size_t side=0;side<2;++side) {
        const auto& a=actual.audit.sides[side];const auto& b=expected.audit.sides[side];
        require(a.residual==b.residual && equal(a.residual_sum,b.residual_sum)
            && equal(a.residual_max,b.residual_max),"resumed fluid audit differs");
        if constexpr(std::is_same_v<Result,ModelHResult2D>) {
            require(a.h_faces==b.h_faces && a.boundary_mass_out==b.boundary_mass_out
                && a.boundary_h_out==b.boundary_h_out && a.linearization_defect==b.linearization_defect,
                "resumed 2D face audit differs");
        } else {
            for(std::size_t face=0;face<6;++face)
                require(a.boundaries[face].enthalpy_faces==b.boundaries[face].enthalpy_faces,
                    "resumed 3D face audit differs");
        }
    }
    for(std::size_t i=0;i<actual.finishing_checks.size();++i) {
        const auto& a=actual.finishing_checks[i];const auto& b=expected.finishing_checks[i];
        require(a.iterations==b.iterations && equal(a.energy_error_ratio,b.energy_error_ratio),
            "resumed finishing history differs");
        if constexpr(std::is_same_v<Result,ModelHResult2D>)
            require(a.passed==b.passed && a.equations_ok==b.equations_ok,"resumed 2D finishing gates differ");
        else require(a.gates==b.gates && a.physical_passed==b.physical_passed,"resumed 3D finishing gates differ");
    }
    if constexpr(std::is_same_v<Result,ModelHResult2D>)
        require(actual.last_a==expected.last_a && actual.last_b==expected.last_b,"resumed linearization differs");
    else require(actual.has_sources==expected.has_sources,"resumed source state differs");
}

template<int dimension> void continuation() {
    for(bool accelerate:{false,true})for(bool strict:{false,true})for(bool red_black:{false,true})
    for(bool warm:{false,true})for(std::size_t budget:{0U,51U,130U,265U}) {
        Fixture<dimension> expected(accelerate,strict,red_black,warm,budget);
        const auto reference=expected.solve();
        for(std::size_t cut=0;cut<(dimension==3 && strict && accelerate?20U:8U);++cut) {
            Fixture<dimension> actual(accelerate,strict,red_black,warm,budget);
            auto owner=actual.start();
            rejects<std::logic_error>([&]{owner->take_result();});
            for(std::size_t i=0;i<cut && owner->phase()==ModelHPhase::active;++i)owner->advance();
            if(owner->phase()==ModelHPhase::active) {
                auto state=owner->snapshot();
                if(state.iteration.chunk) {
                    const auto& chunk=*state.iteration.chunk;
                    require(chunk.sweep_block==(dimension==3 && strict?5U:25U)
                        && chunk.acceleration.history_limit==(dimension==3 && strict?12U:6U),
                        "thermal owner used the wrong acceleration policy");
                }
                state.iteration.temperature[0][0]+=1.;
                require(state.iteration.temperature!=owner->snapshot().iteration.temperature,"snapshot aliases live temperatures");
                state=owner->snapshot();owner.reset();
                for(auto& field:actual.temperature)std::fill(field.begin(),field.end(),-1.);
                owner=actual.restore(state);
                state.iteration.previous[0]+=1.;
                require(state.iteration.previous!=owner->snapshot().iteration.previous,"restore borrows its saved fields");
            }
            while(owner->phase()==ModelHPhase::active)owner->advance();
            require(actual.temperature==expected.temperature,"resumed temperature sequence differs");
            require(actual.callbacks.calls==expected.callbacks.calls
                && actual.callbacks.progress==expected.callbacks.progress,"resumed callback sequence differs");
            require(actual.ledger.residual==expected.ledger.residual,"resumed physical ledger differs");
            compare(owner->take_result(),reference);
            rejects<std::logic_error>([&]{owner->snapshot();});
            rejects<std::logic_error>([&]{owner->take_result();});
            owner->advance();
        }
    }
    for(bool prescribed:{false,true}) {
        Fixture<dimension> expected(true,prescribed,false,true,1000,prescribed,!prescribed);
        expected.control.q_relative_tolerance=1.;expected.control.temperature_tolerance=100.;
        const auto reference=expected.solve();
        Fixture<dimension> actual(true,prescribed,false,true,1000,prescribed,!prescribed);
        actual.control.q_relative_tolerance=1.;actual.control.temperature_tolerance=100.;
        auto owner=actual.start();
        while(owner->phase()==ModelHPhase::active) {
            owner->advance();
            if(owner->phase()==ModelHPhase::active) { const auto saved=owner->snapshot();owner.reset();owner=actual.restore(saved); }
        }
        compare(owner->take_result(),reference);
        require(actual.temperature==expected.temperature,"source or prescribed continuation differs");
    }
}

template<int dimension> void invalid_states() {
    Fixture<dimension> fixture(true,false,false,true,265);
    auto owner=fixture.start();owner->advance();
    const auto saved=owner->snapshot();
    require(saved.iteration.chunk.has_value(),"fixture missed an inner thermal boundary");
    for(int damage=0;damage<13;++damage) {
        auto state=saved;
        switch(damage) {
        case 0:state.iteration.temperature[0].pop_back();break;
        case 1:state.iteration.temperature[2][0]=std::numeric_limits<double>::infinity();break;
        case 2:state.iteration.previous.pop_back();break;
        case 3:state.iteration.previous_q=std::numeric_limits<double>::quiet_NaN();break;
        case 4:state.iteration.have_q=true;break;
        case 5:state.result.iterations=265;break;
        case 6:state.result.stop=TemperatureStop::converged;break;
        case 7:state.result.residual=-1.;break;
        case 8:state.iteration.chunk->completed=0;break;
        case 9:state.iteration.chunk->acceleration.r[0][0]=std::numeric_limits<double>::infinity();break;
        case 10:++state.iteration.chunk->count;break;
        case 11:
            if constexpr(dimension==2)state.result.last_a.pop_back();
            else state.carry[2].pop_back();
            break;
        case 12:state.iteration.chunk->sweep_block=5;break;
        }
        const auto original=fixture.temperature;
        rejects<std::invalid_argument>([&]{fixture.restore(state);});
        require(original==fixture.temperature,"invalid state changed destination fields");
    }
    for(std::size_t cancel_at:{1U,4U,8U,17U}) {
        Fixture<dimension> actual(true,false,false,true,265),expected(true,false,false,true,265);
        actual.callbacks.cancel_at=cancel_at;expected.callbacks.cancel_at=cancel_at;
        const auto reference=expected.solve();
        auto active=actual.start();
        while(active->phase()==ModelHPhase::active) {
            active->advance();
            if(active->phase()==ModelHPhase::active) { const auto state=active->snapshot();active.reset();active=actual.restore(state); }
        }
        require(active->phase()==ModelHPhase::cancelled,"cancelled run remained active");
        compare(active->take_result(),reference);
        require(actual.temperature==expected.temperature && actual.callbacks.calls==expected.callbacks.calls,
            "resume changed cancellation timing");
        rejects<std::logic_error>([&]{active->snapshot();});
    }
    Fixture<dimension> observed(true,false,false,true,130);
    struct Observer { typename Fixture<dimension>::Run* run=nullptr;std::size_t calls=0; } observer;
    observed.control.cancel=nullptr;observed.control.context=&observer;
    observed.control.progress=[](void* context,std::size_t,std::size_t) {
        auto& observation=*static_cast<Observer*>(context);++observation.calls;
        rejects<std::logic_error>([&]{observation.run->snapshot();});
        rejects<std::logic_error>([&]{observation.run->advance();});
    };
    auto observed_run=observed.start();observer.run=observed_run.get();
    while(observed_run->phase()==ModelHPhase::active)observed_run->advance();
    require(observer.calls==2,"progress callback missed the in-progress state check");
    Fixture<dimension> failing(true,false,false,true,265);
    std::fill(failing.ks.begin(),failing.ks.end(),0.);std::fill(failing.hv.begin(),failing.hv.end(),0.);
    auto broken=failing.start();
    rejects<std::domain_error>([&]{broken->advance();});
    require(broken->phase()==ModelHPhase::failed,"partial failure remained active");
    rejects<std::logic_error>([&]{broken->snapshot();});
    rejects<std::logic_error>([&]{broken->advance();});
}
}

int main() {
    continuation<2>();continuation<3>();invalid_states<2>();invalid_states<3>();
    std::puts("model-h runs: exact continuation, original callbacks, state validation and failure boundaries passed");
}
