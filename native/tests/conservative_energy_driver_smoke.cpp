#include "tpmshx/enthalpy_driver.hpp"

#include <Exceptions.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <iostream>
#include <limits>
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
            view(mass[s][0]),view(mass[s][1]),view(mass[s][2]),direction[s]};
    }
    EnthalpyStateView state(bool warm=false) {
        return {output(h[0]),output(h[1]),output(t[0]),output(t[1]),output(solid),warm,warm,warm};
    }
    double boundary_power(std::size_t s,double hin,bool sou) const {
        const bool positive=direction[s]%2==0;
        const std::size_t p=positive?4:0,q=positive?3:1;
        double hout=h[s][p];
        if (sou) hout+=(h[s][p]-h[s][q])*width[axis][p]/(width[axis][p]+width[axis][q]);
        return .005*(hin-hout);
    }
};
EnthalpyControl controls(bool sou) {
    EnthalpyControl c{1200,5,sou?.2:.6,2e-12,1e-7,1e-7,""};
    c.algorithm=sou?EnthalpyAlgorithm::temperature_sou:EnthalpyAlgorithm::temperature_fou;
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
}  // namespace

int main() {
    try {
        std::size_t solved=0;
        double max_eos_error=0.,max_boundary_error=0.,max_warm_difference=0.;
        const std::array<std::array<Fluid,2>,4> pairs{{{Fluid::air,Fluid::air},
            {Fluid::air,Fluid::water},{Fluid::water,Fluid::air},{Fluid::sco2,Fluid::sco2}}};
        for (const auto& pair:pairs) for (std::size_t axis=0;axis<3;++axis)
            for (int sign:{1,-1}) for (bool sou:{false,true}) {
                Case data(axis,sign,pair[0],pair[1]);auto c=controls(sou);
                const auto result=solve_enthalpy(data.grid(),data.side(0),data.side(1),view(data.solid_k),data.state(),c);
                require(result.stop==EnthalpyStop::converged && result.final_audit && result.temperature_update,
                        "T energy solve did not converge with actual evidence");
                require(result.algorithm==c.algorithm && !result.used_bicubic[0] && !result.used_bicubic[1]
                        && !result.heos_polish && !result.total_clips.a && !result.total_clips.b,
                        "T energy algorithm identity is not the executed method");
                require(result.picard_relaxation==(sou?.6:1.),"actual Picard relaxation evidence is missing");
                require(*result.temperature_update<=1e-8 && result.final_audit->equation_ratio<=1e-7
                        && result.final_audit->coupled_ratio<=1e-7,"T energy gate was bypassed");
                EnthalpyEOS independent;
                for (std::size_t s=0;s<2;++s) for (std::size_t p=0;p<5;++p) {
                    const double inverted=independent.temperature(data.fluid[s],data.h[s][p],data.pressure[s][p],false,"smoke HP reference");
                    max_eos_error=std::max(max_eos_error,std::abs(inverted-data.t[s][p]));
                }
                max_boundary_error=std::max({max_boundary_error,
                    std::abs(result.q_a-data.boundary_power(0,result.inlet_enthalpy[0],sou)),
                    std::abs(result.q_b-data.boundary_power(1,result.inlet_enthalpy[1],sou))});
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
        for(bool sou:{false,true}) {
            Case loose(0,1,Fluid::air,Fluid::water);auto gate=controls(sou);
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
            Case data(0,1,Fluid::air,Fluid::water);auto c=controls(true);
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
            Case data(0,1,Fluid::air,Fluid::water);auto c=controls(true);c.max_iterations=6;
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
            Case data(0,1,Fluid::air,Fluid::water);auto c=controls(true);c.max_iterations=3;
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
            Case data(0,1,Fluid::air,Fluid::water);auto c=controls(true);c.max_iterations=3;
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
            auto c=controls(true);c.temperature_update_tolerance=1e-30;c.max_iterations=2;
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
        for(std::size_t axis:{0u,1u}) for(int sign:{1,-1}) for(bool sou:{false,true}) {
            Case unit(axis,sign,Fluid::water,Fluid::sco2);
            unit.width[2][0]=1.;
            auto slab=unit;
            constexpr double thickness=.037;
            slab.width[2][0]=thickness;
            for(auto& side:slab.mass)for(auto& component:side)
                for(double& value:component)value*=thickness;
            const auto c=controls(sou);
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

        Case reference(0,1,Fluid::air,Fluid::water);auto t_control=controls(false);
        const auto t_result=solve_enthalpy(reference.grid(),reference.side(0),reference.side(1),view(reference.solid_k),reference.state(),t_control);
        auto legacy=reference;auto h_control=t_control;h_control.algorithm=EnthalpyAlgorithm::legacy_h_fou;
        const auto h_result=solve_enthalpy(legacy.grid(),legacy.side(0),legacy.side(1),view(legacy.solid_k),legacy.state(),h_control);
        require(t_result.stop==EnthalpyStop::converged && h_result.stop==EnthalpyStop::converged
                && h_result.algorithm==EnthalpyAlgorithm::legacy_h_fou && !h_result.temperature_update,
                "legacy default identity changed");
        for (std::size_t p=0;p<5;++p) {
            for (std::size_t s=0;s<2;++s) require(std::abs(reference.t[s][p]-legacy.t[s][p])<=1e-6,"FOU T/H converged states differ");
            require(std::abs(reference.solid[p]-legacy.solid[p])<=1e-6,"FOU solid state differs from legacy H");
        }

        for (int stop_at:{1,3,4}) {
            Case data(0,1,Fluid::air,Fluid::water);auto c=controls(true);Cancellation token{0,stop_at};
            c.cancel=cancel;c.context=&token;
            const auto result=solve_enthalpy(data.grid(),data.side(0),data.side(1),view(data.solid_k),data.state(),c);
            require(result.stop==EnthalpyStop::cancelled && !result.final_audit,"cancelled T solve published a final certificate");
        }
        Case limited(0,1,Fluid::air,Fluid::water);auto limit=controls(true);limit.max_iterations=1;
        const auto stopped=solve_enthalpy(limited.grid(),limited.side(0),limited.side(1),view(limited.solid_k),limited.state(),limit);
        require(stopped.stop==EnthalpyStop::iteration_limit && stopped.iterations==1 && stopped.final_audit
                && stopped.temperature_update && !stopped.total_clips.a && !stopped.total_clips.b,
                "T energy budget exit lost its actual evidence");
        Case unknown(0,1,Fluid::air,Fluid::water);unknown.mass[0][0].back()=-.001;
        auto c=controls(false);
        rejects<std::invalid_argument>([&] { solve_enthalpy(unknown.grid(),unknown.side(0),unknown.side(1),view(unknown.solid_k),unknown.state(),c); },
                                       "undefined exterior inflow was accepted");
        Case invalid(0,1,Fluid::air,Fluid::water);
        c.equation_energy_tolerance.reset();
        rejects<std::invalid_argument>([&] { solve_enthalpy(invalid.grid(),invalid.side(0),invalid.side(1),view(invalid.solid_k),invalid.state(),c); },
                                       "T energy accepted a missing actual equation gate");
        EnthalpyEOS eos;
        for (double bad_t:{270.,500.,std::numeric_limits<double>::quiet_NaN()})
            rejects<WaterStateError>([&] { eos.evaluate_state(Fluid::water,bad_t,2e5,"PT guard regression"); },"actual PT water guard was bypassed");
        rejects<std::invalid_argument>([&] { eos.evaluate_state(Fluid::sco2,300.,7e6,"PT guard regression"); },"actual PT CO2 domain was bypassed");
        std::cout<<"conservative_energy_driver_smoke ok; cold/warm pairs="<<solved
                 <<"; max EOS T error="<<max_eos_error<<"; boundary W error="<<max_boundary_error
                 <<"; warm T error="<<max_warm_difference<<'\n';
        return 0;
    } catch (const std::exception& error) { std::cerr<<error.what()<<'\n';return 1; }
}
