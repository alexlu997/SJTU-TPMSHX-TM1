#include "tpmshx/simple_2d.hpp"

#include <cmath>
#include <iostream>
#include <stdexcept>
#include <vector>

int main() {
    try {
        constexpr std::size_t ny=8;
        const double width=.02, length=.032, velocity=.005, mu=.001, epsilon=.6, permeability=1e-7;
        double dx[]={width}, dz[]={1.}; std::vector<double> dy(ny,length/static_cast<double>(ny));
        const tpmshx::GridView grid{1,ny,1,{dx,1},{dy.data(),ny},{dz,1}};
        unsigned char outlet[]={1};
        std::vector<double> eps(ny,epsilon),viscosity(ny,mu),effective(ny,mu/epsilon),k(ny,permeability),cf(ny,0.),temperature(ny,300.);
        std::vector<double> u(2*ny,0.),v(ny+1,0.),p(ny,0.),pp(ny,0.),du(2*ny,0.),dv(ny+1,0.),rho(ny,1000.);
        double inlet[]={velocity},fraction[]={1.},outlet_u[]={1.,1.}; v[0]=velocity;
        const auto c=[](const std::vector<double>& a) { return tpmshx::ArrayView<const double>{a.data(),a.size()}; };
        const auto a=[](std::vector<double>& x) { return tpmshx::ArrayView<double>{x.data(),x.size()}; };
        const tpmshx::Simple2DMaterialView material{c(eps),c(viscosity),c(effective),c(k),c(cf),c(temperature)};
        const tpmshx::Simple2DStateView state{a(u),a(v),a(p),a(pp),a(du),a(dv),a(rho),{inlet,1}};
        const tpmshx::Simple2DBoundaryView boundary{{fraction,1},{outlet_u,2},velocity,1.,{}};
        tpmshx::Simple2DControl control{};
        control.max_iterations=2000; control.inner_sweeps=2;
        control.alpha_velocity=.7; control.alpha_pressure=.3; control.alpha_density=.3;
        control.pressure_reference_absolute=101325.; control.gas_constant=287.05;
        control.ideal_gas=false; control.convergence={1e-9,1e-10,1e-10,.01,1e-4,1e-3,2,5,60};
        tpmshx::Simple2DSolver solver(grid,{outlet,1});
        const auto result=solver.solve(material,boundary,state,control);
        if (!result.converged || !result.post_closure_certified) throw std::runtime_error("analytic SIMPLE case did not converge");
        // One cross-stream CV has two no-slip half-width viscous walls.
        // The exact discrete v equation is dP/dy=(mu/K+4*mu_eff/W^2)*v.
        const double gradient=(mu/permeability+4.*(mu/epsilon)/(width*width))*velocity;
        for (std::size_t j=0;j<ny;++j) {
            const double expected=gradient*dy[0]*static_cast<double>(ny-1-j);
            if (std::abs(p[j]-expected)>2e-8 || std::abs(v[j]-velocity)>1e-12)
                throw std::runtime_error("SIMPLE differs from independent Darcy/wall equation");
        }
        if (std::abs(v[ny]-velocity)>1e-12 || p.back()!=0.) throw std::runtime_error("SIMPLE outlet flux/pin changed");
        const auto warm=solver.solve(material,boundary,state,control);
        if (!warm.converged || warm.iterations!=21) throw std::runtime_error("warm F2 confirmation changed");
        std::cout<<"SIMPLE 2D: independent Darcy/Brinkman wall equation, F2 and warm restart passed\n";
        return 0;
    } catch (const std::exception& e) { std::cerr<<e.what()<<'\n'; return 1; }
}
