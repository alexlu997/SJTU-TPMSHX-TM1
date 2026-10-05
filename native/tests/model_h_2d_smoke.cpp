#include "tpmshx/model_h_2d.hpp"
#include "tpmshx/conservative_energy.hpp"
#include <cmath>
#include <cstdio>
#include <stdexcept>

int main() {
    using namespace tpmshx;
    double dx[]{.01}, dy[]{.01}, dz[]{1}, zero[]{0}, hv[]{2000};
    double ma[]{.0001,.0001}, mb[]{-.0001,-.0001}, my[]{0,0};
    double ta[]{350}, tb[]{300}, ts[]{325};
    const GridView grid{1,1,1,{dx,1},{dy,1},{dz,1}};
    const ModelHFluid2D a{Fluid::water,{zero,1},{hv,1},{ma,2},{my,2},{0,350}};
    const ModelHFluid2D b{Fluid::water,{zero,1},{hv,1},{mb,2},{my,2},{1,300}};
    const ModelHControl2D control{1,1,1e-5,true};
    const auto result=solve_model_h_2d(grid,a,b,{zero,1},{{ta,1},{tb,1},{ts,1}},control);
    const double expected_a=350+.2*((.2*325+.4182*350)/.6182-350);
    const double expected_s=.5*(expected_a+300);
    const double expected_b=300+.2*((.2*expected_s+.4182*300)/.6182-300);
    if (result.stop!=TemperatureStop::budget_exhausted || result.iterations!=1 || !result.audit_available
        || std::abs(ta[0]-expected_a)>1e-12 || std::abs(tb[0]-expected_b)>1e-12
        || std::abs(ts[0]-expected_s)>1e-12 || !result.audit.boundary_complete
        || std::abs(result.audit.telescoping_error)>1e-11)
        throw std::runtime_error("single-CV water model-h arithmetic failed");
    bool rejected=false;
    try {
        solve_model_h_2d(grid,a,b,{ta,1},{{ta,1},{tb,1},{ts,1}},control);
    } catch (const std::invalid_argument&) { rejected=true; }
    if (!rejected) throw std::runtime_error("aliased model-h input was accepted");

    // At the model reference temperature h(300 K)=0. Reconstructing C*T+B
    // from rounded coefficients left a spurious ~7e-11 W/m on this inlet.
    mb[0]=mb[1]=-.45543864961988384;
    ta[0]=350;tb[0]=300;ts[0]=325;
    auto strict_control=control;
    strict_control.strict_energy_balance=true;
    PhysicalHeatLedger ledger;
    const auto strict=solve_model_h_2d(grid,a,b,{zero,1},{{ta,1},{tb,1},{ts,1}},strict_control,{},&ledger);
    const double b_out=-mb[0]*4182.*(tb[0]-300.);
    const double b_balance=hv[0]*dx[0]*dy[0]*(ts[0]-tb[0])-b_out;
    if (!strict.physical_audit_available || !ledger.boundary_complete
        || ledger.advective_out[1][1][0]!=0.
        || std::abs(ledger.advective_out[1][0][0]-b_out)>5e-12
        || std::abs(ledger.residual[1][0]-b_balance)>5e-12)
        throw std::runtime_error("strict actual enthalpy power lost its zero reference");

    // Zero enthalpy power does not mean zero mass inflow: the physical
    // boundary identity must still reject an undeclared inward face.
    auto unknown_b=b;
    unknown_b.boundary.direction=0;
    ta[0]=tb[0]=ts[0]=300.;
    auto isothermal_a=a;
    isothermal_a.boundary.inlet_temperature=300.;
    const auto unknown=solve_model_h_2d(grid,isothermal_a,unknown_b,{zero,1},
        {{ta,1},{tb,1},{ts,1}},strict_control,{},&ledger);
    if (!unknown.physical_audit_available || ledger.boundary_complete
        || ledger.advective_out[1][1][0]!=0.)
        throw std::runtime_error("zero enthalpy power hid unknown mass inflow");

    // A known affine T is an exact steady state here: prescribed B supplies
    // the constant advective derivative through A/solid exchange. The two
    // endpoint cells must reconstruct the physical face positions, including
    // the half-cell inlet and the extrapolated outlet, in both directions.
    for (bool nonuniform:{false,true}) for (bool reverse:{false,true}) {
        double widths[]{nonuniform ? .125 : .25,nonuniform ? .375 : .25};
        double transverse[]{1},inactive[]{0,0},exchange[]{4182,4182};
        const double mass=reverse ? -1./64 : 1./64;
        double signed_mass[]{mass,mass,mass},no_x[]{0,0,0},no_y[]{0,0,0,0};
        const double center[]{.5*widths[0],widths[0]+.5*widths[1]};
        double fluid[2],reservoir[2],solid[2];
        for (std::size_t p=0;p<2;++p) {
            fluid[p]=300+16*center[p];
            solid[p]=fluid[p]+16*mass;
            reservoir[p]=fluid[p]+32*mass;
        }
        const GridView pair{2,1,1,{widths,2},{transverse,1},{transverse,1}};
        const ModelHFluid2D flowing{Fluid::water,{inactive,2},{exchange,2},
            {signed_mass,3},{no_y,4},{reverse ? 1 : 0,reverse ? 308. : 300.}};
        const ModelHFluid2D prescribed{Fluid::water,{inactive,2},{exchange,2},
            {no_x,3},{no_y,4},{1,300.}};
        double fixed[2]{reservoir[0],reservoir[1]};
        const auto affine=solve_model_h_2d(pair,flowing,prescribed,{inactive,2},
            {{fluid,2},{reservoir,2},{solid,2}},strict_control,{fixed,2},&ledger);
        if (!affine.physical_audit_available || !ledger.boundary_complete
            || ledger.advective_out[0][0][0]!=0.
            || std::abs(ledger.advective_out[0][1][0]-mass*4182*8)>1e-11)
            throw std::runtime_error("strict affine endpoint face power differs");
        for (std::size_t p=0;p<2;++p)
            if (std::abs(fluid[p]-(300+16*center[p]))>1e-12
                || std::abs(ledger.residual[0][p])>1e-11
                || reservoir[p]!=fixed[p])
                throw std::runtime_error("strict affine two-cell steady state changed");
    }
    std::printf("model-h 2D independent caller: arithmetic, audit, zero enthalpy reference, inlet identity and alias guard passed\n");
    return 0;
}
