#include "../src/model_h_common.hpp"
#include <array>
#include <cstdio>
#include <stdexcept>

namespace {
using namespace tpmshx;
using namespace tpmshx::model_h_common;

void require(bool condition,const char* message) {
    if(!condition)throw std::runtime_error(message);
}
template<class Error,class Action> void rejects(Action action) {
    bool rejected=false;
    try {action();} catch(const Error&) {rejected=true;}
    require(rejected,"invalid chunk operation was accepted");
}
struct Fixture {
    std::array<double,3> temperature{5.,7.,3.};
    double residual=99.;
    std::size_t sweeps=0,calls=0,proposals=0,accepted=0,fail_at=0;
    bool reject=false;
    std::vector<double> returned;
    TemperatureStateView fields() {
        return {{&temperature[0],1},{&temperature[1],1},{&temperature[2],1}};
    }
    double step(std::size_t count) {
        if(++calls==fail_at) {
            temperature[0]+=1.;
            throw std::runtime_error("incomplete numerical step");
        }
        const double target[]{1.,2.,4.},factor[]{.93,.91,.89};
        double change=0.;
        for(std::size_t i=0;i<count;++i) {
            change=0.;
            for(std::size_t side=0;side<3;++side) {
                const double previous=temperature[side];
                temperature[side]=target[side]+factor[side]*(previous-target[side]);
                change=std::max(change,std::abs(temperature[side]-previous));
            }
        }
        sweeps+=count;returned.push_back(change);return change;
    }
    void advance(AcceleratedChunk& chunk) {
        const auto trial=[&](Eigen::VectorXd& picard,const Eigen::VectorXd& candidate) {
            ++proposals;
            const double ordinary=step(1);
            picard=pack(fields());restore(fields(),candidate);
            const double proposed=step(1);
            if(!reject && std::isfinite(proposed) && proposed<=ordinary) {
                ++accepted;return proposed;
            }
            restore(fields(),picard);return ordinary;
        };
        chunk.advance(fields(),true,[&](std::size_t count){return step(count);},trial,residual);
    }
};
}

int main() {
    for(const auto policy:{std::array<std::size_t,2>{25,6},std::array<std::size_t,2>{5,16}})
    for(bool reject:{false,true}) for(std::size_t budget:{0U,1U,4U,5U,6U,7U,24U,25U,26U,27U,50U,51U,52U,77U,130U}) {
        Fixture expected;expected.reject=reject;
        AcceleratedChunk continuous(budget,policy[0],policy[1]);
        while(!continuous.complete())expected.advance(continuous);
        require(expected.sweeps==budget,"chunk exceeded its sweep budget");
        if(budget==130)require(expected.proposals>0 && (reject?expected.accepted==0:expected.accepted>0),
                              "chunk fixture omitted proposal acceptance or rejection");
        for(std::size_t cut=0;cut<20;++cut) {
            Fixture actual;actual.reject=reject;
            AcceleratedChunk initial(budget,policy[0],policy[1]);
            for(std::size_t i=0;i<cut && !initial.complete();++i)actual.advance(initial);
            auto state=initial.snapshot();
            AcceleratedChunk resumed(budget,3,state,policy[0],policy[1]);
            if(!state.acceleration.x.empty()) {
                state.acceleration.x[0][0]+=100.;
                require(initial.snapshot().acceleration.x!=state.acceleration.x,
                        "saved chunk history aliases the owner");
            }
            while(!resumed.complete())actual.advance(resumed);
            require(actual.temperature==expected.temperature && actual.residual==expected.residual
                && actual.sweeps==expected.sweeps && actual.calls==expected.calls
                && actual.proposals==expected.proposals && actual.accepted==expected.accepted
                && actual.returned==expected.returned,"resumed chunk changed its numerical sequence");
            actual.advance(resumed);
            require(actual.sweeps==budget,"completed chunk advanced again");
        }
    }
    Fixture source;AcceleratedChunk owner(130);source.advance(owner);
    const auto saved=owner.snapshot();
    for(int damage=0;damage<9;++damage) {
        auto state=saved;
        switch(damage) {
        case 0:++state.count;break;
        case 1:state.completed=131;break;
        case 2:state.acceleration.history_limit=7;break;
        case 3:state.acceleration.condition_limit=std::numeric_limits<double>::quiet_NaN();break;
        case 4:state.acceleration.x[0].pop_back();break;
        case 5:state.acceleration.r[0][0]=std::numeric_limits<double>::infinity();break;
        case 6:state.completed=0;break;
        case 7:state.acceleration.x.clear();state.acceleration.r.clear();break;
        case 8:state.sweep_block=5;break;
        }
        rejects<std::invalid_argument>([&]{AcceleratedChunk invalid(130,3,state);});
    }
    rejects<std::invalid_argument>([&]{AcceleratedChunk invalid(130,4,saved);});
    rejects<std::invalid_argument>([]{AcceleratedChunk invalid(130,0,6);});
    rejects<std::invalid_argument>([]{AcceleratedChunk invalid(130,5,1);});
    for(std::size_t fail_at:{1U,4U}) {
        Fixture failed;failed.fail_at=fail_at;
        AcceleratedChunk chunk(130);
        rejects<std::runtime_error>([&]{while(!chunk.complete())failed.advance(chunk);});
        require(failed.residual==(fail_at==1?99.:failed.returned[1]),
                "partial proposal changed the published residual");
        rejects<std::logic_error>([&]{chunk.snapshot();});
        rejects<std::logic_error>([&]{failed.advance(chunk);});
    }
    std::puts("model-h chunk: budgets, proposals, exact continuation, invalid state and failed boundaries passed");
}
