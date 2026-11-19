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
        const auto saved_owner=solver.snapshot();
        std::array<std::vector<double>,10> copied{u,v,w,p,pp,du,dv,dw,rho,vin};
        const tpmshx::Simple3DStateView copied_state{view(copied[0]),view(copied[1]),view(copied[2]),
            view(copied[3]),view(copied[4]),view(copied[5]),view(copied[6]),view(copied[7]),view(copied[8]),view(copied[9])};
        tpmshx::Simple3DSolver restored_owner(grid,read(outlet));
        restored_owner.restore(saved_owner);
        for(auto& t:T)t+=1.;
        result=solver.solve(material,boundary,state,control);
        require(result.converged&&result.post_closure_certified,"warm SIMPLE failed original F2");
        require(solver.massflux_target()==target,"warm inlet reference drifted");
        const auto resumed_result=restored_owner.solve(material,boundary,copied_state,control);
        require(resumed_result.converged && resumed_result.iterations==result.iterations
            && restored_owner.history().legacy==solver.history().legacy,"saved SIMPLE owner changed warm solve history");
        const std::array<const std::vector<double>*,10> original{&u,&v,&w,&p,&pp,&du,&dv,&dw,&rho,&vin};
        for(std::size_t i=0;i<copied.size();++i)
            require(copied[i]==*original[i],"saved SIMPLE owner changed warm fields");
        auto invalid_owner=saved_owner;invalid_owner.widths[0][0]*=2.;
        bool owner_rejected=false;
        try { restored_owner.restore(invalid_owner); }
        catch(const std::invalid_argument&) { owner_rejected=true; }
        require(owner_rejected && restored_owner.history().legacy==solver.history().legacy,
            "invalid SIMPLE owner changed the active state");
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
        auto saved=monitor.snapshot();
        tpmshx::SimpleF2Monitor resumed(saved,control.convergence);
        saved.previous[0][2]=9.;
        require(resumed.velocity_delta({read(probe),{},{}})==0.,"F2 snapshot shares mutable storage");
        require(resumed.submit(13,9e-5,balanced,0.)==tpmshx::SimpleStop::tol,"saved F2 confirmation was reset");
        require(monitor.submit(13,9e-5,balanced,monitor.velocity_delta({read(probe),{},{}}))==tpmshx::SimpleStop::tol,"fresh confirmation did not recover");
        tpmshx::SimpleF2Monitor stalled({read(probe),{},{}},control.convergence,10);
        require(stalled.submit(10,1e-3,balanced,0.)==tpmshx::SimpleStop::ongoing,"F2 stall window did not start");
        tpmshx::SimpleF2Monitor stalled_resume(stalled.snapshot(),control.convergence);
        require(stalled.submit(70,1e-3,balanced,0.)==tpmshx::SimpleStop::stall
            && stalled_resume.submit(70,1e-3,balanced,0.)==tpmshx::SimpleStop::stall,"saved F2 stall window was reset");
        auto invalid=stalled.snapshot();invalid.streak=control.convergence.confirmations+1;
        bool rejected_state=false;
        try { tpmshx::SimpleF2Monitor invalid_monitor(invalid,control.convergence); }
        catch (const std::invalid_argument&) { rejected_state=true; }
        require(rejected_state,"invalid F2 history was accepted");
        std::cout<<"3D cold iterations="<<cold<<" warm/cancel/F2-reset passed\n";return 0;
    } catch(const std::exception& e) { std::cerr<<e.what()<<'\n';return 1; }
}
