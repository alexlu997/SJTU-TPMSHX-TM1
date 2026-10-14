#include "tpmshx/simple_2d.hpp"
#include "tpmshx/simple_3d.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <iostream>
#include <limits>
#include <memory>
#include <stdexcept>
#include <type_traits>
#include <vector>

namespace {
using namespace tpmshx;
void require(bool value,const char* message) { if(!value)throw std::runtime_error(message); }
template<class Error,class Call> void rejects(Call call) {
    try { call(); } catch(const Error&) { return; }
    throw std::runtime_error("invalid SIMPLE operation was accepted");
}
template<class T> ArrayView<T> view(std::vector<T>& x) { return {x.data(),x.size()}; }
template<class T> ArrayView<const T> read(const std::vector<T>& x) { return {x.data(),x.size()}; }
bool same(double a,double b) { return a==b || (std::isnan(a) && std::isnan(b)); }
void momentum(const SimpleMomentumResidual& a,const SimpleMomentumResidual& b) {
    require(a.numerator==b.numerator && a.denominator==b.denominator && a.component==b.component
        && same(a.maximum,b.maximum),"SIMPLE momentum changed after restore");
}
void history(const SimpleHistory& a,const SimpleHistory& b) {
    require(a.legacy==b.legacy && a.local_mass==b.local_mass && a.global_mass==b.global_mass
        && a.momentum.size()==b.momentum.size(),"SIMPLE history changed after restore");
    for(std::size_t i=0;i<a.momentum.size();++i) {
        require(a.momentum[i].iteration==b.momentum[i].iteration,"SIMPLE momentum schedule changed");
        momentum(a.momentum[i].residual,b.momentum[i].residual);
    }
}
void pressure(const PressureResult& a,const PressureResult& b) {
    require(a.success==b.success && a.method==b.method && a.exit==b.exit && a.amg_exit==b.amg_exit
        && a.rebuild_reason==b.rebuild_reason && a.detail==b.detail && a.x==b.x
        && a.iterations==b.iterations && a.rebuild_count==b.rebuild_count
        && a.hierarchy_bytes==b.hierarchy_bytes && a.superlu_info==b.superlu_info,
        "SIMPLE pressure state or rebuild schedule changed");
    const double x[]{a.rhs_scale,a.relative_residual,a.absolute_residual,a.iterative_relative_residual,a.pin_max_abs,a.diagonal_drift};
    const double y[]{b.rhs_scale,b.relative_residual,b.absolute_residual,b.iterative_relative_residual,b.pin_max_abs,b.diagonal_drift};
    for(std::size_t i=0;i<6;++i)require(same(x[i],y[i]),"SIMPLE pressure residual changed");
}
template<class Result> void result(const Result& a,const Result& b) {
    require(a.stop==b.stop && a.converged==b.converged && a.post_closure_measured==b.post_closure_measured
        && a.post_closure_certified==b.post_closure_certified && a.iterations==b.iterations
        && a.pressure_clip_hits==b.pressure_clip_hits && same(a.legacy_residual,b.legacy_residual),
        "SIMPLE stop, budget or clip evidence changed");
    if constexpr(std::is_same_v<Result,Simple3DResult>)
        require(a.post_closure_rejections==b.post_closure_rejections && a.legacy_reference==b.legacy_reference,
            "SIMPLE closure rejection state changed");
    const double x[]{a.mass.local_residual,a.mass.mass_in,a.mass.mass_out,a.mass.global_residual,a.mass.backflow_fraction};
    const double y[]{b.mass.local_residual,b.mass.mass_in,b.mass.mass_out,b.mass.global_residual,b.mass.backflow_fraction};
    for(std::size_t i=0;i<5;++i)require(same(x[i],y[i]),"SIMPLE mass audit changed");
    require(a.mass.counted_cells==b.mass.counted_cells,"SIMPLE mass audit coverage changed");
    momentum(a.momentum,b.momentum);pressure(a.linear,b.linear);
}
struct Callbacks {
    std::size_t calls=0,stop_at=std::numeric_limits<std::size_t>::max();
    std::vector<std::pair<std::size_t,double>> progress;
};
bool cancel(void* context) { auto& c=*static_cast<Callbacks*>(context);return ++c.calls>=c.stop_at; }
void progress(void* context,std::size_t i,double r) { static_cast<Callbacks*>(context)->progress.emplace_back(i,r); }

template<int dimension> struct Fixture {
    using Solver=std::conditional_t<dimension==2,Simple2DSolver,Simple3DSolver>;
    using Control=std::conditional_t<dimension==2,Simple2DControl,Simple3DControl>;
    std::size_t nx,ny,nz;
    bool ideal;
    int option;
    std::array<std::vector<double>,3> widths;
    std::array<std::vector<double>,6> material_fields;
    std::array<std::vector<double>,dimension==2?8:10> fields;
    std::vector<unsigned char> outlet;
    std::vector<double> inlet_fraction,outlet_u,outlet_w;
    Callbacks callbacks;
    Fixture(bool gas,int method,bool large=false):nx(large?13:dimension==2?3:4),ny(large?12:dimension==2?8:5),
        nz(dimension==2?1:large?14:3),ideal(gas),option(method) {
        const auto n=nx*ny*nz;const double velocity=ideal?.7:.005,mu=ideal?1.8e-5:.001;
        widths={std::vector<double>(nx,.009),std::vector<double>(ny,.008),std::vector<double>(nz,dimension==2?1.:.007)};
        material_fields={std::vector<double>(n,.6),std::vector<double>(n,mu),std::vector<double>(n,mu/.6),
            std::vector<double>(n,1e-7),std::vector<double>(n,35.),std::vector<double>(n,300.)};
        fields[0].resize((nx+1)*ny*nz);fields[1].assign(nx*(ny+1)*nz,velocity);
        if constexpr(dimension==2) {
            fields[2].resize(n);fields[3].resize(n);fields[4].resize(fields[0].size());fields[5].resize(fields[1].size());
            fields[6].assign(n,ideal?1.2:1000.);fields[7].assign(nx,velocity);
        } else {
            fields[2].resize(nx*ny*(nz+1));fields[3].resize(n);fields[4].resize(n);
            fields[5].resize(fields[0].size());fields[6].resize(fields[1].size());fields[7].resize(fields[2].size());
            fields[8].assign(n,ideal?1.2:1000.);fields[9].assign(nx*nz,velocity);
        }
        fields[dimension==2?3:4].assign(n,std::numeric_limits<double>::quiet_NaN());
        outlet.assign(nx*nz,1);inlet_fraction.assign(nx,1.);outlet_u.assign((nx+1)*nz,1.);outlet_w.assign(nx*(nz+1),1.);
    }
    GridView grid() const { return {nx,ny,nz,read(widths[0]),read(widths[1]),read(widths[2])}; }
    auto material() const {
        if constexpr(dimension==2)return Simple2DMaterialView{read(material_fields[0]),read(material_fields[1]),read(material_fields[2]),read(material_fields[3]),read(material_fields[4]),read(material_fields[5])};
        else return Simple3DMaterialView{read(material_fields[0]),read(material_fields[1]),read(material_fields[2]),read(material_fields[3]),read(material_fields[4]),read(material_fields[5])};
    }
    auto boundary() const {
        if constexpr(dimension==2)return Simple2DBoundaryView{read(inlet_fraction),read(outlet_u),ideal?.7:.005,1.,ideal?std::optional<double>{}:1000.};
        else return Simple3DBoundaryView{read(outlet_u),read(outlet_w)};
    }
    auto state() {
        if constexpr(dimension==2)return Simple2DStateView{view(fields[0]),view(fields[1]),view(fields[2]),view(fields[3]),view(fields[4]),view(fields[5]),view(fields[6]),view(fields[7])};
        else return Simple3DStateView{view(fields[0]),view(fields[1]),view(fields[2]),view(fields[3]),view(fields[4]),view(fields[5]),view(fields[6]),view(fields[7]),view(fields[8]),view(fields[9])};
    }
    Control control(std::size_t budget=45) {
        Control c{};c.max_iterations=budget;c.inner_sweeps=1;c.alpha_velocity=dimension==2?.7:.5;
        c.alpha_pressure=dimension==2?.3:.2;c.alpha_density=.3;c.pressure_reference_absolute=101325.;c.gas_constant=287.05;
        c.ideal_gas=ideal;c.convergence={1e-4,1e-6,1e-6,.01,1e-4,1e-3,2,5,60};
        c.cancel=cancel;c.progress=progress;c.context=&callbacks;
        if constexpr(dimension==2)c.close_outlet_on_exit=option==0;
        else { c.pressure_rebuild_every=7;c.pressure_diagonal_drift=.05;c.track_momentum=option!=1;
            c.ordering=option==1?Simple3DOrdering::red_black:Simple3DOrdering::natural;c.second_order_upwind=option==2; }
        return c;
    }
    auto owner() const { return std::make_unique<Solver>(grid(),read(outlet)); }
};
template<int d> void fields(const Fixture<d>& a,const Fixture<d>& b) {
    for(std::size_t i=0;i<a.fields.size();++i) {
        require(a.fields[i].size()==b.fields[i].size(),"SIMPLE field extent changed");
        for(std::size_t j=0;j<a.fields[i].size();++j)require(same(a.fields[i][j],b.fields[i][j]),"SIMPLE field changed after restore");
    }
}

template<int d> void continuation() {
    std::size_t cuts=0;bool confirmation_seen=false;
    for(bool ideal:{false,true})for(bool warm:{false,true})for(int option=0;option<(d==2?2:3);++option) {
        Fixture<d> seed(ideal,option);auto seeded=seed.owner();
        if(warm)seeded->solve(seed.material(),seed.boundary(),seed.state(),seed.control(600));
        const auto saved_owner=seeded->snapshot();
        Fixture<d> expected(ideal,option);expected.fields=seed.fields;auto baseline=expected.owner();baseline->restore(saved_owner);
        const auto answer=baseline->solve(expected.material(),expected.boundary(),expected.state(),expected.control());
        for(std::size_t cut:{0U,1U,9U,10U,19U,20U,44U}) {
            Fixture<d> actual(ideal,option);actual.fields=seed.fields;auto run=actual.owner();run->restore(saved_owner);
            run->start(actual.material(),actual.boundary(),actual.state(),actual.control());
            for(std::size_t i=0;i<cut && run->phase()==SimplePhase::active;++i)run->advance();
            if(run->phase()==SimplePhase::active) {
                auto saved=run->snapshot_active();confirmation_seen=confirmation_seen || saved.convergence.streak>0;
                saved.fields[0][0]+=1.;require(saved.fields[0]!=run->snapshot_active().fields[0],"SIMPLE snapshot aliases fields");
                saved=run->snapshot_active();run.reset();run=actual.owner();
                for(auto& field:actual.fields)std::fill(field.begin(),field.end(),std::numeric_limits<double>::quiet_NaN());
                run->restore_active(actual.material(),actual.boundary(),actual.state(),actual.control(),saved);
                saved.fields[0][0]+=1.;require(saved.fields[0]!=run->snapshot_active().fields[0],"SIMPLE restore borrows fields");
                ++cuts;
            }
            while(run->phase()==SimplePhase::active)run->advance();
            fields(actual,expected);result(run->take_result(),answer);history(run->history(),baseline->history());
            require(actual.callbacks.calls==expected.callbacks.calls && actual.callbacks.progress==expected.callbacks.progress,
                "SIMPLE callback sequence changed after restore");
            require(run->massflux_target()==baseline->massflux_target(),"SIMPLE inlet target changed");
            rejects<std::logic_error>([&]{run->snapshot_active();});rejects<std::logic_error>([&]{run->take_result();});
        }
    }
    require(confirmation_seen,"SIMPLE continuation did not cover an active F2 confirmation");
    std::cout<<d<<"D exact SIMPLE continuation cuts="<<cuts<<'\n';
}
void hierarchy() {
    Fixture<3> expected(true,0,true);auto baseline=expected.owner();auto c=expected.control(5);c.pressure_rebuild_every=3;
    const auto answer=baseline->solve(expected.material(),expected.boundary(),expected.state(),c);
    for(std::size_t cut:{1U,2U,4U}) {
        Fixture<3> actual(true,0,true);auto run=actual.owner();auto options=actual.control(5);options.pressure_rebuild_every=3;
        run->start(actual.material(),actual.boundary(),actual.state(),options);
        for(std::size_t i=0;i<cut;++i)require(run->advance()==SimplePhase::active,"large SIMPLE fixture ended too soon");
        const auto saved=run->snapshot_active();require(saved.owner.pressure.construction.has_value(),"large SIMPLE fixture did not use AMG");
        run.reset();run=actual.owner();run->restore_active(actual.material(),actual.boundary(),actual.state(),options,saved);
        while(run->phase()==SimplePhase::active)run->advance();
        fields(actual,expected);result(run->take_result(),answer);history(run->history(),baseline->history());
    }
}
template<int d> void boundaries() {
    Fixture<d> sample(true,0);auto owner=sample.owner();owner->start(sample.material(),sample.boundary(),sample.state(),sample.control());
    owner->advance();owner->advance();const auto saved=owner->snapshot_active();
    for(int damage=0;damage<13;++damage) {
        auto broken=saved;
        switch(damage) {
        case 0:broken.fields[0].pop_back();break;
        case 1:broken.fields[0][0]=std::numeric_limits<double>::infinity();break;
        case 2:broken.fields[d==2?6:8][0]=0.;break;
        case 3:broken.result.iterations=45;break;
        case 4:broken.result.stop=SimpleStop::tol;break;
        case 5:broken.convergence.previous[0].pop_back();break;
        case 6:broken.convergence.streak=2;break;
        case 7:++broken.result.pressure_clip_hits;break;
        case 8:broken.owner.history.legacy.pop_back();break;
        case 9:broken.convergence.window_start_iteration=3;break;
        case 10:broken.owner.widths[0][0]*=2.;break;
        case 11:broken.fields[d==2?3:4][0]=std::numeric_limits<double>::quiet_NaN();break;
        case 12:
            if constexpr(d==2)broken.owner.depth*=2.;
            else broken.owner.widths[2][0]*=2.;
            break;
        }
        Fixture<d> target(true,0),unchanged(true,0);auto destination=target.owner();
        rejects<std::invalid_argument>([&]{destination->restore_active(target.material(),target.boundary(),target.state(),target.control(),broken);});
        fields(target,unchanged);require(destination->history().legacy.empty(),"invalid SIMPLE restore changed owner history");
    }
    for(std::size_t stop_at:{1U,3U,12U,27U}) {
        Fixture<d> expected(true,0),actual(true,0);expected.callbacks.stop_at=actual.callbacks.stop_at=stop_at;
        auto baseline=expected.owner(),run=actual.owner();
        const auto answer=baseline->solve(expected.material(),expected.boundary(),expected.state(),expected.control());
        run->start(actual.material(),actual.boundary(),actual.state(),actual.control());
        while(run->phase()==SimplePhase::active) {
            run->advance();
            if(run->phase()==SimplePhase::active) {
                const auto state=run->snapshot_active();run.reset();run=actual.owner();
                run->restore_active(actual.material(),actual.boundary(),actual.state(),actual.control(),state);
            }
        }
        require(run->phase()==SimplePhase::cancelled,"cancelled SIMPLE fixture completed");
        result(run->take_result(),answer);fields(actual,expected);history(run->history(),baseline->history());
        require(actual.callbacks.calls==expected.callbacks.calls,"SIMPLE cancellation call count changed");
        rejects<std::logic_error>([&]{run->snapshot_active();});
    }
    Fixture<d> observed(true,0);auto run=observed.owner();auto options=observed.control(3);
    struct Observer { typename Fixture<d>::Solver* run;std::size_t calls=0,cancel_calls=0; } observer{run.get()};
    options.context=&observer;
    options.cancel=[](void* context) {
        auto& current=*static_cast<Observer*>(context);++current.cancel_calls;
        require(current.run->phase()==SimplePhase::active,"SIMPLE callback sees an incorrect phase");
        rejects<std::logic_error>([&]{current.run->snapshot_active();});
        rejects<std::logic_error>([&]{current.run->advance();});
        return false;
    };
    options.progress=[](void* context,std::size_t,double) {
        auto& current=*static_cast<Observer*>(context);++current.calls;
        rejects<std::logic_error>([&]{current.run->snapshot_active();});
        rejects<std::logic_error>([&]{current.run->snapshot();});
        rejects<std::logic_error>([&]{current.run->advance();});
    };
    run->solve(observed.material(),observed.boundary(),observed.state(),options);
    require(observer.calls==1 && observer.cancel_calls==(d==2?3:4),"SIMPLE callbacks omitted the boundary test");
    Fixture<d> failed(true,0);auto broken=failed.owner();auto failure=failed.control();failure.progress=nullptr;
    failure.cancel=[](void*)->bool { throw std::runtime_error("failed SIMPLE callback"); };
    rejects<std::runtime_error>([&]{broken->solve(failed.material(),failed.boundary(),failed.state(),failure);});
    require(broken->phase()==SimplePhase::failed,"failed SIMPLE call remained active");
    rejects<std::logic_error>([&]{broken->snapshot_active();});rejects<std::logic_error>([&]{broken->advance();});
}
}
int main() {
    try { continuation<2>();continuation<3>();hierarchy();boundaries<2>();boundaries<3>();
        std::cout<<"SIMPLE state ownership, F2, pressure cadence, cancellation and invalid boundaries passed\n";return 0; }
    catch(const std::exception& e) { std::cerr<<e.what()<<'\n';return 1; }
}
