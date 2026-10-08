#include "tpmshx/simple_3d.hpp"

#include <cmath>
#include <iostream>
#include <stdexcept>
#include <vector>
namespace {
void require(bool condition,const char* message) { if(!condition)throw std::runtime_error(message); }
template<typename T> tpmshx::ArrayView<T> view(std::vector<T>& a) { return {a.data(),a.size()}; }
template<typename T> tpmshx::ArrayView<const T> read(const std::vector<T>& a) { return {a.data(),a.size()}; }
bool cancel(void* context) { return ++*static_cast<int*>(context)>=3; }
}
int main() {
    try {
        constexpr std::size_t nx=4,ny=5,nz=3,n=nx*ny*nz;
        std::vector<double> dx(nx,.009),dy(ny,.016),dz(nz,.008);
        const tpmshx::GridView grid{nx,ny,nz,read(dx),read(dy),read(dz)};
        std::vector<unsigned char> outlet(nx*nz,1);
        std::vector<double> epsilon(n,.6),mu(n,1.8e-5),mu_eff(n,3e-5),K(n,1e-7),cf(n,35.),T(n,300.);
        std::vector<double> u((nx+1)*ny*nz),v(nx*(ny+1)*nz,.7),w(nx*ny*(nz+1)),p(n),pp(n),du(u.size()),dv(v.size()),dw(w.size()),rho(n,1.2),vin(nx*nz,.7);
        std::vector<double> out_u((nx+1)*nz,1.),out_w(nx*(nz+1),1.);
        const tpmshx::Simple3DMaterialView material{read(epsilon),read(mu),read(mu_eff),read(K),read(cf),read(T)};
        const tpmshx::Simple3DBoundaryView boundary{read(out_u),read(out_w)};
        const tpmshx::Simple3DStateView state{view(u),view(v),view(w),view(p),view(pp),view(du),view(dv),view(dw),view(rho),view(vin)};
        tpmshx::Simple3DControl control{};
        control.max_iterations=600;control.inner_sweeps=1;control.pressure_rebuild_every=100;
        control.alpha_velocity=.5;control.alpha_pressure=.2;control.alpha_density=.3;
        control.pressure_reference_absolute=101325.;control.gas_constant=287.05;control.pressure_diagonal_drift=.05;
        control.convergence={1e-4,1e-6,1e-6,.01,1e-4,1e-3,2,5,60};
        control.track_momentum=true;
        tpmshx::Simple3DSolver solver(grid,read(outlet));
        auto result=solver.solve(material,boundary,state,control);
        require(result.converged&&result.post_closure_certified,"cold SIMPLE failed original F2");
        require(result.mass.counted_cells==n,"returned-field audit omitted cells");
        const auto target=solver.massflux_target();const auto cold=result.iterations;
        for(auto& t:T)t+=1.;
        result=solver.solve(material,boundary,state,control);
        require(result.converged&&result.post_closure_certified,"warm SIMPLE failed original F2");
        require(solver.massflux_target()==target,"warm inlet reference drifted");
        int calls=0;control.cancel=cancel;control.context=&calls;
        result=solver.solve(material,boundary,state,control);
        require(result.stop==tpmshx::SimpleStop::cancelled&&!result.converged&&result.iterations==1&&calls==3,"cancellation budget changed");
        // The actual shared monitor clears only confirmation after a rejected
        // final certificate. Its next delta must observe closure's velocity jump.
        std::vector<double> probe(3,0.);
        tpmshx::SimpleF2Monitor monitor({read(probe),{},{}},control.convergence,10);
        tpmshx::SimpleMassAudit balanced{0.,1.,1.,0.,0.,1};
        tpmshx::SimpleStop reason=tpmshx::SimpleStop::ongoing;
        for(std::size_t it=1;it<=11;++it) reason=monitor.submit(it,9e-5,balanced,monitor.velocity_delta({read(probe),{},{}}));
        require(reason==tpmshx::SimpleStop::tol,"confirmation contract changed");
        auto rejected=balanced;rejected.global_residual=2e-6;
        require(!monitor.gates_hold(9e-5,rejected),"final failure falsely certified");
        monitor.reset_confirmation();probe[2]=1.;
        const auto fresh_delta=monitor.velocity_delta({read(probe),{},{}});
        require(fresh_delta==1.,"post-closure velocity snapshot was reset");
        require(monitor.submit(12,9e-5,balanced,fresh_delta)==tpmshx::SimpleStop::ongoing,"stale confirmation reused");
        require(monitor.submit(13,9e-5,balanced,monitor.velocity_delta({read(probe),{},{}}))==tpmshx::SimpleStop::tol,"fresh confirmation did not recover");
        std::cout<<"3D cold iterations="<<cold<<" warm/cancel/F2-reset passed\n";return 0;
    } catch(const std::exception& e) { std::cerr<<e.what()<<'\n';return 1; }
}
