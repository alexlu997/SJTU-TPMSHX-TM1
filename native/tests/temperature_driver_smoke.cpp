#include "tpmshx/temperature_driver.hpp"
#include "tpmshx/conservative_energy.hpp"
#include "../src/temperature_faces.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdio>
#include <limits>
#include <stdexcept>
#include <vector>

namespace {
using namespace tpmshx;
using Values = std::vector<double>;
using Faces = std::array<Values,3>;
ArrayView<const double> read(const Values& v) { return {v.data(),v.size()}; }
ArrayView<double> write(Values& v) { return {v.data(),v.size()}; }
std::array<ArrayView<const double>,3> read(const Faces& v) { return {read(v[0]),read(v[1]),read(v[2])}; }
std::array<ArrayView<double>,3> write(Faces& v) { return {write(v[0]),write(v[1]),write(v[2])}; }
void require(bool condition,const char* message) { if(!condition) throw std::runtime_error(message); }

void capacity_from_actual_mass() {
    const Values dx{.1,.3},dy{.2},dz{.5},cp{1000.,2000.};
    GridView grid{2,1,1,read(dx),read(dy),read(dz)};
    Faces mass{Values{2.,-3.,4.},Values(4),Values(4)};
    const double partial=.25;
    TemperatureBoundary boundary{0,330.,{},{&partial,1},{}};
    auto capacity=detail::temperature_capacity_faces(grid,read(mass),read(cp),1500.,boundary);
    require(capacity[0]==Values({3000.,-3750.,8000.}),"mass/cp interpolation or opening counted twice");
    for(std::size_t axis=1;axis<3;++axis)
        require(capacity[axis]==Values(4),"zero mass produced nonzero capacity");
    mass[0]={-2.,3.,-4.};boundary.direction=1;
    capacity=detail::temperature_capacity_faces(grid,read(mass),read(cp),1500.,boundary);
    require(capacity[0]==Values({-2000.,3750.,-6000.}),"reverse actual inlet cp");
    const double closed=0.;boundary.opening={&closed,1};
    capacity=detail::temperature_capacity_faces(grid,read(mass),read(cp),1500.,boundary);
    require(capacity[0][2]==-8000.,"closed actual inflow was masked or treated as known inlet");
    const Values constant{4182.,4182.};boundary.opening={};
    capacity=detail::temperature_capacity_faces(grid,read(mass),read(constant),4182.,boundary);
    for(std::size_t face=0;face<3;++face)
        require(capacity[0][face]==mass[0][face]*4182.,"constant cp actual mass product");
    const double unit=1.;grid.dz={&unit,1};
    require(detail::temperature_capacity_faces(grid,read(mass),read(constant),4182.,boundary)==capacity,
            "mass capacity repeated physical depth");
    auto bad=read(mass);bad[1].size=3;bool rejected=false;
    try { (void)detail::temperature_capacity_faces(grid,bad,read(cp),1500.,boundary); }
    catch(const std::invalid_argument&) { rejected=true; }
    require(rejected,"invalid mass extent accepted");
    mass[0][1]=std::numeric_limits<double>::quiet_NaN();rejected=false;
    try { (void)detail::temperature_capacity_faces(grid,read(mass),read(cp),1500.,boundary); }
    catch(const std::invalid_argument&) { rejected=true; }
    require(rejected,"nonfinite actual mass accepted");
}

void direct_capacity_update_and_incomplete_boundary() {
    const double width=1.,depth=.125,zero=0.,hv=2.,epsilon=.5,rho_cp=2.,u=1.,partial=.25,old_inlet=99.;
    const GridView grid{1,1,1,{&width,1},{&width,1},{&depth,1}};
    Faces ca{Values{4.,4.},Values(2),Values(2)},cb{Values(2),Values{3.,3.},Values(2)};
    double ta=400.,tb=300.,ts=350.;
    const TemperatureStateView state{{&ta,1},{&tb,1},{&ts,1}};
    TemperatureFluidView a{{&zero,1},{&hv,1},{&epsilon,1},{&rho_cp,1},{&u,1},{&zero,1},{},
        {0,400.,{},{&partial,1},{&old_inlet,1}},read(ca)};
    TemperatureFluidView b{{&zero,1},{&hv,1},{&epsilon,1},{&rho_cp,1},{&zero,1},{&u,1},{},
        {2,300.,{},{&partial,1},{&old_inlet,1}},read(cb)};
    TemperatureControl control{1,1,1e-4,.7,1.,1.,true,false};
    PhysicalHeatLedger audit;
    const auto result=solve_temperature(TemperatureScheme::cell_centered_2d,grid,a,b,{&zero,1},state,control,{},false,&audit);
    // Explicit C=4/3 wins over cell epsilon*rho_cp*u=1 and old inlet=99.
    // C already contains the partial opening; this 2D driver uses unit depth.
    const double a_star=(4.*400.+2.*350.)/6.,a_point=400.+.2*(a_star-400.);
    const double s_point=.5*(a_point+300.),b_point=(3.*300.+2.*s_point)/5.;
    const double expected_a=400.+.6*(a_point-400.),expected_s=350.+.6*(s_point-350.);
    const double expected_b=300.+.6*(b_point-300.);
    require(result.stop==TemperatureStop::budget_exhausted&&result.iterations==1&&audit.boundary_complete,
            "one-step direct capacity status");
    require(std::abs(ta-expected_a)<1e-12&&std::abs(ts-expected_s)<1e-12&&std::abs(tb-expected_b)<1e-12,
            "direct capacity repeated cell rho/epsilon/opening/depth or old inlet");
    require(audit.advective_out[0][0][0]==-1600.,"direct inlet physical capacity changed");
    ta=tb=ts=330.;a.boundary.inlet_temperature=b.boundary.inlet_temperature=330.;a.boundary.opening={&zero,1};
    control.max_iterations=20;control.chunk_iterations=5;
    const auto incomplete=solve_temperature(TemperatureScheme::cell_centered_2d,grid,a,b,{&zero,1},state,control,{},false,&audit);
    require(incomplete.stop==TemperatureStop::budget_exhausted&&incomplete.iterations==20&&!audit.boundary_complete,
            "unknown closed inflow certified convergence");
    require(std::abs(ta-330.)<1e-8&&std::abs(tb-330.)<1e-8&&std::abs(ts-330.)<1e-8,
            "divergence-free unknown-inflow fixture changed uniform temperature");
    require(std::abs(audit.advective_out[0][0][0]+1320.)<1e-10&&ca[0]==Values({4.,4.}),
            "unknown closed inflow was masked");
}

void optional_w_is_inactive_in_2d() {
    const double unit=1.,zero=0.,rho_cp=1000.;
    const GridView grid{1,1,1,{&unit,1},{&unit,1},{&unit,1}};
    const TemperatureControl control{1,1,1e-8,.7,1.,1.,true,false};
    std::array<double,3> reference{};
    TemperatureResult reference_result{};
    PhysicalHeatLedger reference_audit;
    for(const double w:{0.,1.}) {
        std::array<double,3> t{400.,300.,350.};
        const TemperatureFluidView a{{&zero,1},{&unit,1},{&unit,1},{&rho_cp,1},
            {&zero,1},{&zero,1},{&w,1},{0,400.,{},{},{}}};
        const TemperatureFluidView b{{&zero,1},{&unit,1},{&unit,1},{&rho_cp,1},
            {&zero,1},{&zero,1},{&zero,1},{1,300.,{},{},{}}};
        PhysicalHeatLedger audit;
        const auto result=solve_temperature(TemperatureScheme::cell_centered_2d,
            grid,a,b,{&zero,1},{{&t[0],1},{&t[1],1},{&t[2],1}},control,{},false,&audit);
        // With no active-axis transport or conduction: A*=390, S*=345,
        // B*=345. The .6 block mix gives [394,327,347], Q_B=20 and dTmax=27.
        const std::array<double,3> expected{394.,327.,347.},residual{-47.,20.,27.};
        for(std::size_t side=0;side<3;++side) {
            require(std::abs(t[side]-expected[side])<1e-12,"2D optional w changed the analytical state");
            require(audit.residual[side].size()==1&&std::abs(audit.residual[side][0]-residual[side])<1e-12,
                    "2D optional w changed the analytical cell balance");
        }
        require(result.stop==TemperatureStop::budget_exhausted&&result.iterations==1&&audit.boundary_complete,
                "2D optional w changed status or physical boundary completeness");
        require(std::abs(result.residual-27.)<1e-12&&std::abs(result.q_b-20.)<1e-12,
                "2D optional w changed the analytical update or heat");
        if(w==0.) { reference=t;reference_result=result;reference_audit=audit; }
        else require(t==reference&&result.stop==reference_result.stop&&result.iterations==reference_result.iterations
            &&result.residual==reference_result.residual&&result.q_b==reference_result.q_b
            &&audit.boundary_complete==reference_audit.boundary_complete&&audit.residual==reference_audit.residual
            &&audit.advective_out==reference_audit.advective_out&&audit.diffusive_out==reference_audit.diffusive_out,
            "2D optional cell w is not numerically inactive");
    }
}

void divergence_free_case(bool three_d,int direction,int opening_kind) {
    const Values dx{.012,.018,.015,.021,.017},dy{.014,.019,.016,.023},dz=three_d?Values{.011,.017,.013}:Values{1.};
    const GridView grid{dx.size(),dy.size(),dz.size(),read(dx),read(dy),read(dz)};
    const detail::EnergyMesh mesh(grid);const auto n=mesh.cells();
    const double t0=330.,cp_value=4182.,rho=1.2,epsilon_value=.4,speed=.3;
    Values cp(n,cp_value),rho_cp(n,rho*cp_value),epsilon(n,epsilon_value),ka(n,.04),kb(n,.05),ks(n,3.),hva(n,1200.),hvb(n,1500.);
    std::array<Values,3> t{Values(n,t0),Values(n,t0),Values(n,t0)};
    std::array<Faces,2> mass,capacity,velocity,offset;
    std::array<Values,2> opening;std::array<TemperatureBoundary,2> boundary;
    const std::array<std::size_t,3> sizes{(grid.nx+1)*grid.ny*grid.nz,grid.nx*(grid.ny+1)*grid.nz,grid.nx*grid.ny*(grid.nz+1)};
    for(std::size_t side=0;side<2;++side) {
        const int d=side==0?direction:direction^1;const auto axis=static_cast<std::size_t>(d/2);
        const double sign=d%2?-1.:1.;opening[side].resize(n/mesh.count[axis]);
        for(std::size_t patch=0;patch<opening[side].size();++patch)
            opening[side][patch]=opening_kind==0?1.:opening_kind==2?0.:std::array<double,4>{0.,.25,.5,1.}[patch%4];
        for(std::size_t a=0;a<3;++a) {mass[side][a].assign(sizes[a],0.);offset[side][a].assign(sizes[a],0.);velocity[side][a].assign(n,0.);}
        for(std::size_t p=0;p<n;++p) {
            const auto cell=mesh.coord(p);const double u=sign*speed*opening[side][mesh.patch(axis,cell)];
            velocity[side][axis][p]=9.*u; // Caller cell velocity intentionally disagrees with actual faces.
            double area=1.;for(std::size_t a=0;a<3;++a)if(a!=axis)area*=mesh.width[a][cell[a]];
            const double m=epsilon_value*rho*u*area;
            mass[side][axis][mesh.face(axis,p,1)]=m;
            if(cell[axis]==0)mass[side][axis][mesh.face(axis,p,-1)]=m;
        }
        boundary[side]={d,t0,{},read(opening[side]),{}};
        capacity[side]=detail::temperature_capacity_faces(grid,read(mass[side]),read(cp),cp_value,boundary[side]);
        for(std::size_t p=0;p<n;++p) {
            double divergence=0.;
            for(std::size_t a=0;a<3;++a)divergence+=capacity[side][a][mesh.face(a,p,1)]-capacity[side][a][mesh.face(a,p,-1)];
            require(divergence==0.,"isothermal fixture has nonzero actual capacity divergence");
        }
    }
    const auto original_capacity=capacity,original_mass=mass;const auto original_cp=cp;
    const auto phase=[&](std::size_t side) {return EnergyPhase{side==0?read(ka):read(kb),side==0?read(hva):read(hvb),{},
        {read(capacity[side]),read(offset[side])},boundary[side],true};};
    const TemperatureStateView state{write(t[0]),write(t[1]),write(t[2])};
    const auto uniform=energy_physical_audit(grid,phase(0),phase(1),read(ks),state);
    require(uniform.boundary_complete,"isothermal fixture boundary incomplete");
    for(const auto& r:uniform.residual)for(double value:r)require(value==0.,"uniform fixture is not an exact solution");
    const auto fluid=[&](std::size_t side) {return TemperatureFluidView{side==0?read(ka):read(kb),side==0?read(hva):read(hvb),
        read(epsilon),read(rho_cp),read(velocity[side][0]),read(velocity[side][1]),read(velocity[side][2]),boundary[side],read(capacity[side])};};
    const TemperatureControl control{20,5,1e-4,.7,three_d?.7:1.,three_d?.7:1.,true,three_d};
    PhysicalHeatLedger returned;
    const auto solved=solve_temperature(three_d?TemperatureScheme::cell_centered_3d:TemperatureScheme::cell_centered_2d,
        grid,fluid(0),fluid(1),read(ks),state,control,{},false,&returned);
    require(capacity==original_capacity&&mass==original_mass&&cp==original_cp,"actual face inputs were mutated");
    for(const auto& field:t)for(double value:field)require(std::isfinite(value)&&std::abs(value-t0)<1e-8,"isothermal 1e-8 K gate failed");
    detail::temperature_face_offsets(mesh,read(capacity[0]),read(t[0]),write(offset[0]));
    if(three_d)detail::temperature_face_offsets(mesh,read(capacity[1]),read(t[1]),write(offset[1]));
    const auto actual=energy_physical_audit(grid,phase(0),phase(1),read(ks),state);
    require(returned.boundary_complete&&actual.boundary_complete&&returned.solved==actual.solved
        &&returned.residual==actual.residual&&returned.advective_out==actual.advective_out
        &&returned.diffusive_out==actual.diffusive_out&&returned.source_integral==actual.source_integral
        &&returned.prescribed_b_power==actual.prescribed_b_power,"returned ledger is not the fresh actual-face ledger");
    double qa=0.;for(std::size_t p=0;p<n;++p)qa+=hva[p]*(t[0][p]-t[2][p])*mesh.volume(mesh.coord(p));
    require(solved.stop==TemperatureStop::converged&&energy_balance_error(actual)/std::max({std::abs(qa),std::abs(solved.q_b),1.})<=1e-7,
            "isothermal original budget/balance gate failed");
}
} // namespace

int main() {
    using namespace tpmshx;
    const double width[]{1.}, zero[]{0.}, hv[]{2.}, epsilon[]{.5}, rcp[]{2.}, velocity[]{1.};
    double ta[]{400.}, tb[]{300.}, ts[]{350.};
    const GridView grid{1,1,1,{width,1},{width,1},{width,1}};
    const TemperatureFluidView a{{zero,1},{hv,1},{epsilon,1},{rcp,1},
                                 {velocity,1},{zero,1},{},{0,400.}};
    const TemperatureFluidView b{{zero,1},{hv,1},{epsilon,1},{rcp,1},
                                 {zero,1},{velocity,1},{},{2,300.}};
    const TemperatureStateView state{{ta,1},{tb,1},{ts,1}};
    const TemperatureControl control{1,1,1e-4,.7,1.,1.,true,false};
    const auto result = solve_temperature(TemperatureScheme::cell_centered_2d,
                                          grid,a,b,{zero,1},state,control);
    // One CV is both inlet and outlet. The shared Picard recipe applies
    // .2 A relaxation, then solid/B updates, then .6 mixing of all phases.
    // The previous undamped single-step expectation belongs to the old recipe;
    // the analytical steady state and all comparison tolerances stay unchanged.
    const double a_star = (400.+2.*350.)/3.;
    const double a_point = 400.+.2*(a_star-400.);
    const double s_point = .5*(a_point+300.);
    const double b_point = (300.+2.*s_point)/3.;
    const double expected_a = 400.+.6*(a_point-400.);
    const double expected_s = 350.+.6*(s_point-350.);
    const double expected_b = 300.+.6*(b_point-300.);
    if (result.stop != TemperatureStop::budget_exhausted || result.iterations != 1
        || std::abs(ta[0]-expected_a)>1e-12 || std::abs(ts[0]-expected_s)>1e-12
        || std::abs(tb[0]-expected_b)>1e-12) return 1;
    const auto saved_a = ta[0];
    try {
        solve_temperature(static_cast<TemperatureScheme>(99),grid,a,b,{zero,1},state,control);
        return 2;
    } catch (const std::invalid_argument&) {
        if (ta[0] != saved_a) return 3;
    }
    auto finishing = control;
    finishing.max_iterations = 1000;
    finishing.chunk_iterations = 5;
    finishing.q_relative_tolerance = 1e-10;
    const auto converged = solve_temperature(TemperatureScheme::cell_centered_2d,
                                             grid,a,b,{zero,1},state,finishing);
    // Steady one-CV equations give Ts=350, Ta=1100/3, Tb=1000/3,
    // and equal physical hot/cold duties of 100/3 W per metre of depth.
    if (converged.stop != TemperatureStop::converged || converged.iterations >= 1000
        || std::abs(ts[0]-350.)>1e-7 || std::abs(ta[0]-1100./3.)>1e-7
        || std::abs(tb[0]-1000./3.)>1e-7 || std::abs(converged.q_b-100./3.)>1e-7
        || std::abs((400.-ta[0])-(tb[0]-300.))>1e-7) return 4;
    capacity_from_actual_mass();
    direct_capacity_update_and_incomplete_boundary();
    optional_w_is_inactive_in_2d();
    for(bool three_d:{false,true})for(int direction=0;direction<(three_d?6:4);++direction)
        for(int opening=0;opening<3;++opening)divergence_free_case(three_d,direction,opening);
    std::puts("C++ temperature driver: analytical updates, actual mass/cp, incomplete inflow and 30 divergence-free cases passed");
    return 0;
}
