#include "tpmshx/enthalpy_driver.hpp"

#include <Exceptions.h>
#include <CoolProp/AbstractState.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <iostream>
#include <limits>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using namespace tpmshx;
using Values = std::vector<double>;
ArrayView<const double> view(const Values& v) { return {v.data(),v.size()}; }
ArrayView<double> output(Values& v) { return {v.data(),v.size()}; }
void require(bool condition,const char* message) { if (!condition) throw std::runtime_error(message); }

struct Case {
    std::size_t axis;
    std::array<std::size_t,3> shape{1,1,1};
    std::array<Values,3> width{Values(1,.1),Values(1,.1),Values(1,.1)};
    Values epsilon=Values(5,.3),hv=Values(5,1e5),solid_k=Values(5,4.);
    std::array<Fluid,2> fluid;
    std::array<EnergyRelation,2> energy{EnergyRelation::eos_h_TP,EnergyRelation::eos_h_TP};
    std::array<Values,2> conductivity;
    std::array<double,2> inlet_t,inlet_p;
    std::array<int,2> direction;
    std::array<Values,2> pressure,h{Values(5),Values(5)},t{Values(5),Values(5)};
    std::array<std::array<Values,3>,2> mass;
    Values solid=Values(5);
    Case(std::size_t a,int sign,Fluid first,Fluid second):axis(a),fluid{first,second},
        inlet_t{first==Fluid::sco2?340.:first==Fluid::water?350.:380.,300.},
        inlet_p{first==Fluid::sco2?8e6:3e5,second==Fluid::sco2?8e6:2e5},
        direction{static_cast<int>(2*a)+(sign<0),static_cast<int>(2*a)+(sign>0)} {
        shape[axis]=5;width[axis]={.004,.005,.006,.007,.008};
        for (std::size_t s=0;s<2;++s) {
            pressure[s].resize(5);
            for (std::size_t p=0;p<5;++p) pressure[s][p]=inlet_p[s]-100.*p;
            for (std::size_t d=0;d<3;++d) {
                const auto count=(shape[0]+(d==0))*(shape[1]+(d==1))*(shape[2]+(d==2));
                mass[s][d].assign(count,d==axis ? (s==0?sign:-sign)*.005 : 0.);
            }
        }
    }
    GridView grid() const { return {shape[0],shape[1],shape[2],view(width[0]),view(width[1]),view(width[2])}; }
    EnthalpySideView side(std::size_t s) const {
        return {fluid[s],inlet_t[s],inlet_p[s],view(pressure[s]),view(epsilon),view(hv),
            view(mass[s][0]),view(mass[s][1]),view(mass[s][2]),direction[s],energy[s],
            conductivity[s].empty()?ConductivitySource::local_eos:ConductivitySource::prepared,
            view(conductivity[s])};
    }
    EnthalpyStateView state(bool warm=false) {
        return {output(h[0]),output(h[1]),output(t[0]),output(t[1]),output(solid),warm,warm,warm};
    }
    double boundary_power(std::size_t s,double hin) const {
        const bool positive=direction[s]%2==0;
        const std::size_t p=positive?4:0,q=positive?3:1;
        double hout=h[s][p];
        hout+=(h[s][p]-h[s][q])*width[axis][p]/(width[axis][p]+width[axis][q]);
        return .005*(hin-hout);
    }
};
std::size_t cpu_threads=1;
EnthalpyControl controls() {
    EnthalpyControl c{1200,5,.2,2e-12,1e-7,1e-7};
    c.cpu_threads=cpu_threads;
    return c;
}

bool same_fields(const Case& a,const Case& b) {
    return a.t==b.t && a.h==b.h && a.solid==b.solid;
}
bool same(double a,double b) {
    return std::isfinite(a) && std::isfinite(b)
        && std::abs(a-b)<=2e-12*std::max({std::abs(a),std::abs(b),1.});
}
void require_same_actual_solve(const Case& a,const EnthalpyResult& actual,
                               const Case& b,const EnthalpyResult& expected) {
    require(actual.final_audit && expected.final_audit && actual.temperature_update && expected.temperature_update,
            "ordinary replay omitted actual evidence");
    EnthalpyEOS independent;
    for (std::size_t p=0;p<5;++p) {
        for (std::size_t s=0;s<2;++s) {
            require(same(a.t[s][p],b.t[s][p]) && same(a.h[s][p],b.h[s][p]),
                    "ordinary replay changed the actual fluid state");
            const auto pt=independent.evaluate_state(a.fluid[s],a.t[s][p],a.pressure[s][p],"ordinary replay PT reference");
            require(same(a.h[s][p],pt.enthalpy),"ordinary replay published h from a different PT state");
        }
        require(same(a.solid[p],b.solid[p]),"ordinary replay changed the solid state");
    }
    const auto values=[](const EnergyAudit& v) {
        return std::array<double,11>{v.q_a,v.q_b,v.net,v.solid_abs_sum,v.denominator,v.coupled_ratio,
            v.fluid_abs_sum[0],v.fluid_abs_sum[1],v.fluid_cell_max[0],v.fluid_cell_max[1],v.equation_ratio};
    };
    require(actual.final_audit->fluid_equations_computed && expected.final_audit->fluid_equations_computed,
            "ordinary replay omitted its equation audit");
    const auto av=values(*actual.final_audit),bv=values(*expected.final_audit);
    for (std::size_t i=0;i<av.size();++i) require(same(av[i],bv[i]),"ordinary replay changed the actual audit");
    require(same(*actual.temperature_update,*expected.temperature_update) && same(actual.residual,expected.residual)
            && same(actual.q_a,expected.q_a) && same(actual.q_b,expected.q_b)
            && same(actual.energy_imbalance,expected.energy_imbalance),
            "ordinary replay changed the reported update or duty");
}
struct Observations {
    Case* data;
    std::vector<Case> snapshots;
    bool cancel_on_second_repeat=false,triggered=false;
    std::size_t repeats=0;
};
bool observe(void* context) {
    auto& seen=*static_cast<Observations*>(context);
    if (seen.triggered) return true;
    if (!seen.snapshots.empty() && same_fields(seen.snapshots.back(),*seen.data)) ++seen.repeats;
    else seen.repeats=0;
    seen.snapshots.push_back(*seen.data);
    seen.triggered=seen.cancel_on_second_repeat && seen.repeats==2;
    return seen.triggered;
}

struct Cancellation { int calls=0,stop_at=1; };
bool cancel(void* context) {
    auto& c=*static_cast<Cancellation*>(context);
    return ++c.calls>=c.stop_at;
}

template<class Error,class Call> void rejects(Call call,const char* message) {
    try { call(); } catch (const Error&) { return; }
    throw std::runtime_error(message);
}

bool same_value(double a,double b) { return a==b || (std::isnan(a) && std::isnan(b)); }
void require_same_result(const EnthalpyResult& a,const EnthalpyResult& b) {
    require(a.stop==b.stop && a.iterations==b.iterations && a.algorithm==b.algorithm
        && a.inlet_enthalpy==b.inlet_enthalpy && a.enthalpy_update_scale==b.enthalpy_update_scale
        && a.reference_independent_update==b.reference_independent_update && a.last_clips.a==b.last_clips.a
        && a.last_clips.b==b.last_clips.b && a.total_clips.a==b.total_clips.a
        && a.total_clips.b==b.total_clips.b && a.used_bicubic==b.used_bicubic
        && a.heos_polish==b.heos_polish && a.temperature_update==b.temperature_update
        && a.picard_relaxation==b.picard_relaxation && a.final_audit.has_value()==b.final_audit.has_value(),
        "energy continuation changed result state");
    require(same_value(a.residual,b.residual) && same_value(a.q_a,b.q_a)
        && same_value(a.q_b,b.q_b) && same_value(a.energy_imbalance,b.energy_imbalance),
        "energy continuation changed result values");
    if(a.final_audit) {
        const auto values=[](const EnergyAudit& v) {
            return std::array<double,11>{v.q_a,v.q_b,v.net,v.solid_abs_sum,v.denominator,v.coupled_ratio,
                v.fluid_abs_sum[0],v.fluid_abs_sum[1],v.fluid_cell_max[0],v.fluid_cell_max[1],v.equation_ratio};
        };
        const auto x=values(*a.final_audit),y=values(*b.final_audit);
        for(std::size_t i=0;i<x.size();++i)require(same_value(x[i],y[i]),"energy continuation changed final audit");
        require(a.final_audit->fluid_equations_computed==b.final_audit->fluid_equations_computed,
            "energy continuation changed equation audit state");
    }
}

void mixed_model_checks() {
    for(auto model:{Fluid::air,Fluid::water}) {
    std::optional<Case> baseline;
    EnthalpyResult baseline_result{};
    for(bool swap:{false,true}) {
        Case data(0,1,model,Fluid::co2);
        data.inlet_t={350.,300.};data.inlet_p={2e6,8e6};
        for(std::size_t side=0;side<2;++side)std::fill(data.pressure[side].begin(),data.pressure[side].end(),data.inlet_p[side]);
        data.energy[0]=EnergyRelation::integral_cp_T;
        PropertyEvaluator properties;data.conductivity[0].assign(5,.3*properties.transport(model,350.,2e6).k);
        if(swap) {
            std::swap(data.fluid[0],data.fluid[1]);std::swap(data.inlet_t[0],data.inlet_t[1]);
            std::swap(data.inlet_p[0],data.inlet_p[1]);std::swap(data.direction[0],data.direction[1]);
            std::swap(data.pressure[0],data.pressure[1]);std::swap(data.mass[0],data.mass[1]);
            std::swap(data.energy[0],data.energy[1]);std::swap(data.conductivity[0],data.conductivity[1]);
        }
        auto c=controls();
        c.reference_independent_update=true;c.update_tolerance=1e-10;
        Case resumed=data;PhysicalHeatLedger ledger;
        const auto result=solve_enthalpy(data.grid(),data.side(0),data.side(1),view(data.solid_k),data.state(),c,&ledger);
        if(result.stop!=EnthalpyStop::converged || !result.final_audit
            || result.final_audit->equation_ratio>*c.equation_energy_tolerance)
            std::cerr<<"mixed model="<<static_cast<int>(model)<<" swap="<<swap
                <<" stop="<<static_cast<int>(result.stop)
                <<" iterations="<<result.iterations<<" update="<<result.residual
                <<" equation="<<(result.final_audit?result.final_audit->equation_ratio:-1.)
                <<" coupled="<<(result.final_audit?result.final_audit->coupled_ratio:-1.)
                <<" clips="<<result.total_clips.a<<","<<result.total_clips.b<<"\n";
        require(result.stop==EnthalpyStop::converged && result.final_audit
            && result.final_audit->equation_ratio<=*c.equation_energy_tolerance,
            "mixed energy model did not pass its actual equations");
        EnthalpyEOS independent;
        for(std::size_t side=0;side<2;++side) {
            require(!result.used_bicubic[side],"SOU result reports table use");
            const auto inlet=independent.evaluate_state(data.fluid[side],data.inlet_t[side],data.inlet_p[side],"mixed inlet",data.energy[side]);
            require(result.enthalpy_update_scale[side]==50.*inlet.cp,"mixed update scale depends on an enthalpy origin");
            for(std::size_t p=0;p<5;++p) {
                const auto actual=independent.evaluate_state(data.fluid[side],data.t[side][p],data.pressure[side][p],"mixed final",data.energy[side]);
                require(std::abs(actual.enthalpy-data.h[side][p])<1e-7,"mixed model h and T differ");
            }
        }
        if(!swap) {baseline=data;baseline_result=result;}
        else {
            const auto& reference=*baseline;const auto& prior=baseline_result;
            require(std::abs(result.q_a-prior.q_b)<1e-6 && std::abs(result.q_b-prior.q_a)<1e-6,
                "A/B swap changed the mixed-model boundary power");
            require(result.enthalpy_update_scale[0]==prior.enthalpy_update_scale[1]
                && result.enthalpy_update_scale[1]==prior.enthalpy_update_scale[0],
                "A/B swap changed a fluid's update scale");
            for(std::size_t p=0;p<5;++p) {
                require(std::abs(data.t[0][p]-reference.t[1][p])<1e-6
                    && std::abs(data.t[1][p]-reference.t[0][p])<1e-6
                    && std::abs(data.solid[p]-reference.solid[p])<1e-6,
                    "A/B swap changed the mixed-model temperature field");
            }
        }
        const auto direct=result;
        auto owner=std::make_unique<EnthalpyRun>(resumed.grid(),resumed.side(0),resumed.side(1),
            view(resumed.solid_k),resumed.state(),c);
        for(std::size_t step=0;step<2;++step)require(owner->advance()==EnthalpyPhase::active,"mixed fixture finished before its save");
        const auto saved=owner->snapshot();owner.reset();
        for(std::size_t side=0;side<2;++side) {
            auto damaged=saved;damaged.result.enthalpy_update_scale[side]*=1000.;
            Case destination=resumed;const auto before=destination;
            rejects<std::invalid_argument>([&]{EnthalpyRun invalid(destination.grid(),destination.side(0),destination.side(1),
                view(destination.solid_k),destination.state(),c,damaged);},"changed mixed update scale was accepted");
            require(same_fields(destination,before),"invalid mixed update scale changed destination fields");
        }
        owner=std::make_unique<EnthalpyRun>(resumed.grid(),resumed.side(0),resumed.side(1),view(resumed.solid_k),resumed.state(),c,saved);
        while(owner->phase()==EnthalpyPhase::active)owner->advance();
        require(same_fields(data,resumed),"mixed continuation changed physical fields");
        require_same_result(owner->take_result(),direct);
    }
    }
}

void zero_sweep_checks() {
    for(bool warm:{false,true})for(std::size_t axis:{0U,2U}) {
        Case data(axis,1,Fluid::air,Fluid::water);
        for(std::size_t side=0;side<2;++side)
            for(std::size_t p=0;p<5;++p)data.t[side][p]=data.inlet_t[side]+.1*p;
        std::fill(data.solid.begin(),data.solid.end(),330.);
        auto c=controls();c.max_iterations=2;c.sweeps=0;
        EnthalpyRun owner(data.grid(),data.side(0),data.side(1),view(data.solid_k),data.state(warm),c);
        const Case initial=data;
        require(owner.advance()==EnthalpyPhase::active,"zero-sweep residual was accepted as convergence");
        require(same_fields(data,initial),"zero sweeps changed the initialized physical state");
        const auto saved=owner.snapshot();
        owner.advance();
        const auto result=owner.take_result();
        require(result.stop==EnthalpyStop::iteration_limit && result.iterations==2
            && result.temperature_update && *result.temperature_update==0. && result.residual==0.
            && result.final_audit && result.final_audit->equation_ratio>*c.equation_energy_tolerance,
            "zero-sweep budget lost its failed physical gate");
        require(same_fields(data,initial),"zero-sweep budget changed the physical state");
        Case resumed=initial;
        EnthalpyRun continuation(resumed.grid(),resumed.side(0),resumed.side(1),view(resumed.solid_k),
            resumed.state(warm),c,saved);
        while(continuation.phase()==EnthalpyPhase::active)continuation.advance();
        const auto replay=continuation.take_result();
        require_same_result(replay,result);
        require_same_actual_solve(resumed,replay,data,result);
    }
    std::cout<<"zero-sweep budget, physical residual and snapshot checks passed\n";
}


void initial_and_final_transport_checks() {
    for(bool swapped:{false,true})for(bool warm:{false,true})for(bool prepared:{false,true}) {
        Case base(0,1,swapped?Fluid::water:Fluid::sco2,swapped?Fluid::sco2:Fluid::water);
        const std::size_t water=swapped?0:1;
        base.energy[water]=EnergyRelation::integral_cp_T;
        if(prepared)base.conductivity[water]={.21,.22,.23,.24,.25};
        for(std::size_t side=0;side<2;++side)
            for(std::size_t p=0;p<5;++p)base.t[side][p]=base.inlet_t[side]+.1*p;
        std::fill(base.solid.begin(),base.solid.end(),320.);
        auto c=controls();c.max_iterations=13;c.cpu_threads=1;
        Case serial=base,parallel=base;
        EnthalpyRun reference(serial.grid(),serial.side(0),serial.side(1),view(serial.solid_k),serial.state(warm),c);
        c.cpu_threads=4;
        EnthalpyRun actual(parallel.grid(),parallel.side(0),parallel.side(1),view(parallel.solid_k),parallel.state(warm),c);
        const auto initialized=reference.snapshot(),threaded=actual.snapshot();
        require(initialized.fields==threaded.fields,"parallel initialization changed fields");
        for(std::size_t side=0;side<2;++side)
            require(initialized.sides[side].transport==threaded.sides[side].transport,
                "parallel initialization changed transport");
        while(reference.phase()==EnthalpyPhase::active)reference.advance();
        while(actual.phase()==EnthalpyPhase::active)actual.advance();
        std::array<Values,2> conductivity;
        require_same_result(actual.take_result(&conductivity),reference.take_result());
        require(same_fields(parallel,serial),"parallel initialization changed the final fields");
        EnthalpyEOS independent;
        for(std::size_t side=0;side<2;++side) {
            require(conductivity[side].size()==5,"final conductivity was not transferred");
            for(std::size_t p=0;p<5;++p) {
                const double expected=parallel.conductivity[side].empty()
                    ?parallel.epsilon[p]*independent.conductivity(parallel.fluid[side],parallel.t[side][p],parallel.pressure[side][p])
                    :parallel.conductivity[side][p];
                require(conductivity[side][p]==expected,"transferred conductivity differs from the final state");
            }
        }
        rejects<std::logic_error>([&]{actual.take_result(&conductivity);},"conductivity was transferred twice");
    }
    Case data(0,1,Fluid::sco2,Fluid::water);auto c=controls();
    c.cancel=[](void*){return true;};
    EnthalpyRun cancelled(data.grid(),data.side(0),data.side(1),view(data.solid_k),data.state(),c);
    std::array<Values,2> output{{{1.},{2.}}};const auto before=output;
    require(cancelled.take_result(&output).stop==EnthalpyStop::cancelled && output==before,
        "cancelled run transferred incomplete conductivity");
    std::cout<<"parallel initialization and final conductivity checks passed\n";
}

void energy_run_checks() {
    const std::array<std::array<Fluid,2>,4> pairs{{{Fluid::air,Fluid::water},{Fluid::water,Fluid::air},
        {Fluid::sco2,Fluid::water},{Fluid::co2,Fluid::air}}};
    for(const auto& pair:pairs)for(std::size_t axis:{0U,2U})for(bool warm:{false,true}) {
        Case base(axis,1,pair[0],pair[1]);
        for(std::size_t side=0;side<2;++side)
            std::fill(base.t[side].begin(),base.t[side].end(),warm?base.inlet_t[side]:std::numeric_limits<double>::quiet_NaN());
        std::fill(base.solid.begin(),base.solid.end(),.5*(base.inlet_t[0]+base.inlet_t[1]));
        auto c=controls();
        c.max_iterations=13;
        Case expected=base;PhysicalHeatLedger expected_ledger;
        Cancellation baseline{0,1000000};c.cancel=cancel;c.context=&baseline;
        const auto reference=solve_enthalpy(expected.grid(),expected.side(0),expected.side(1),
            view(expected.solid_k),expected.state(warm),c,&expected_ledger);
        for(std::size_t cut:{0U,1U,2U,7U,12U}) {
            Case actual=base;Cancellation observed{0,1000000};c.context=&observed;PhysicalHeatLedger ledger;
            auto owner=std::make_unique<EnthalpyRun>(actual.grid(),actual.side(0),actual.side(1),
                view(actual.solid_k),actual.state(warm),c,&ledger);
            for(std::size_t i=0;i<cut && owner->phase()==EnthalpyPhase::active;++i)owner->advance();
            if(owner->phase()==EnthalpyPhase::active) {
                auto saved=owner->snapshot();saved.fields[0][0]+=1.;
                require(saved.fields[0]!=owner->snapshot().fields[0],"energy snapshot aliases live fields");
                saved=owner->snapshot();owner.reset();
                std::fill(actual.solid.begin(),actual.solid.end(),-1.);
                owner=std::make_unique<EnthalpyRun>(actual.grid(),actual.side(0),actual.side(1),
                    view(actual.solid_k),actual.state(warm),c,saved,&ledger);
                saved.fields[0][0]+=1.;
                require(saved.fields[0]!=owner->snapshot().fields[0],"energy restore borrows its snapshot");
            }
            while(owner->phase()==EnthalpyPhase::active)owner->advance();
            require(same_fields(actual,expected),"energy continuation changed fields");
            require(observed.calls>0,"energy continuation omitted cancellation checks");
            // Parallel wait polling depends on worker timing.
            if(c.cpu_threads==1)
                require(observed.calls==baseline.calls,"energy continuation changed cancellation calls");
            require(ledger.residual==expected_ledger.residual && ledger.advective_out==expected_ledger.advective_out,
                "energy continuation changed physical ledger");
            require_same_result(owner->take_result(),reference);
            rejects<std::logic_error>([&]{owner->snapshot();},"completed energy run exported state");
            rejects<std::logic_error>([&]{owner->take_result();},"energy result was transferred twice");
            owner->advance();
        }
    }
    Case sample(0,1,Fluid::air,Fluid::water);auto c=controls();c.max_iterations=30;
    auto run=std::make_unique<EnthalpyRun>(sample.grid(),sample.side(0),sample.side(1),view(sample.solid_k),sample.state(),c);
    run->advance();run->advance();const auto saved=run->snapshot();
    for(int damage=0;damage<20;++damage) {
        auto state=saved;
        switch(damage) {
        case 0:state.fields[0].pop_back();break;
        case 1:state.fields[2][0]=std::numeric_limits<double>::infinity();break;
        case 2:state.result.iterations=c.max_iterations;break;
        case 3:state.result.algorithm=static_cast<EnthalpyAlgorithm>(0);break;
        case 4:state.result.stop=EnthalpyStop::converged;break;
        case 5:state.sides[0].transport[0][0]=0.;break;
        case 6:state.result.heos_polish=true;break;
        case 7:state.sides[0].transport[1].pop_back();break;
        case 8:state.acceleration.r[0][0]=std::numeric_limits<double>::infinity();break;
        case 9:state.result.used_bicubic[0]=true;break;
        case 10:state.result.temperature_update.reset();break;
        case 11:state.result.final_audit.reset();break;
        case 12:state.result.final_audit->equation_ratio=std::numeric_limits<double>::quiet_NaN();break;
        case 13:state.result.final_audit->denominator=0.;break;
        case 14:state.result.final_audit->fluid_equations_computed=false;break;
        case 15:state.result.energy_imbalance=-1.;break;
        case 16:state.result.final_audit->solid_abs_sum=-1.;break;
        case 17:state.result.enthalpy_update_scale[0]=0.;break;
        case 18:state.result.reference_independent_update=!c.reference_independent_update;break;
        case 19:state.result.enthalpy_update_scale[0]*=1000.;break;
        }
        Case destination=sample;const auto before=destination;
        rejects<std::invalid_argument>([&]{EnthalpyRun invalid(destination.grid(),destination.side(0),destination.side(1),
            view(destination.solid_k),destination.state(),c,state);},"damaged energy state was accepted");
        require(same_fields(destination,before),"invalid energy state changed destination fields");
    }
    for(int stop_at:{1,4,9,17}) {
        Case expected(0,1,Fluid::air,Fluid::water),actual=expected;
        auto options=controls();
        // Callback-count cancellation requires deterministic serial polling.
        options.cpu_threads=1;
        Cancellation baseline{0,stop_at},observed{0,stop_at};options.cancel=cancel;options.context=&baseline;
        const auto reference=solve_enthalpy(expected.grid(),expected.side(0),expected.side(1),view(expected.solid_k),expected.state(),options);
        options.context=&observed;auto owner=std::make_unique<EnthalpyRun>(actual.grid(),actual.side(0),actual.side(1),view(actual.solid_k),actual.state(),options);
        while(owner->phase()==EnthalpyPhase::active) {
            owner->advance();
            if(owner->phase()==EnthalpyPhase::active) {
                const auto state=owner->snapshot();owner.reset();
                owner=std::make_unique<EnthalpyRun>(actual.grid(),actual.side(0),actual.side(1),view(actual.solid_k),actual.state(),options,state);
            }
        }
        require(owner->phase()==EnthalpyPhase::cancelled && same_fields(actual,expected)
            && observed.calls==baseline.calls,"energy resume changed cancellation timing");
        require_same_result(owner->take_result(),reference);
        rejects<std::logic_error>([&]{owner->snapshot();},"cancelled energy run exported state");
    }
    Case observed(0,1,Fluid::air,Fluid::water);auto observing=controls();observing.max_iterations=3;
    struct Observer { EnthalpyRun* run=nullptr;std::size_t calls=0; } observer;
    observing.context=&observer;
    observing.cancel=[](void* context) {
        auto& current=*static_cast<Observer*>(context);
        if(current.run) {
            ++current.calls;
            rejects<std::logic_error>([&]{current.run->snapshot();},"callback exported an unfinished energy step");
            rejects<std::logic_error>([&]{current.run->advance();},"callback advanced an unfinished energy step");
        }
        return false;
    };
    EnthalpyRun observed_run(observed.grid(),observed.side(0),observed.side(1),view(observed.solid_k),observed.state(),observing);
    observer.run=&observed_run;
    while(observed_run.phase()==EnthalpyPhase::active)observed_run.advance();
    require(observer.calls>=6,"energy callback omitted the active boundary check");
    Case failed(0,1,Fluid::air,Fluid::water);auto failing=controls();Cancellation failure{0,2};failing.context=&failure;
    failing.cancel=[](void* context) { if(++static_cast<Cancellation*>(context)->calls==2)throw std::runtime_error("failed callback");return false; };
    EnthalpyRun broken(failed.grid(),failed.side(0),failed.side(1),view(failed.solid_k),failed.state(),failing);
    rejects<std::runtime_error>([&]{broken.advance();},"callback failure was hidden");
    require(broken.phase()==EnthalpyPhase::failed,"failed energy run remained active");
    rejects<std::logic_error>([&]{broken.snapshot();},"failed energy run exported state");
    rejects<std::logic_error>([&]{broken.advance();},"failed energy run advanced again");
    std::cout<<"energy run continuation, ownership and invalid boundaries passed\n";
}

void optional_gate_checks() {
    for(unsigned gates=0;gates<4;++gates) {
        Case data(0,1,Fluid::air,Fluid::water);auto c=controls();
        if(!(gates&1))c.coupled_energy_tolerance.reset();
        if(!(gates&2))c.equation_energy_tolerance.reset();
        c.require_enthalpy_update_on_temperature=true;c.update_tolerance=1e-8;
        EnthalpyRun running(data.grid(),data.side(0),data.side(1),view(data.solid_k),data.state(),c);
        running.advance();require(running.phase()==EnthalpyPhase::active,"optional gate case finished before snapshot");
        const auto saved=running.snapshot();auto restored=data;
        EnthalpyRun resumed(restored.grid(),restored.side(0),restored.side(1),view(restored.solid_k),restored.state(),c,saved);
        while(running.phase()==EnthalpyPhase::active)running.advance();
        while(resumed.phase()==EnthalpyPhase::active)resumed.advance();
        const auto actual=running.take_result(),replay=resumed.take_result();
        require_same_actual_solve(data,actual,restored,replay);
        require(actual.stop==EnthalpyStop::converged && actual.final_audit && actual.final_audit->fluid_equations_computed,
                "optional T gates lost full equation evidence");
        require(actual.temperature_update && *actual.temperature_update<=c.temperature_update_tolerance
                && actual.residual<=c.update_tolerance,"optional T gates changed update units");
        if(c.coupled_energy_tolerance)require(actual.final_audit->coupled_ratio<=*c.coupled_energy_tolerance,"optional coupled gate failed");
        if(c.equation_energy_tolerance)require(actual.final_audit->equation_ratio<=*c.equation_energy_tolerance,"optional equation gate failed");
    }
    for(double value:{0.,-1.,std::numeric_limits<double>::quiet_NaN()}) {
        Case invalid(0,1,Fluid::air,Fluid::water);auto c=controls();
        c.coupled_energy_tolerance=value;c.equation_energy_tolerance.reset();
        rejects<std::invalid_argument>([&] {solve_enthalpy(invalid.grid(),invalid.side(0),invalid.side(1),
            view(invalid.solid_k),invalid.state(),c);},"invalid optional T gate was accepted");
    }
    std::cout<<"optional T stop gates, update units and snapshot replay passed\n";
}

void scalar_inflow_checks() {
    for(std::size_t axis=0;axis<3;++axis) for(int sign:{1,-1}) {
        Case directed(axis,sign,Fluid::air,Fluid::water);auto c=controls();
        const auto expected=solve_enthalpy(directed.grid(),directed.side(0),directed.side(1),
            view(directed.solid_k),directed.state(),c);
        Case scalar(axis,sign,Fluid::air,Fluid::water);scalar.direction={-1,-1};
        const auto actual=solve_enthalpy(scalar.grid(),scalar.side(0),scalar.side(1),
            view(scalar.solid_k),scalar.state(),c);
        require_same_actual_solve(scalar,actual,directed,expected);
        Case multiple(axis,sign,Fluid::air,Fluid::water);multiple.direction={-1,-1};
        const auto transverse=(axis+1)%3;
        for(auto& side:multiple.mass)std::fill(side[transverse].begin(),side[transverse].end(),.0001);
        const auto solved=solve_enthalpy(multiple.grid(),multiple.side(0),multiple.side(1),
            view(multiple.solid_k),multiple.state(),c);
        require(solved.stop==EnthalpyStop::converged && solved.final_audit,
                "scalar multiple-inlet solve did not converge");
        require(solved.final_audit->coupled_ratio<=1e-7 && solved.final_audit->equation_ratio<=1e-7,
                "scalar multiple-inlet energy gate failed");
        for(std::size_t side=0;side<2;++side) {
            const bool positive=side==0?sign>0:sign<0;
            const std::size_t p=positive?4:0,q=positive?3:1;
            double outlet=multiple.h[side][p];
            outlet+=(multiple.h[side][p]-multiple.h[side][q])
                *multiple.width[axis][p]/(multiple.width[axis][p]+multiple.width[axis][q]);
            double power=.005*(solved.inlet_enthalpy[side]-outlet);
            for(double h:multiple.h[side])power+=.0001*(solved.inlet_enthalpy[side]-h);
            require(same(power,side==0?solved.q_a:solved.q_b),
                    "scalar multiple-inlet boundary power differs from independent sum");
        }
    }
    for(int direction:{-2,6}) {
        Case invalid(0,1,Fluid::air,Fluid::water);invalid.direction[0]=direction;
        auto c=controls();
        rejects<std::invalid_argument>([&] {solve_enthalpy(invalid.grid(),invalid.side(0),invalid.side(1),
            view(invalid.solid_k),invalid.state(),c);},"invalid scalar inlet direction was accepted");
    }
    std::cout<<"scalar inlet states, multiple inflows and independent boundary powers passed\n";
}

}  // namespace

int main(int argc,char** argv) {
    try {
        require(argc<=2,"expected one optional CPU thread count");
        if(argc==2)cpu_threads=std::stoul(argv[1]);
        require(cpu_threads>0,"CPU thread count must be positive");
        optional_gate_checks();
        scalar_inflow_checks();
        zero_sweep_checks();
        initial_and_final_transport_checks();
        energy_run_checks();
        mixed_model_checks();
        std::size_t solved=0;
        double max_eos_error=0.,max_boundary_error=0.,max_warm_difference=0.;
        const std::array<std::array<Fluid,2>,4> pairs{{{Fluid::air,Fluid::air},
            {Fluid::air,Fluid::water},{Fluid::water,Fluid::air},{Fluid::sco2,Fluid::sco2}}};
        for (const auto& pair:pairs) for (std::size_t axis=0;axis<3;++axis)
            for (int sign:{1,-1}) {
                Case data(axis,sign,pair[0],pair[1]);auto c=controls();
                const auto result=solve_enthalpy(data.grid(),data.side(0),data.side(1),view(data.solid_k),data.state(),c);
                require(result.stop==EnthalpyStop::converged && result.final_audit && result.temperature_update,
                        "T energy solve did not converge with actual evidence");
                require(result.algorithm==c.algorithm && !result.used_bicubic[0] && !result.used_bicubic[1]
                        && !result.heos_polish && !result.total_clips.a && !result.total_clips.b,
                        "T energy algorithm identity is not the executed method");
                require(result.picard_relaxation==.6,"actual Picard relaxation evidence is missing");
                require(*result.temperature_update<=1e-8 && result.final_audit->equation_ratio<=1e-7
                        && result.final_audit->coupled_ratio<=1e-7,"T energy gate was bypassed");
                for (std::size_t s=0;s<2;++s) for (std::size_t p=0;p<5;++p) {
                    const auto exact=std::unique_ptr<CoolProp::AbstractState>(
                        CoolProp::AbstractState::factory("HEOS",data.fluid[s]==Fluid::air?"Air":data.fluid[s]==Fluid::water?"Water":"CO2"));
                    exact->update(CoolProp::PT_INPUTS,data.pressure[s][p],data.t[s][p]);
                    max_eos_error=std::max(max_eos_error,std::abs(exact->hmass()-data.h[s][p]));
                }
                max_boundary_error=std::max({max_boundary_error,
                    std::abs(result.q_a-data.boundary_power(0,result.inlet_enthalpy[0])),
                    std::abs(result.q_b-data.boundary_power(1,result.inlet_enthalpy[1]))});
                auto warm=data;
                for (std::size_t p=0;p<5;++p) {
                    warm.t[0][p]=.8*data.inlet_t[0]+.2*data.inlet_t[1];
                    warm.t[1][p]=.2*data.inlet_t[0]+.8*data.inlet_t[1];
                    warm.solid[p]=.5*(data.inlet_t[0]+data.inlet_t[1]);
                }
                const auto again=solve_enthalpy(warm.grid(),warm.side(0),warm.side(1),view(warm.solid_k),warm.state(true),c);
                require(again.stop==EnthalpyStop::converged,"warm T energy solve did not converge");
                for (std::size_t p=0;p<5;++p) {
                    for (std::size_t s=0;s<2;++s) max_warm_difference=std::max(max_warm_difference,std::abs(data.t[s][p]-warm.t[s][p]));
                    max_warm_difference=std::max(max_warm_difference,std::abs(data.solid[p]-warm.solid[p]));
                }
                ++solved;
            }
        require(max_eos_error<=1e-6,"published T and h are not the same actual EOS state");
        require(max_boundary_error<=1e-9,"actual boundary duty omitted SOU outlet reconstruction");
        require(max_warm_difference<=1e-6,"warm and cold T energy solve different equations");

        // Each explicit gate must control the actual exit, not merely appear
        // in reported settings. The one-step fixtures isolate one gate each.
        {
            Case loose(0,1,Fluid::air,Fluid::water);auto gate=controls();
            gate.max_iterations=1;gate.sweeps=1;gate.update_tolerance=1e-30;
            gate.temperature_update_tolerance=1e6;
            gate.coupled_energy_tolerance=gate.equation_energy_tolerance=1e6;
            require(!gate.require_enthalpy_update_on_temperature,"extra h gate changed the T default");
            const auto ungated=solve_enthalpy(loose.grid(),loose.side(0),loose.side(1),view(loose.solid_k),loose.state(),gate);
            require(ungated.stop==EnthalpyStop::converged && ungated.residual>1e-30
                    && ungated.final_audit && ungated.final_audit->coupled_ratio>1e-30
                    && ungated.final_audit->equation_ratio>1e-30,"one-step gate fixture is not discriminating");
            for(int selected=0;selected<3;++selected) {
                Case strict(0,1,Fluid::air,Fluid::water);auto selected_gate=gate;
                if(selected==0)selected_gate.require_enthalpy_update_on_temperature=true;
                if(selected==1)selected_gate.coupled_energy_tolerance=1e-30;
                if(selected==2)selected_gate.equation_energy_tolerance=1e-30;
                const auto stopped=solve_enthalpy(strict.grid(),strict.side(0),strict.side(1),view(strict.solid_k),strict.state(),selected_gate);
                require(stopped.stop==EnthalpyStop::iteration_limit && stopped.iterations==1
                        && stopped.final_audit && stopped.temperature_update
                        && *stopped.temperature_update<=gate.temperature_update_tolerance,
                        "strict actual h/coupled/equation gate did not block the native exit");
            }
            for(double bad:{0.,-1.,std::numeric_limits<double>::infinity(),std::numeric_limits<double>::quiet_NaN()}) {
                Case invalid_gate(0,1,Fluid::air,Fluid::water);auto invalid=gate;
                invalid.require_enthalpy_update_on_temperature=true;invalid.update_tolerance=bad;
                rejects<std::invalid_argument>([&] {
                    solve_enthalpy(invalid_gate.grid(),invalid_gate.side(0),invalid_gate.side(1),
                                   view(invalid_gate.solid_k),invalid_gate.state(),invalid);
                },"T energy accepted an invalid additional h-update tolerance");
            }
        }

        // Accepted AA must seed a complete ordinary confirmation. The last
        // three callbacks see the unvalidated image, accepted state, and final
        // ordinary swept T. An h-only change cannot prove AA was accepted.
        {
            Case data(0,1,Fluid::air,Fluid::water);auto c=controls();
            c.max_iterations=3;c.require_enthalpy_update_on_temperature=true;
            c.temperature_update_tolerance=c.update_tolerance=1e-30;
            c.coupled_energy_tolerance=c.equation_energy_tolerance=1e-30;
            Observations seen{&data,{}};c.context=&seen;c.cancel=observe;
            const auto result=solve_enthalpy(data.grid(),data.side(0),data.side(1),
                view(data.solid_k),data.state(),c);
            require(result.stop==EnthalpyStop::iteration_limit && result.iterations==3
                    && result.final_audit && result.temperature_update && seen.snapshots.size()>=3,
                    "AA confirmation fixture did not reach its three-block budget");
            const auto tail=seen.snapshots.size()-3;
            const auto& ordinary=seen.snapshots[tail];
            const auto& accepted=seen.snapshots[tail+1];
            const auto& swept=seen.snapshots[tail+2];
            require(accepted.t!=ordinary.t || accepted.solid!=ordinary.solid,
                    "AA confirmation fixture never accepted a candidate");
            require(swept.h==accepted.h && swept.t==data.t && swept.solid==data.solid,
                    "AA confirmation callback tail is not the final ordinary block");
            Case replay=accepted;auto one=c;
            one.max_iterations=1;one.cancel=nullptr;one.context=nullptr;
            const auto repeated=solve_enthalpy(replay.grid(),replay.side(0),replay.side(1),
                view(replay.solid_k),replay.state(true),one);
            require(repeated.stop==EnthalpyStop::iteration_limit && repeated.iterations==1,
                    "AA confirmation replay did not execute one ordinary block");
            require_same_actual_solve(data,result,replay,repeated);
            double actual_dT=0.,actual_dh=0.;
            for (std::size_t p=0;p<5;++p) {
                for (std::size_t s=0;s<2;++s) {
                    actual_dT=std::max(actual_dT,std::abs(data.t[s][p]-accepted.t[s][p]));
                    actual_dh=std::max(actual_dh,std::abs(data.h[s][p]-accepted.h[s][p]));
                }
                actual_dT=std::max(actual_dT,std::abs(data.solid[p]-accepted.solid[p]));
            }
            actual_dh/=std::max(std::abs(result.inlet_enthalpy[0]-result.inlet_enthalpy[1]),1.);
            require(same(*result.temperature_update,actual_dT) && same(result.residual,actual_dh),
                    "AA confirmation update certificate refers to a different starting state");
        }

        // This warm fixture rejects the fifth-block trial. Callback snapshots
        // verify trial isolation and ordinary fallback; they do not identify
        // the rejection reason or count candidate EOS evaluations.
        {
            Case data(0,1,Fluid::air,Fluid::water);auto c=controls();c.max_iterations=6;
            data.t={Values(5,364.),Values(5,316.)};data.solid.assign(5,340.);
            Observations seen{&data,{}};c.context=&seen;c.cancel=observe;
            const auto result=solve_enthalpy(data.grid(),data.side(0),data.side(1),
                view(data.solid_k),data.state(true),c);
            require(result.stop==EnthalpyStop::iteration_limit && result.iterations==6
                    && result.final_audit && result.temperature_update && seen.snapshots.size()>=4,
                    "rollback fixture did not reach its six-block budget");
            const auto image_index=seen.snapshots.size()-3;
            const auto& image=seen.snapshots[image_index];
            const auto& ordinary=seen.snapshots[image_index+1];
            const auto& swept=seen.snapshots[image_index+2];
            require(image.t==ordinary.t && image.solid==ordinary.solid && image.h!=ordinary.h,
                    "rollback fixture did not take an ordinary EOS fallback");
            require(swept.h==ordinary.h && swept.t==data.t && swept.solid==data.solid,
                    "rollback callback tail is not the final ordinary block");
            auto first_image=image_index;
            while (first_image>0 && same_fields(seen.snapshots[first_image-1],image)) --first_image;
            require(first_image>0 && image_index-first_image+1==5,
                    "rollback fixture missed its five isolated trial/fallback callbacks");
            const auto& before=seen.snapshots[first_image-1];
            require(image.h==before.h && (image.t!=before.t || image.solid!=before.solid),
                    "rejected candidate changed caller enthalpy before ordinary validation");
            Case replay=before;auto two=c;two.max_iterations=2;two.cancel=nullptr;two.context=nullptr;
            const auto repeated=solve_enthalpy(replay.grid(),replay.side(0),replay.side(1),
                view(replay.solid_k),replay.state(true),two);
            require(repeated.stop==EnthalpyStop::iteration_limit && repeated.iterations==2,
                    "rollback replay did not execute two ordinary blocks");
            require_same_actual_solve(data,result,replay,repeated);
        }

        // The first trial's post-sweep/A0/B0 callbacks see identical caller
        // fields. Cancel at B0 after five A-side candidate PT evaluations;
        // cancellation must prevent an ordinary iteration-2 update.
        {
            Case data(0,1,Fluid::air,Fluid::water);auto c=controls();c.max_iterations=3;
            data.t={Values(5,364.),Values(5,316.)};data.solid.assign(5,340.);
            Observations seen{&data,{}};seen.cancel_on_second_repeat=true;c.context=&seen;c.cancel=observe;
            const auto result=solve_enthalpy(data.grid(),data.side(0),data.side(1),
                view(data.solid_k),data.state(true),c);
            require(seen.triggered && result.stop==EnthalpyStop::cancelled && result.iterations==2
                    && !result.final_audit && seen.snapshots.size()>=4,
                    "inner candidate cancellation did not clear the final audit");
            const auto image_index=seen.snapshots.size()-3;
            const auto& before=seen.snapshots[image_index-1];
            const auto& image=seen.snapshots[image_index];
            require(same_fields(image,seen.snapshots[image_index+1])
                    && same_fields(image,seen.snapshots[image_index+2]) && same_fields(image,data),
                    "cancelled trial published scratch candidate fields");
            require(image.h==before.h && (image.t!=before.t || image.solid!=before.solid),
                    "inner cancellation did not preserve the unaudited ordinary image");
        }

        // A legal positive energy tolerance may overflow normalized merit.
        // Preserve the raw gates and skip optional AA, without a tolerance
        // floor. The one-block probe permits T convergence to isolate the
        // energy gate; its ordinary state also seeds the two-block replay.
        {
            constexpr double tiny=1e-310;
            Case data(0,1,Fluid::air,Fluid::water);auto c=controls();c.max_iterations=3;
            data.t={Values(5,364.),Values(5,316.)};data.solid.assign(5,340.);
            c.coupled_energy_tolerance=c.equation_energy_tolerance=tiny;
            Case replay=data;auto one=c;one.max_iterations=1;one.temperature_update_tolerance=1e6;
            const auto first=solve_enthalpy(replay.grid(),replay.side(0),replay.side(1),
                view(replay.solid_k),replay.state(true),one);
            require(tiny>0. && first.stop==EnthalpyStop::iteration_limit && first.iterations==1
                    && first.final_audit && first.temperature_update
                    && !one.require_enthalpy_update_on_temperature && std::isfinite(*first.temperature_update)
                    && *first.temperature_update<=one.temperature_update_tolerance,
                    "tiny legal energy tolerance did not independently block convergence");
            const auto& audit=*first.final_audit;
            require(std::isfinite(audit.equation_ratio) && std::isfinite(audit.coupled_ratio)
                    && audit.equation_ratio>tiny && audit.coupled_ratio>tiny,
                    "tiny-tolerance probe did not produce finite failing energy ratios");
            const double merit=std::max(audit.equation_ratio/tiny,audit.coupled_ratio/tiny);
            require(std::isinf(merit) && merit>0.,"tiny-tolerance probe did not overflow normalized merit");
            Observations seen{&data,{}};c.context=&seen;c.cancel=observe;
            const auto result=solve_enthalpy(data.grid(),data.side(0),data.side(1),
                view(data.solid_k),data.state(true),c);
            require(result.stop==EnthalpyStop::iteration_limit && result.iterations==3
                    && seen.snapshots.size()==7 && same_fields(replay,seen.snapshots[3]),
                    "nonfinite reference merit did not skip the optional AA trial");
            double pre_dT=0.;
            const auto& before=seen.snapshots[3];const auto& image=seen.snapshots[4];
            for (std::size_t p=0;p<5;++p) {
                for (std::size_t s=0;s<2;++s) {
                    require(std::isfinite(image.t[s][p]),"tiny-tolerance ordinary image is not finite");
                    pre_dT=std::max(pre_dT,std::abs(image.t[s][p]-before.t[s][p]));
                }
                require(std::isfinite(image.solid[p]),"tiny-tolerance solid image is not finite");
                pre_dT=std::max(pre_dT,std::abs(image.solid[p]-before.solid[p]));
            }
            require(std::isfinite(pre_dT) && pre_dT>c.temperature_update_tolerance,
                    "tiny-tolerance fixture skipped AA because of a small T update");
            auto two=c;two.max_iterations=2;two.cancel=nullptr;two.context=nullptr;
            const auto repeated=solve_enthalpy(replay.grid(),replay.side(0),replay.side(1),
                view(replay.solid_k),replay.state(true),two);
            require(repeated.stop==EnthalpyStop::iteration_limit && repeated.iterations==2,
                    "tiny-tolerance replay did not execute two ordinary blocks");
            require_same_actual_solve(data,result,replay,repeated);
        }

        // Real CoolProp two-phase rejection from a finite, positive AA
        // proposal. Ordinary EOS failures must still propagate unchanged.
        {
            Case data(0,1,Fluid::air,Fluid::air);
            data.inlet_t={150.,60.};data.inlet_p={1e6,1e6};
            data.t={Values(5,141.),Values(5,69.)};data.solid.assign(5,105.);
            for(auto& pressure:data.pressure)
                for(std::size_t p=0;p<5;++p) pressure[p]=1e6-100.*p;
            auto c=controls();c.temperature_update_tolerance=1e-30;c.max_iterations=2;
            Case ordinary=data;
            const auto probe=solve_enthalpy(ordinary.grid(),ordinary.side(0),ordinary.side(1),
                view(ordinary.solid_k),ordinary.state(true),c);
            require(probe.stop==EnthalpyStop::iteration_limit && probe.iterations==2
                    && probe.final_audit && probe.temperature_update,
                    "CoolProp trial fixture did not retain two valid ordinary blocks");

            c.max_iterations=3;
            Observations seen{&data,{}};c.context=&seen;c.cancel=observe;
            const auto result=solve_enthalpy(data.grid(),data.side(0),data.side(1),
                view(data.solid_k),data.state(true),c);
            require(result.stop==EnthalpyStop::iteration_limit && result.iterations==3
                    && result.final_audit && result.temperature_update && seen.snapshots.size()>=3,
                    "CoolProp candidate exception escaped its ordinary fallback");
            const auto tail=seen.snapshots.size()-3;
            const auto& image=seen.snapshots[tail];
            const auto& actual=seen.snapshots[tail+1];
            const auto& swept=seen.snapshots[tail+2];
            require(image.t==actual.t && image.solid==actual.solid && image.h!=actual.h
                    && same_fields(actual,ordinary),
                    "CoolProp rejection changed the two-block ordinary state");
            require(swept.h==actual.h && swept.t==data.t && swept.solid==data.solid,
                    "CoolProp rejection skipped the final ordinary block");
            auto one=c;one.max_iterations=1;one.cancel=nullptr;one.context=nullptr;
            const auto repeated=solve_enthalpy(ordinary.grid(),ordinary.side(0),ordinary.side(1),
                view(ordinary.solid_k),ordinary.state(true),one);
            require(repeated.stop==EnthalpyStop::iteration_limit && repeated.iterations==1,
                    "CoolProp rejection replay did not execute one ordinary block");
            require_same_actual_solve(data,result,ordinary,repeated);

            // The rejected PT was side A cell 3. As an initial state it is
            // an actual input failure, not an optional trial to discard.
            Case invalid=actual;
            invalid.t[0][3]=107.4014706134527;
            rejects<CoolProp::CoolPropBaseError>([&] {
                solve_enthalpy(invalid.grid(),invalid.side(0),invalid.side(1),
                    view(invalid.solid_k),invalid.state(true),one);
            },"ordinary initial CoolProp failure was swallowed");
        }

        // Unit-depth 2D and a physical nz=1 extrusion have identical T fields;
        // integrated convection, diffusion and exchange all scale with depth.
        for(std::size_t axis:{0u,1u}) for(int sign:{1,-1}) {
            Case unit(axis,sign,Fluid::water,Fluid::sco2);
            unit.width[2][0]=1.;
            auto slab=unit;
            constexpr double thickness=.037;
            slab.width[2][0]=thickness;
            for(auto& side:slab.mass)for(auto& component:side)
                for(double& value:component)value*=thickness;
            const auto c=controls();
            const auto per_depth=solve_enthalpy(unit.grid(),unit.side(0),unit.side(1),
                view(unit.solid_k),unit.state(),c);
            const auto integrated=solve_enthalpy(slab.grid(),slab.side(0),slab.side(1),
                view(slab.solid_k),slab.state(),c);
            require(per_depth.stop==EnthalpyStop::converged && integrated.stop==EnthalpyStop::converged,
                    "unit-depth candidate did not converge");
            for(std::size_t p=0;p<5;++p) {
                for(std::size_t s=0;s<2;++s)
                    require(std::abs(unit.t[s][p]-slab.t[s][p])<=1e-6,"extrusion changed fluid temperature");
                require(std::abs(unit.solid[p]-slab.solid[p])<=1e-6,"extrusion changed solid temperature");
            }
            require(std::abs(integrated.q_a/thickness-per_depth.q_a)<=1e-7*std::abs(per_depth.q_a)+1e-9
                    && std::abs(integrated.q_b/thickness-per_depth.q_b)<=1e-7*std::abs(per_depth.q_b)+1e-9,
                    "extrusion lost unit-depth duty scaling");
        }

        for (int stop_at:{1,3,4}) {
            Case data(0,1,Fluid::air,Fluid::water);auto c=controls();Cancellation token{0,stop_at};
            c.cancel=cancel;c.context=&token;
            const auto result=solve_enthalpy(data.grid(),data.side(0),data.side(1),view(data.solid_k),data.state(),c);
            require(result.stop==EnthalpyStop::cancelled && !result.final_audit,"cancelled T solve published a final certificate");
        }
        Case limited(0,1,Fluid::air,Fluid::water);auto limit=controls();limit.max_iterations=1;
        const auto stopped=solve_enthalpy(limited.grid(),limited.side(0),limited.side(1),view(limited.solid_k),limited.state(),limit);
        require(stopped.stop==EnthalpyStop::iteration_limit && stopped.iterations==1 && stopped.final_audit
                && stopped.temperature_update && !stopped.total_clips.a && !stopped.total_clips.b,
                "T energy budget exit lost its actual evidence");
        Case unknown(0,1,Fluid::air,Fluid::water);unknown.mass[0][0].back()=-.001;
        auto c=controls();
        rejects<std::invalid_argument>([&] { solve_enthalpy(unknown.grid(),unknown.side(0),unknown.side(1),view(unknown.solid_k),unknown.state(),c); },
                                       "undefined exterior inflow was accepted");
        Case invalid(0,1,Fluid::air,Fluid::water);
        c.cpu_threads=0;
        rejects<std::invalid_argument>([&] { solve_enthalpy(invalid.grid(),invalid.side(0),invalid.side(1),view(invalid.solid_k),invalid.state(),c); },
                                       "zero CPU thread count was accepted");
        c.cpu_threads=cpu_threads;
        c.equation_energy_tolerance=0.;
        rejects<std::invalid_argument>([&] { solve_enthalpy(invalid.grid(),invalid.side(0),invalid.side(1),view(invalid.solid_k),invalid.state(),c); },
                                       "T energy accepted a zero equation tolerance");
        EnthalpyEOS eos;
        for (double bad_t:{270.,500.,std::numeric_limits<double>::quiet_NaN()})
            rejects<WaterStateError>([&] { eos.evaluate_state(Fluid::water,bad_t,2e5,"PT guard regression"); },"actual PT water guard was bypassed");
        rejects<std::invalid_argument>([&] { eos.evaluate_state(Fluid::sco2,300.,7e6,"PT guard regression"); },"actual PT CO2 domain was bypassed");
        rejects<WaterStateError>([&] { eos.evaluate_state(Fluid::water,300.,30e6,"PT guard regression"); },
                                 "high-pressure water guard was bypassed");
        rejects<std::invalid_argument>([&] { eos.evaluate_state(Fluid::co2,215.,8e6,"PT guard regression"); },
                                       "CO2 triple-point guard was bypassed");
        // Reuse the evaluator after rejected states and other valid PT states.
        for (const auto fluid:{Fluid::water,Fluid::co2,Fluid::sco2,Fluid::air}) {
            const char* name=fluid==Fluid::water ? "Water" : fluid==Fluid::air ? "Air" : "CO2";
            auto heos_reference=make_eos_state("HEOS",name);
            for (const double pressure:{2e6,8e6}) for (const double temperature:{300.,350.}) {
                if (fluid==Fluid::sco2 && pressure<7.9e6) continue;
                heos_reference->update(CoolProp::PT_INPUTS,pressure,temperature);
                const double h=heos_reference->hmass(),cp=heos_reference->cpmass(),k=heos_reference->conductivity();
                eos.validate(fluid,temperature+1.,pressure,"other PT state");
                const auto actual=eos.evaluate_state(fluid,temperature,pressure,"PT reuse regression");
                require(std::abs(actual.enthalpy-h)<=2e-10*std::max(std::abs(h),1.)
                        && std::abs(actual.cp-cp)<=2e-10*cp
                        && std::abs(actual.conductivity-k)<=2e-10*k,
                        "guarded PT properties differ from independent HEOS");
                eos.bracket_enthalpy(fluid,temperature+2.,pressure);
                const auto transport=eos.evaluate(fluid,temperature,pressure);
                require(std::abs(transport.cp-cp)<=2e-10*cp
                        && std::abs(transport.conductivity-k)<=2e-10*k
                        && std::abs(eos.conductivity(fluid,temperature,pressure)-k)<=2e-10*k,
                        "transport properties retained another PT state");

            }
        }
        std::cout<<"conservative_energy_driver_smoke ok; cold/warm pairs="<<solved
                 <<"; max EOS h error J/kg="<<max_eos_error<<"; boundary W error="<<max_boundary_error
                 <<"; warm T error="<<max_warm_difference<<'\n';
        return 0;
    } catch (const std::exception& error) { std::cerr<<error.what()<<'\n';return 1; }
}
