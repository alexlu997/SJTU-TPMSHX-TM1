#include "tpmshx/temperature_staggered.hpp"
#include "tpmshx/conservative_energy.hpp"

#include <algorithm>
#include <cmath>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <utility>

namespace {
using namespace tpmshx;
using Values=std::vector<double>;
using Fields=std::array<Values,3>;
using Faces=Fields;
ArrayView<const double> read(const Values& x) { return {x.data(),x.size()}; }
ArrayView<double> write(Values& x) { return {x.data(),x.size()}; }
std::array<ArrayView<const double>,3> read(const Faces& x) { return {read(x[0]),read(x[1]),read(x[2])}; }
TemperatureStateView write(Fields& x) { return {write(x[0]),write(x[1]),write(x[2])}; }
void require(bool condition,const char* message) { if(!condition) throw std::runtime_error(message); }
template<class F> void reject(F&& action) {
    bool rejected=false;
    try { action(); } catch(const std::logic_error&) { rejected=true; }
    require(rejected,"invalid temperature operation was accepted");
}
bool same(double a,double b) { return a==b || (std::isnan(a)&&std::isnan(b)); }
bool same(const TemperatureResult& a,const TemperatureResult& b) {
    return a.stop==b.stop && a.iterations==b.iterations && a.residual==b.residual && same(a.q_b,b.q_b);
}
bool same(const TemperatureRunState& a,const TemperatureRunState& b) {
    return a.temperature==b.temperature && same(a.result,b.result);
}
bool same(const MacProjectionInfo& a,const MacProjectionInfo& b) {
    return a.skipped==b.skipped && a.used_bordered_lu==b.used_bordered_lu
        && a.cg_iterations==b.cg_iterations && a.rhs_mean==b.rhs_mean && a.residual_relative==b.residual_relative;
}
bool same(const StaggeredTemperatureRunState& a,const StaggeredTemperatureRunState& b) {
    return same(a.iteration,b.iteration) && a.velocity==b.velocity
        && same(a.projection[0],b.projection[0]) && same(a.projection[1],b.projection[1]);
}
bool same(const PhysicalHeatLedger& a,const PhysicalHeatLedger& b) {
    for(std::size_t p=0;p<3;++p) if(!same(a.source_integral[p],b.source_integral[p])) return false;
    return a.advective_out==b.advective_out && a.diffusive_out==b.diffusive_out && a.residual==b.residual
        && a.solved==b.solved
        && a.prescribed_b_power==b.prescribed_b_power && a.boundary_complete==b.boundary_complete;
}
bool same(const StaggeredTemperatureResult& a,const StaggeredTemperatureResult& b) {
    if(!same(a.iteration,b.iteration)) return false;
    for(std::size_t s=0;s<2;++s) {
        if(!same(a.projection[s],b.projection[s])) return false;
        const auto& x=a.residual[s];const auto& y=b.residual[s];
        if(x.available!=y.available || x.cells!=y.cells || x.sum!=y.sum || x.maximum!=y.maximum
            || x.exchange!=y.exchange || x.global_ratio!=y.global_ratio || x.cell_ratio!=y.cell_ratio) return false;
    }
    return true;
}

struct Fixture {
    Values dx{.01,.014,.009,.016},dy{.012,.009,.015},dz;
    Values k,hv,eps,cp,ks,prescribed,source,zero,u,v;
    std::array<Faces,2> velocity,capacity;
    explicit Fixture(bool three_d):dz(three_d?Values{.013,.008}:Values{.7}) {
        const auto n=dx.size()*dy.size()*dz.size();
        k.assign(n,.2);hv.resize(n);eps.assign(n,.35);cp.assign(n,1200.);ks.assign(n,5.);
        prescribed.resize(n);source.resize(n);zero.assign(n,0.);u.assign(n,.1);v.assign(n,-.08);
        for(std::size_t p=0;p<n;++p) {
            hv[p]=10000.+10.*static_cast<double>(p);
            prescribed[p]=303.+.01*static_cast<double>(p);
            source[p]=20.*std::sin(static_cast<double>(p));
        }
        const std::array<std::size_t,3> counts{dx.size(),dy.size(),dz.size()};
        for(std::size_t s=0;s<2;++s) for(std::size_t axis=0;axis<3;++axis) {
            auto extent=counts;++extent[axis];
            velocity[s][axis].assign(extent[0]*extent[1]*extent[2],s==axis?(s==0?.1:-.08):0.);
            capacity[s][axis].resize(velocity[s][axis].size());
            for(std::size_t i=0;i<extent[0];++i) for(std::size_t j=0;j<extent[1];++j)
                for(std::size_t z=0;z<extent[2];++z) {
                    const auto p=(i*extent[1]+j)*extent[2]+z;
                    const double depth=three_d?dz[std::min(z,dz.size()-1)]:1.;
                    const double area=axis==0?dy[j]*depth:axis==1?dx[i]*depth:dx[i]*dy[j];
                    capacity[s][axis][p]=.35*1200.*velocity[s][axis][p]*area;
                }
        }
        // A nonzero divergence makes restore consume the saved MAC result.
        if(three_d) velocity[0][0][dy.size()*dz.size()]+=.01;
    }
    GridView grid() const { return {dx.size(),dy.size(),dz.size(),read(dx),read(dy),read(dz)}; }
    Fields fields() const {
        Fields out{Values(hv.size()),Values(hv.size()),Values(hv.size())};
        for(std::size_t p=0;p<hv.size();++p) {
            out[0][p]=342.+.02*static_cast<double>(p);
            out[1][p]=308.-.03*static_cast<double>(p);out[2][p]=326.+.01*static_cast<double>(p);
        }
        return out;
    }
    TemperatureFluidView cell(std::size_t side,bool direct) const {
        return {read(k),read(hv),read(eps),read(cp),read(side==0?u:zero),read(side==1?v:zero),read(zero),
            {side==0?0:3,side==0?350.:300.,{},{},{}},direct?read(capacity[side]):std::array<ArrayView<const double>,3>{}};
    }
    StaggeredTemperatureFluid staggered(std::size_t side,bool sources) const {
        return {read(k),read(hv),read(eps),read(cp),read(velocity[side]),
            {side==0?0:3,side==0?350.:300.,{},{},{}},sources?read(source):ArrayView<const double>{}};
    }
};

struct Observer {
    std::size_t calls=0,cancel_on=0;
    std::vector<std::pair<std::size_t,std::size_t>> progress;
    TemperatureRun* cell=nullptr;
    StaggeredTemperatureDriver* staggered=nullptr;
    bool fail=false;
    static bool cancel(void* context) {
        auto& self=*static_cast<Observer*>(context);
        ++self.calls;return self.cancel_on && self.calls==self.cancel_on;
    }
    static void notify(void* context,std::size_t used,std::size_t budget) {
        auto& self=*static_cast<Observer*>(context);
        self.progress.emplace_back(used,budget);
        if(self.cell) {
            require(self.cell->phase()==TemperaturePhase::active,"cell callback phase");
            reject([&]{self.cell->snapshot();});reject([&]{self.cell->advance();});reject([&]{self.cell->take_result();});
        }
        if(self.staggered) {
            require(self.staggered->phase()==TemperaturePhase::active,"staggered callback phase");
            reject([&]{self.staggered->snapshot_active();});reject([&]{self.staggered->advance();});reject([&]{self.staggered->take_result();});
        }
        if(self.fail) throw std::runtime_error("test progress failure");
    }
    TemperatureControl control(bool warm,bool second=true,std::size_t budget=43) {
        return {budget,7,1e-12,.7,1.,1.,warm,second,cancel,notify,this};
    }
};
void damage(TemperatureRunState& state,int kind,const TemperatureControl& control) {
    switch(kind) {
    case 0:state.temperature[0].pop_back();break;
    case 1:state.temperature[2][0]=std::numeric_limits<double>::quiet_NaN();break;
    case 2:state.result.iterations=control.max_iterations;break;
    case 3:state.result.iterations=1;break;
    case 4:state.result.stop=TemperatureStop::converged;break;
    case 5:state.result.residual=-1.;break;
    case 6:state.result.residual=std::numeric_limits<double>::quiet_NaN();break;
    case 7:state.result.q_b=std::numeric_limits<double>::quiet_NaN();break;
    case 8:state.temperature[1][0]+=1.;break;
    default:throw std::runtime_error("unknown damage fixture");
    }
}

std::size_t cell_cuts(bool three_d,bool warm,bool rb,bool second,bool direct,bool prescribed) {
    Fixture f(three_d);auto reference=f.fields();Observer expected;
    const auto c=expected.control(warm,second);
    const auto scheme=three_d?TemperatureScheme::cell_centered_3d:TemperatureScheme::cell_centered_2d;
    const auto fixed=prescribed?read(f.prescribed):ArrayView<const double>{};
    PhysicalHeatLedger reference_audit;
    TemperatureRun continuous(scheme,f.grid(),f.cell(0,direct),f.cell(1,direct),read(f.ks),write(reference),c,fixed,rb,&reference_audit);
    expected.cell=&continuous;
    std::vector<TemperatureRunState> history;
    while(continuous.phase()==TemperaturePhase::active) {
        history.push_back(continuous.snapshot());continuous.advance();
    }
    const auto expected_result=continuous.take_result();
    reject([&]{continuous.snapshot();});reject([&]{continuous.take_result();});
    require(history.size()>3,"cell fixture does not cross enough chunks");
    for(std::size_t cut=0;cut<history.size();++cut) {
        auto fields=f.fields();Observer observed;const auto controls=observed.control(warm,second);
        TemperatureRunState saved;
        {
            TemperatureRun first(scheme,f.grid(),f.cell(0,direct),f.cell(1,direct),read(f.ks),write(fields),controls,fixed,rb);
            observed.cell=&first;
            for(std::size_t step=0;step<cut;++step) first.advance();
            saved=first.snapshot();require(same(saved,history[cut]),"cell save boundary changed");
        }
        for(auto& field:fields) std::fill(field.begin(),field.end(),std::numeric_limits<double>::quiet_NaN());
        require(same(saved,history[cut]),"cell snapshot aliases caller fields");
        PhysicalHeatLedger audit;
        TemperatureRun restored(scheme,f.grid(),f.cell(0,direct),f.cell(1,direct),read(f.ks),write(fields),controls,saved,fixed,rb,&audit);
        observed.cell=&restored;
        std::size_t step=cut;
        while(restored.phase()==TemperaturePhase::active) {
            require(same(restored.snapshot(),history.at(step++)),"cell resumed chunk differs");restored.advance();
        }
        const auto actual_result=restored.take_result();
        if(fields!=reference || !same(actual_result,expected_result) || !same(audit,reference_audit)) {
            std::cerr<<"cell case "<<three_d<<warm<<rb<<second<<direct<<prescribed<<" cut "<<cut
                <<" fields "<<(fields==reference)<<" result "<<same(actual_result,expected_result)
                <<" audit "<<same(audit,reference_audit)<<'\n';
            throw std::runtime_error("cell resumed result differs");
        }
        require(observed.calls==expected.calls && observed.progress==expected.progress,"cell resumed callbacks differ");
    }
    auto wrapper=f.fields();Observer calls;const auto controls=calls.control(warm,second);
    PhysicalHeatLedger audit;
    require(same(solve_temperature(scheme,f.grid(),f.cell(0,direct),f.cell(1,direct),read(f.ks),write(wrapper),controls,fixed,rb,&audit),expected_result)
        && wrapper==reference && same(audit,reference_audit),"cell one-shot wrapper differs");
    if(prescribed) for(int kind=0;kind<9;++kind) {
        auto invalid=history[1];damage(invalid,kind,c);auto target=f.fields();const auto before=target;
        reject([&]{TemperatureRun bad(scheme,f.grid(),f.cell(0,direct),f.cell(1,direct),read(f.ks),write(target),c,invalid,fixed,rb);});
        require(target==before,"invalid cell save wrote destination");
    }
    return history.size();
}

std::size_t staggered_cuts(bool conservative,bool rb,bool prescribed) {
    Fixture f(true);auto reference=f.fields();Observer expected;
    const auto c=expected.control(rb);const auto fixed=prescribed?read(f.prescribed):ArrayView<const double>{};
    PhysicalHeatLedger reference_audit;
    StaggeredTemperatureDriver continuous;
    continuous.start(f.grid(),f.staggered(0,true),f.staggered(1,true),read(f.ks),write(reference),c,conservative,rb,fixed,read(f.source),&reference_audit);
    expected.staggered=&continuous;
    std::vector<StaggeredTemperatureRunState> history;
    while(continuous.phase()==TemperaturePhase::active) {
        history.push_back(continuous.snapshot_active());continuous.advance();
    }
    const auto expected_result=continuous.take_result();
    require(history.size()>3,"staggered fixture does not cross enough chunks");
    require(!conservative || (!history[0].projection[0].skipped && history[0].velocity[0]!=f.velocity[0]),"MAC fixture did not project");
    reject([&]{continuous.snapshot_active();});reject([&]{continuous.take_result();});
    for(std::size_t cut=0;cut<history.size();++cut) {
        auto fields=f.fields();Observer observed;const auto controls=observed.control(rb);
        StaggeredTemperatureRunState saved;
        {
            StaggeredTemperatureDriver first;
            first.start(f.grid(),f.staggered(0,true),f.staggered(1,true),read(f.ks),write(fields),controls,conservative,rb,fixed,read(f.source));
            observed.staggered=&first;
            for(std::size_t step=0;step<cut;++step) first.advance();
            saved=first.snapshot_active();require(same(saved,history[cut]),"staggered save boundary changed");
            reject([&]{first.start(f.grid(),f.staggered(0,true),f.staggered(1,true),read(f.ks),write(fields),controls,conservative,rb);});
            reject([&]{first.project_capacity_faces(f.grid(),read(f.eps),read(f.cp),read(f.velocity[0]));});
        }
        for(auto& field:fields) std::fill(field.begin(),field.end(),std::numeric_limits<double>::quiet_NaN());
        require(same(saved,history[cut]),"staggered snapshot aliases caller fields");
        PhysicalHeatLedger audit;StaggeredTemperatureDriver restored;
        restored.restore_active(f.grid(),f.staggered(0,true),f.staggered(1,true),read(f.ks),write(fields),controls,conservative,rb,saved,fixed,read(f.source),&audit);
        observed.staggered=&restored;
        std::size_t step=cut;
        while(restored.phase()==TemperaturePhase::active) {
            require(same(restored.snapshot_active(),history.at(step++)),"staggered resumed chunk differs");restored.advance();
        }
        require(fields==reference && same(restored.take_result(),expected_result) && same(audit,reference_audit),"staggered resumed result differs");
        require(observed.calls==expected.calls && observed.progress==expected.progress,"staggered resumed callbacks differ");
    }
    auto wrapper=f.fields();Observer calls;const auto controls=calls.control(rb);PhysicalHeatLedger audit;
    require(same(continuous.solve(f.grid(),f.staggered(0,true),f.staggered(1,true),read(f.ks),write(wrapper),controls,conservative,rb,fixed,read(f.source),&audit),expected_result)
        && wrapper==reference && same(audit,reference_audit),"staggered one-shot wrapper differs");
    if(prescribed) for(int kind=0;kind<14;++kind) {
        auto invalid=history[1];
        if(kind<9) damage(invalid.iteration,kind,c);
        else if(kind==9) invalid.velocity[0][0].pop_back();
        else if(kind==10) invalid.velocity[1][1][0]=std::numeric_limits<double>::infinity();
        else if(kind==11) invalid.projection[0].rhs_mean=std::numeric_limits<double>::quiet_NaN();
        else if(kind==12) invalid.projection[0].cg_iterations=501;
        else invalid.projection[0].residual_relative=-1.;
        auto target=f.fields();const auto before=target;StaggeredTemperatureDriver bad;
        reject([&]{bad.restore_active(f.grid(),f.staggered(0,true),f.staggered(1,true),read(f.ks),write(target),c,conservative,rb,invalid,fixed,read(f.source));});
        require(target==before,"invalid staggered save wrote destination");
    }
    return history.size();
}

void termination(bool staggered) {
    Fixture f(staggered);
    for(std::size_t budget:{0U,1U,8U}) {
        auto fields=f.fields();Observer observer;auto c=observer.control(true,true,budget);
        PhysicalHeatLedger audit;audit.prescribed_b_power=123.;
        TemperatureResult result{};
        if(staggered) {
            StaggeredTemperatureDriver run;
            run.start(f.grid(),f.staggered(0,false),f.staggered(1,false),read(f.ks),write(fields),c,true,false,{},{},&audit);
            while(run.phase()==TemperaturePhase::active) run.advance();
            result=run.take_result().iteration;
        } else {
            TemperatureRun run(TemperatureScheme::cell_centered_2d,f.grid(),f.cell(0,false),f.cell(1,false),read(f.ks),write(fields),c,{},false,&audit);
            while(run.phase()==TemperaturePhase::active) run.advance();
            result=run.take_result();
        }
        require(result.iterations==budget && observer.calls==2*((budget+6)/7),"temperature budget or callback charge");
        if(!budget) require(std::isnan(result.q_b) && (staggered?audit.prescribed_b_power==0.:audit.prescribed_b_power==123.),"zero-budget audit contract");
    }
    for(std::size_t cancel_on:{1U,2U,3U,4U}) {
        auto fields=f.fields();Observer observer;observer.cancel_on=cancel_on;auto c=observer.control(false);
        PhysicalHeatLedger audit;audit.prescribed_b_power=123.;TemperatureResult result{};
        if(staggered) {
            StaggeredTemperatureDriver run;
            run.start(f.grid(),f.staggered(0,false),f.staggered(1,false),read(f.ks),write(fields),c,true,false,{},{},&audit);
            observer.staggered=&run;while(run.phase()==TemperaturePhase::active) run.advance();
            require(run.phase()==TemperaturePhase::cancelled,"staggered cancel phase");
            reject([&]{run.snapshot_active();});result=run.take_result().iteration;
        } else {
            TemperatureRun run(TemperatureScheme::cell_centered_2d,f.grid(),f.cell(0,false),f.cell(1,false),read(f.ks),write(fields),c,{},false,&audit);
            observer.cell=&run;while(run.phase()==TemperaturePhase::active) run.advance();
            require(run.phase()==TemperaturePhase::cancelled,"cell cancel phase");
            reject([&]{run.snapshot();});result=run.take_result();
        }
        require(result.stop==TemperatureStop::cancelled && result.iterations==7*(cancel_on/2)
            && observer.calls==cancel_on && audit.prescribed_b_power==123.,"cancel budget or audit contract");
        require(staggered&&cancel_on==3?std::isfinite(result.q_b):std::isnan(result.q_b),"cancel duty contract");
    }
    auto fields=f.fields();Observer observer;observer.fail=true;auto c=observer.control(false);bool failed=false;
    if(staggered) {
        StaggeredTemperatureDriver run;
        run.start(f.grid(),f.staggered(0,false),f.staggered(1,false),read(f.ks),write(fields),c,true,false);
        try { run.advance(); } catch(const std::runtime_error&) { failed=true; }
        require(run.phase()==TemperaturePhase::failed,"staggered failure phase");
        reject([&]{run.advance();});reject([&]{run.snapshot_active();});reject([&]{run.take_result();});
    } else {
        TemperatureRun run(TemperatureScheme::cell_centered_2d,f.grid(),f.cell(0,false),f.cell(1,false),read(f.ks),write(fields),c);
        try { run.advance(); } catch(const std::runtime_error&) { failed=true; }
        require(run.phase()==TemperaturePhase::failed,"cell failure phase");
        reject([&]{run.advance();});reject([&]{run.snapshot();});reject([&]{run.take_result();});
    }
    require(failed,"callback exception was suppressed");
}

void initial_and_converged(bool staggered) {
    Fixture f(staggered);auto fields=f.fields();Observer observer;auto c=observer.control(false);
    if(staggered) {
        auto a=f.staggered(0,false),b=f.staggered(1,false);
        a.boundary.inlet_temperature=b.boundary.inlet_temperature=330.;
        StaggeredTemperatureDriver run;
        run.start(f.grid(),a,b,read(f.ks),write(fields),c,true,false);
        auto initial=run.snapshot_active();
        for(int kind=0;kind<3;++kind) {
            auto invalid=initial;auto target=f.fields();const auto before=target;
            if(kind==0) invalid.iteration.result.q_b=0.;
            else if(kind==1) invalid.iteration.result.residual=1.;
            else { invalid.projection[0].skipped=true;invalid.projection[0].used_bordered_lu=true; }
            StaggeredTemperatureDriver bad;
            reject([&]{bad.restore_active(f.grid(),a,b,read(f.ks),write(target),c,true,false,invalid);});
            require(target==before,"invalid initial staggered state wrote destination");
        }
        StaggeredTemperatureDriver alias;
        reject([&]{alias.restore_active(f.grid(),a,b,read(f.ks),write(initial.iteration.temperature),c,true,false,initial);});
        require(same(initial,run.snapshot_active()),"staggered restore changed its saved input");
        run.advance();const auto saved=run.snapshot_active();
        while(run.phase()==TemperaturePhase::active) run.advance();
        const auto expected=run.take_result();const auto reference=fields;
        require(expected.iteration.stop==TemperatureStop::converged,"staggered equilibrium did not converge");
        StaggeredTemperatureDriver restored;
        restored.restore_active(f.grid(),a,b,read(f.ks),write(fields),c,true,false,saved);
        while(restored.phase()==TemperaturePhase::active) restored.advance();
        require(fields==reference && same(restored.take_result(),expected),"staggered restored convergence differs");
    } else {
        auto a=f.cell(0,false),b=f.cell(1,false);
        a.boundary.inlet_temperature=b.boundary.inlet_temperature=330.;
        TemperatureRun run(TemperatureScheme::cell_centered_2d,f.grid(),a,b,read(f.ks),write(fields),c);
        auto initial=run.snapshot();
        for(int kind=0;kind<2;++kind) {
            auto invalid=initial;auto target=f.fields();const auto before=target;
            if(kind==0) invalid.result.q_b=0.;else invalid.result.residual=1.;
            reject([&]{TemperatureRun bad(TemperatureScheme::cell_centered_2d,f.grid(),a,b,read(f.ks),write(target),c,invalid);});
            require(target==before,"invalid initial cell state wrote destination");
        }
        reject([&]{TemperatureRun bad(TemperatureScheme::cell_centered_2d,f.grid(),a,b,read(f.ks),write(initial.temperature),c,initial);});
        require(same(initial,run.snapshot()),"cell restore changed its saved input");
        run.advance();const auto saved=run.snapshot();
        while(run.phase()==TemperaturePhase::active) run.advance();
        const auto expected=run.take_result();const auto reference=fields;
        require(expected.stop==TemperatureStop::converged,"cell equilibrium did not converge");
        TemperatureRun restored(TemperatureScheme::cell_centered_2d,f.grid(),a,b,read(f.ks),write(fields),c,saved);
        while(restored.phase()==TemperaturePhase::active) restored.advance();
        require(fields==reference && same(restored.take_result(),expected),"cell restored convergence differs");
    }
}
}  // namespace

int main() {
    try {
        std::size_t cell=0,staggered=0;
        for(bool warm:{false,true}) {
            cell+=cell_cuts(false,warm,false,false,false,false);
            cell+=cell_cuts(false,warm,false,true,true,false);
            cell+=cell_cuts(false,warm,true,true,true,true);
            cell+=cell_cuts(true,warm,false,true,false,false);
            cell+=cell_cuts(true,warm,false,true,true,true);
        }
        for(bool conservative:{false,true}) for(bool rb:{false,true})
            staggered+=staggered_cuts(conservative,rb,rb);
        termination(false);termination(true);
        initial_and_converged(false);initial_and_converged(true);
        std::cout<<"temperature restore: "<<cell<<" cell boundaries, "<<staggered
            <<" staggered boundaries; invalid saves, cancellation, budgets and callbacks passed\n";
        return 0;
    } catch(const std::exception& error) { std::cerr<<error.what()<<'\n';return 1; }
}
