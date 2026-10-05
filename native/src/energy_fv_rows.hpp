#pragma once

#include "tpmshx/conservative_energy.hpp"
#include <algorithm>
#include <array>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace tpmshx::detail {

struct EnergyMesh {
    const GridView& g;
    std::array<std::size_t,3> count, stride;
    std::array<ArrayView<const double>,3> width;
    explicit EnergyMesh(const GridView& grid)
        : g(grid), count{g.nx,g.ny,g.nz}, stride{g.ny*g.nz,g.nz,1},
          width{g.dx,g.dy,g.dz} {}
    std::size_t cells() const { return g.nx*g.ny*g.nz; }
    std::array<std::size_t,3> coord(std::size_t p) const {
        return {p/stride[0],(p/g.nz)%g.ny,p%g.nz};
    }
    double volume(const std::array<std::size_t,3>& c) const {
        return g.dx[c[0]]*g.dy[c[1]]*g.dz[c[2]];
    }
    double face_area(std::size_t axis,const std::array<std::size_t,3>& c) const {
        return volume(c)/width[axis][c[axis]];
    }
    bool inside(const std::array<std::size_t,3>& c,std::size_t axis,int sign) const {
        return sign<0 ? c[axis]>0 : c[axis]+1<count[axis];
    }
    std::size_t neighbor(std::size_t p,std::size_t axis,int sign) const {
        return sign<0 ? p-stride[axis] : p+stride[axis];
    }
    std::size_t face(std::size_t axis,std::size_t p,int sign) const {
        const auto c=coord(p);
        const std::size_t low=axis==0 ? p : axis==1
            ? (c[0]*(g.ny+1)+c[1])*g.nz+c[2]
            : (c[0]*g.ny+c[1])*(g.nz+1)+c[2];
        return low+(sign>0 ? stride[axis] : 0);
    }
    std::size_t patch(std::size_t axis,const std::array<std::size_t,3>& c) const {
        return axis==0 ? c[1]*g.nz+c[2] : axis==1 ? c[0]*g.nz+c[2] : c[0]*g.ny+c[1];
    }
    std::size_t line_count(std::size_t axis) const { return cells()/count[axis]; }
    std::size_t line_start(std::size_t axis,std::size_t ordinal) const {
        return axis==0 ? ordinal : axis==1
            ? (ordinal/g.nz)*g.ny*g.nz+ordinal%g.nz : ordinal*g.nz;
    }
};

struct EnergyRow {
    double diagonal, rhs, local_rhs;
    std::array<double,6> neighbor{}; // positive RHS coefficients, x-/x+/...
};
struct PointEnergyCoefficients {
    double diagonal;
    std::array<double,6> neighbor;
};
static_assert(sizeof(PointEnergyCoefficients)==7*sizeof(double));
struct LinearFace { double C,B; };
inline double optional(ArrayView<const double> a,std::size_t p,double fallback=0.) {
    return a.size ? a[p] : fallback;
}
inline double effective_K(const EnergyPhase& f,std::size_t p) { return f.K[p]; }
inline double effective_K(const PhysicalEnergyPhase& f,std::size_t p) { return f.K[p]; }
inline double effective_K(const FrozenEnergyPhase& f,std::size_t p) {
    return f.fluid.dh[p]*f.fluid.cp[p];
}
inline ArrayView<const double> exchange(const EnergyPhase& f) { return f.hv; }
inline ArrayView<const double> exchange(const PhysicalEnergyPhase& f) { return f.hv; }
inline ArrayView<const double> exchange(const FrozenEnergyPhase& f) { return f.fluid.hv; }
inline double transport(const EnergyPhase& f,std::size_t axis,std::size_t face) {
    return f.faces.capacity[axis][face];
}
inline double transport(const PhysicalEnergyPhase& f,std::size_t axis,std::size_t face) {
    return f.signed_transport[axis][face];
}
inline double transport(const FrozenEnergyPhase& f,std::size_t axis,std::size_t face) {
    const ArrayView<const double> mass[]{f.fluid.mass_x,f.fluid.mass_y,f.fluid.mass_z};
    return mass[axis][face];
}
inline bool inlet_face(const TemperatureBoundary& b,std::size_t axis,int sign) {
    return b.direction==static_cast<int>(2*axis+(sign>0));
}
inline bool known_inlet(const EnergyMesh& m,const TemperatureBoundary& b,
                        const std::array<std::size_t,3>& c,std::size_t axis,int sign) {
    return inlet_face(b,axis,sign)&&optional(b.opening,m.patch(axis,c),1.)>0.;
}
inline double inlet_temperature(const TemperatureBoundary& b,std::size_t patch) {
    return optional(b.profile,patch,b.inlet_temperature);
}
inline LinearFace face_energy(const EnergyPhase& f,const EnergyMesh& m,
                              std::size_t p,std::size_t axis,int sign) {
    const auto face=m.face(axis,p,sign);
    return {f.faces.capacity[axis][face],optional(f.faces.offset[axis],face)};
}
inline LinearFace face_energy(const PhysicalEnergyPhase& f,const EnergyMesh& m,
                              std::size_t p,std::size_t axis,int sign) {
    return {0.,f.power[axis][m.face(axis,p,sign)]};
}
inline LinearFace face_energy(const FrozenEnergyPhase& phase,const EnergyMesh& m,
                              std::size_t p,std::size_t axis,int sign) {
    const auto& f=phase.fluid;
    const auto c=m.coord(p);
    const double mass=transport(phase,axis,m.face(axis,p,sign));
    std::size_t up=p;
    if(sign*mass<0.) {
        if(m.inside(c,axis,sign)) up=m.neighbor(p,axis,sign);
        else if(phase.inlet.direction==-1 || known_inlet(m,phase.inlet,c,axis,sign)) {
            const auto patch=m.patch(axis,c);
            const double hin=optional(phase.inlet_h,patch,f.h_in);
            const double tin=inlet_temperature(phase.inlet,patch);
            return {mass*f.cp[p],mass*(hin-f.cp[p]*tin)};
        }
    }
    return {mass*f.cp[up],mass*(f.h_star[up]-f.cp[up]*f.t_star[up])};
}
template<class Phase>
double inlet_conductance(const EnergyMesh& m,const Phase& f,std::size_t p,
                         std::size_t axis,int sign) {
    if(!f.inlet_conduction||!inlet_face(f.inlet,axis,sign)) return 0.;
    const auto c=m.coord(p);
    return 2.*effective_K(f,p)*m.face_area(axis,c)
        *optional(f.inlet.opening,m.patch(axis,c),1.)/m.width[axis][c[axis]];
}

inline bool second_order_inlet(const EnergyPhase& f) { return f.second_order_inlet_conduction; }
inline bool second_order_inlet(const PhysicalEnergyPhase& f) { return f.second_order_inlet_conduction; }
inline bool second_order_inlet(const FrozenEnergyPhase&) { return false; }
struct InletDiffusion {
    double boundary=0.,neighbor=0.;
    std::size_t neighbor_cell=0;
};
template<class Phase>
InletDiffusion inlet_diffusion(const EnergyMesh& m,const Phase& f,std::size_t p,
                              std::size_t axis,int sign) {
    if(!second_order_inlet(f)) return {inlet_conductance(m,f,p,axis,sign),0.,p};
    if(!f.inlet_conduction||!inlet_face(f.inlet,axis,sign)) return {};
    const auto c=m.coord(p);
    const double opening=optional(f.inlet.opening,m.patch(axis,c),1.),kp=effective_K(f,p);
    if(opening==0.||kp==0.) return {};
    const double G0=inlet_conductance(m,f,p,axis,sign);
    if(m.count[axis]==1) return {G0,0.,p};
    const auto q=m.neighbor(p,axis,-sign),nc=sign<0 ? c[axis]+1:c[axis]-1;
    const double kn=effective_K(f,q);
    if(kn==0.) return {G0,0.,p}; // Do not sample a thermally disconnected cell.
    const double h0=m.width[axis][c[axis]],h1=m.width[axis][nc];
    const double length=std::max(h0,h1),k=std::min(kp,kn);
    const double x=h0/length,y=h1/length;
    const double r0=x*(k/kp),r1=y*(k/kn),resistance=std::max(r0,r1);
    const double rp=r0/resistance,rn=r1/resistance;
    // Reconstruct q(s)=q0+q1*s from Tb-T(s)=integral_0^s(q/K).
    // These positive scaled ratios implement D=RP*MN-RN*MP without subtracting
    // moments or forming h*h/K and Kp*Kn. Gb/G0 is in [1,1.5], Gn/G0 in [0,.5].
    const double denominator=2.*x*rp+(3.*x+y)*rn;
    return {G0*(1.+x*(rp+rn)/denominator),G0*(x*rp/denominator),q};
}

// One conservative physical row for both finite representations and updates.
// The default absolute form keeps its historical accumulation order. In the
// defect form rhs is evaluated as differences, never as rhs_absolute-D*T.
template<bool Defect,bool Cached=false,class Phase>
EnergyRow assemble_fluid_energy_row(const EnergyMesh& m,const Phase& f,
        ArrayView<const double> t,ArrayView<const double> ts,std::size_t p,
        double numerical_W=0.,const PointEnergyCoefficients* cached=nullptr) {
    static_assert(!Defect||!Cached,"physical defects never use the point cache");
    const auto c=m.coord(p);
    const double volume=m.volume(c), h=exchange(f)[p]*volume;
    const double local=h*(Defect ? ts[p]-t[p]:ts[p])
        +optional(f.source_W_m3,p)*volume+numerical_W;
    EnergyRow row{Cached ? cached->diagonal:h,local,local};
    double divergence_C=0.,divergence_B=0.;
    for(std::size_t axis=0;axis<3;++axis) {
        InletDiffusion inlet;
        int inlet_sign=0;
        if(second_order_inlet(f)) for(int sign:{-1,1})
            if(!m.inside(c,axis,sign)&&inlet_face(f.inlet,axis,sign)) {
                inlet=inlet_diffusion(m,f,p,axis,sign);inlet_sign=sign;
            }
        const LinearFace faces[]{face_energy(f,m,p,axis,-1),face_energy(f,m,p,axis,1)};
        if constexpr(Defect) {
            divergence_C+=faces[1].C-faces[0].C;
            divergence_B+=faces[1].B-faces[0].B;
        }
        for(int sign:{-1,1}) {
        const auto face=faces[sign>0];
        const double outward=sign*face.C;
        if constexpr(!Cached) row.diagonal+=std::max(outward,0.);
        if constexpr(!Defect) {
            row.rhs-=sign*face.B;
            row.local_rhs-=sign*face.B;
        }
        if(m.inside(c,axis,sign)) {
            const auto q=m.neighbor(p,axis,sign),nc=sign<0 ? c[axis]-1:c[axis]+1;
            double coefficient;
            if constexpr(Cached) coefficient=cached->neighbor[2*axis+(sign>0)];
            else {
                const double G=diffusion_conductance(effective_K(f,p),effective_K(f,q),
                    .5*m.width[axis][c[axis]],.5*m.width[axis][nc])*m.face_area(axis,c);
                row.diagonal+=G;coefficient=G+std::max(-outward,0.);
                if(inlet.neighbor>0.&&q==inlet.neighbor_cell) {
                    row.diagonal+=inlet.neighbor;coefficient+=inlet.neighbor;
                }
            }
            row.rhs+=coefficient*(Defect ? t[q]-t[p]:t[q]);
            row.neighbor[2*axis+(sign>0)]=coefficient;
        } else {
            const double G=sign==inlet_sign ? inlet.boundary:inlet_conductance(m,f,p,axis,sign);
            if constexpr(!Cached) row.diagonal+=G;
            const double incoming=G+std::max(-outward,0.);
            if(incoming>0.) {
                // Undefined inward transport is kept as an interior-state
                // diagnostic proxy; strict component sweeps reject it before
                // writes, and raw audit cannot certify this boundary.
                const bool defined=f.inlet.direction==-1||known_inlet(m,f.inlet,c,axis,sign);
                if(G>0.) {
                    const double inlet=inlet_temperature(f.inlet,m.patch(axis,c));
                    const double value=G*(Defect ? inlet-t[p]:inlet);
                    row.rhs+=value;
                    if constexpr(!Defect) row.local_rhs+=value;
                }
                const double upstream=defined ? inlet_temperature(f.inlet,m.patch(axis,c)):t[p];
                row.rhs+=std::max(-outward,0.)*(Defect ? upstream-t[p]:upstream);
                if constexpr(!Defect) row.local_rhs+=std::max(-outward,0.)*upstream;
            }
        }
        }
    }
    if constexpr(Defect) {
        row.rhs-=t[p]*divergence_C;
        row.rhs-=divergence_B;
        row.local_rhs=0.; // No absolute-temperature RHS is used by delta lines.
    }
    return row;
}

template<class Phase>
EnergyRow fluid_energy_row(const EnergyMesh& m,const Phase& f,
        ArrayView<const double> t,ArrayView<const double> ts,std::size_t p,
        double numerical_W=0.) {
    return assemble_fluid_energy_row<false>(m,f,t,ts,p,numerical_W);
}
template<class Phase>
EnergyRow fluid_energy_row(const EnergyMesh& m,const Phase& f,
        ArrayView<const double> t,ArrayView<const double> ts,std::size_t p,
        const PointEnergyCoefficients& cached,double numerical_W=0.) {
    return assemble_fluid_energy_row<false,true>(m,f,t,ts,p,numerical_W,&cached);
}
template<class Phase>
EnergyRow fluid_energy_defect_row(const EnergyMesh& m,const Phase& f,
        ArrayView<const double> t,ArrayView<const double> ts,std::size_t p,
        double numerical_W=0.) {
    return assemble_fluid_energy_row<true>(m,f,t,ts,p,numerical_W);
}

template<bool Defect,bool Cached=false>
EnergyRow assemble_solid_energy_row(const EnergyMesh& m,ArrayView<const double> ks,
        ArrayView<const double> hva,ArrayView<const double> hvb,
        ArrayView<const double> ta,ArrayView<const double> tb,
        ArrayView<const double> ts,ArrayView<const double> source,std::size_t p,
        const PointEnergyCoefficients* cached=nullptr) {
    static_assert(!Defect||!Cached,"physical defects never use the point cache");
    const auto c=m.coord(p);const double volume=m.volume(c);
    const double a=hva[p]*volume,b=hvb[p]*volume;
    const double local=a*(Defect ? ta[p]-ts[p]:ta[p])
        +b*(Defect ? tb[p]-ts[p]:tb[p])+optional(source,p)*volume;
    EnergyRow row{Cached ? cached->diagonal:a+b,local,local};
    for(std::size_t axis=0;axis<3;++axis) for(int sign:{-1,1}) {
        if(!m.inside(c,axis,sign)) continue;
        const auto q=m.neighbor(p,axis,sign),nc=sign<0 ? c[axis]-1:c[axis]+1;
        double G;
        if constexpr(Cached) G=cached->neighbor[2*axis+(sign>0)];
        else {
            G=diffusion_conductance(ks[p],ks[q],.5*m.width[axis][c[axis]],
                .5*m.width[axis][nc])*m.face_area(axis,c);
            row.diagonal+=G;
        }
        row.rhs+=G*(Defect ? ts[q]-ts[p]:ts[q]);
        row.neighbor[2*axis+(sign>0)]=G;
    }
    return row;
}

inline EnergyRow solid_energy_row(const EnergyMesh& m,ArrayView<const double> ks,
        ArrayView<const double> hva,ArrayView<const double> hvb,
        ArrayView<const double> ta,ArrayView<const double> tb,
        ArrayView<const double> ts,ArrayView<const double> source,std::size_t p) {
    return assemble_solid_energy_row<false>(m,ks,hva,hvb,ta,tb,ts,source,p);
}
inline EnergyRow solid_energy_row(const EnergyMesh& m,ArrayView<const double> ks,
        ArrayView<const double> hva,ArrayView<const double> hvb,
        ArrayView<const double> ta,ArrayView<const double> tb,
        ArrayView<const double> ts,ArrayView<const double> source,std::size_t p,
        const PointEnergyCoefficients& cached) {
    return assemble_solid_energy_row<false,true>(m,ks,hva,hvb,ta,tb,ts,source,p,&cached);
}
inline EnergyRow solid_energy_defect_row(const EnergyMesh& m,ArrayView<const double> ks,
        ArrayView<const double> hva,ArrayView<const double> hvb,
        ArrayView<const double> ta,ArrayView<const double> tb,
        ArrayView<const double> ts,ArrayView<const double> source,std::size_t p) {
    return assemble_solid_energy_row<true>(m,ks,hva,hvb,ta,tb,ts,source,p);
}

// Caller owns and reuses this O(line length) workspace. No per-cell or
// per-line allocation occurs after the three vectors have been sized.
struct EnergyLineScratch {
    std::vector<double> pivot,upper,rhs;
    explicit EnergyLineScratch(std::size_t length)
        : pivot(length),upper(length),rhs(length) {}
};

inline void append_line_row(EnergyLineScratch& work,std::size_t i,
        double diagonal,double lower,double upper,double rhs) {
    if(!std::isfinite(diagonal)||!std::isfinite(lower)||!std::isfinite(upper)
        ||!std::isfinite(rhs)||diagonal<=1e-30)
        throw std::domain_error("invalid or degenerate energy line row");
    const double scale=std::max({std::abs(diagonal),std::abs(lower),std::abs(upper)});
    double pivot=diagonal;
    if(i) {
        const double multiplier=lower/work.pivot[i-1];
        pivot-=multiplier*work.upper[i-1];
        rhs-=multiplier*work.rhs[i-1];
    }
    if(!std::isfinite(pivot)||!std::isfinite(rhs)
        ||pivot<=64.*std::numeric_limits<double>::epsilon()*scale)
        throw std::domain_error("singular or ill-conditioned energy line pivot");
    work.pivot[i]=pivot;work.upper[i]=upper;work.rhs[i]=rhs;
}

// Retain increments below a temperature ulp across the consumer's sweeps.
// The caller owns the carry lifetime and resets it after replacing the state.
inline double compensated_energy_increment(double temperature,double increment,
                                             double& carry) {
    const double corrected=increment-carry;
    const double next=temperature+corrected;
    const double next_carry=(next-temperature)-corrected;
    if(!std::isfinite(next)||!std::isfinite(next_carry))
        throw std::domain_error("nonfinite compensated energy update");
    carry=next_carry;
    return next;
}

inline double apply_energy_line(const EnergyMesh& m,ArrayView<double> t,
        std::size_t axis,std::size_t start,double omega,EnergyLineScratch& work,
        ArrayView<double> compensation={}) {
    const auto length=m.count[axis];
    for(std::size_t ordinal=0;ordinal<length;++ordinal) {
        const auto j=length-1-ordinal;
        work.rhs[j]=(work.rhs[j]-(j+1<length ? work.upper[j]*work.rhs[j+1]:0.))/work.pivot[j];
        if(!std::isfinite(work.rhs[j])) throw std::domain_error("nonfinite energy line solution");
    }
    double change=0.;
    // Preflight every relaxed value before writing any cell in this line.
    for(std::size_t j=0;j<length;++j) {
        const auto p=start+j*m.stride[axis];
        if(compensation.size) {
            // A rounded-zero write can still be a live compensated step.
            // Report it so an exact-zero early exit cannot discard its carry.
            change=std::max(change,std::abs(omega*work.rhs[j]));
            double carry=compensation[p];
            work.rhs[j]=compensated_energy_increment(t[p],omega*work.rhs[j],carry);
            // Thomas back-substitution is complete; upper is free scratch.
            work.upper[j]=carry;
        } else work.rhs[j]=t[p]+omega*work.rhs[j];
        if(!std::isfinite(work.rhs[j])) throw std::domain_error("nonfinite energy line update");
    }
    for(std::size_t j=0;j<length;++j) {
        const auto p=start+j*m.stride[axis];
        change=std::max(change,std::abs(work.rhs[j]-t[p]));t[p]=work.rhs[j];
        if(compensation.size) compensation[p]=work.upper[j];
    }
    return change;
}

inline void check_line_workspace(const EnergyMesh& m,std::size_t axis,
        double omega,const EnergyLineScratch& work,ArrayView<double> compensation={}) {
    if(axis>=3||!std::isfinite(omega)||omega<=0.||omega>1.)
        throw std::invalid_argument("invalid energy line axis or relaxation");
    const auto n=m.count[axis];
    if(work.pivot.size()<n||work.upper.size()<n||work.rhs.size()<n)
        throw std::invalid_argument("energy line scratch is too short");
    if(compensation.size && (!compensation.data || compensation.size!=m.cells()))
        throw std::invalid_argument("energy line compensation extent mismatch");
}

template<class Phase>
double fluid_energy_line(const EnergyMesh& m,const Phase& f,ArrayView<double> t,
        ArrayView<const double> ts,std::size_t axis,std::size_t start,
        double omega,EnergyLineScratch& work,ArrayView<const double> numerical={},
        ArrayView<double> compensation={}) {
    check_line_workspace(m,axis,omega,work,compensation);
    const ArrayView<const double> temperature{t.data,t.size};
    for(std::size_t j=0;j<m.count[axis];++j) {
        const auto p=start+j*m.stride[axis];
        const auto row=fluid_energy_defect_row(m,f,temperature,ts,p,optional(numerical,p));
        append_line_row(work,j,row.diagonal,-row.neighbor[2*axis],
            -row.neighbor[2*axis+1],row.rhs);
    }
    return apply_energy_line(m,t,axis,start,omega,work,compensation);
}

inline double solid_energy_line(const EnergyMesh& m,ArrayView<const double> ks,
        ArrayView<const double> hva,ArrayView<const double> hvb,
        ArrayView<const double> ta,ArrayView<const double> tb,ArrayView<double> ts,
        ArrayView<const double> source,std::size_t axis,std::size_t start,
        double omega,EnergyLineScratch& work,ArrayView<double> compensation={}) {
    check_line_workspace(m,axis,omega,work,compensation);
    const ArrayView<const double> temperature{ts.data,ts.size};
    for(std::size_t j=0;j<m.count[axis];++j) {
        const auto p=start+j*m.stride[axis];
        const auto row=solid_energy_defect_row(m,ks,hva,hvb,ta,tb,temperature,source,p);
        append_line_row(work,j,row.diagonal,-row.neighbor[2*axis],
            -row.neighbor[2*axis+1],row.rhs);
    }
    return apply_energy_line(m,ts,axis,start,omega,work,compensation);
}

template<class Phase>
std::size_t dominant_diffusion_axis(const EnergyMesh& m,const Phase& a,
        const Phase& b,ArrayView<const double> ks) {
    std::array<double,3> score{};
    for(std::size_t p=0;p<m.cells();++p) {
        const auto c=m.coord(p);
        for(std::size_t axis=0;axis<3;++axis) if(c[axis]+1<m.count[axis]) {
            const auto q=p+m.stride[axis];
            const double dl=.5*m.width[axis][c[axis]],dr=.5*m.width[axis][c[axis]+1];
            score[axis]+=m.face_area(axis,c)*(
                diffusion_conductance(effective_K(a,p),effective_K(a,q),dl,dr)
                +diffusion_conductance(effective_K(b,p),effective_K(b,q),dl,dr)
                +diffusion_conductance(ks[p],ks[q],dl,dr));
        }
    }
    for(double s:score) if(!std::isfinite(s)) throw std::domain_error("nonfinite energy line axis score");
    return std::max_element(score.begin(),score.end())-score.begin();
}

} // namespace tpmshx::detail
