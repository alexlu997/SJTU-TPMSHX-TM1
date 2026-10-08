#pragma once

#include "energy_fv_rows.hpp"
#include <algorithm>
#include <cmath>

namespace tpmshx::detail {

// Mass already includes density, side void, opening and physical face area.
// Interpolate cp by cell-centre distance; only known actual inlet flow uses
// inlet cp. Preserve every signed mass face without balancing or projection.
inline std::array<std::vector<double>,3> temperature_capacity_faces(
    const GridView& grid,const std::array<ArrayView<const double>,3>& mass,
    ArrayView<const double> cp,double inlet_cp,const TemperatureBoundary& boundary) {
    const EnergyMesh mesh(grid);
    const std::array<std::size_t,3> sizes{(grid.nx+1)*grid.ny*grid.nz,
        grid.nx*(grid.ny+1)*grid.nz,grid.nx*grid.ny*(grid.nz+1)};
    if(!cp.data||cp.size!=mesh.cells()||!std::isfinite(inlet_cp)||inlet_cp<=0.)
        throw std::invalid_argument("invalid temperature face cp");
    for(std::size_t p=0;p<cp.size;++p)
        if(!std::isfinite(cp[p])||cp[p]<=0.) throw std::invalid_argument("invalid temperature cell cp");
    std::array<std::vector<double>,3> result;
    for(std::size_t axis=0;axis<3;++axis) {
        if(!mass[axis].data||mass[axis].size!=sizes[axis])
            throw std::invalid_argument("invalid temperature mass face extent");
        result[axis].resize(sizes[axis]);
        for(std::size_t p=0;p<mesh.cells();++p) {
            const auto c=mesh.coord(p);
            for(int sign:{-1,1}) {
                if(sign<0&&c[axis]>0) continue;
                const auto face=mesh.face(axis,p,sign);
                const double m=mass[axis][face];
                if(!std::isfinite(m)) throw std::invalid_argument("nonfinite temperature mass face");
                double value=cp[p];
                if(mesh.inside(c,axis,sign)) {
                    const auto q=mesh.neighbor(p,axis,sign);
                    const double here=mesh.width[axis][c[axis]],next=mesh.width[axis][c[axis]+1];
                    value=cp[p]+(here/(here+next))*(cp[q]-cp[p]);
                } else if(sign*m<0.&&known_inlet(mesh,boundary,c,axis,sign)) value=inlet_cp;
                result[axis][face]=m*value;
                if(!std::isfinite(result[axis][face]))
                    throw std::domain_error("nonfinite temperature capacity face");
            }
        }
    }
    return result;
}

// A nonlinear temperature reconstruction exists only where a transported
// interior face has at least three cells along that axis. This depends only
// on the frozen operator, never the current iterate or a residual threshold.
inline bool temperature_second_order_active(const EnergyMesh& mesh,
        const std::array<ArrayView<const double>,3>& capacity) {
    for(std::size_t axis=0;axis<3;++axis) {
        if(mesh.count[axis]<3) continue;
        for(std::size_t p=0;p<mesh.cells();++p)
            if(mesh.coord(p)[axis]+1<mesh.count[axis]
                &&capacity[axis][mesh.face(axis,p,1)]!=0.) return true;
    }
    return false;
}

struct TemperatureFaceCorrection {
    double value=0.,derivative=0.;
    std::size_t low=0,high=0;
};

// The physical value keeps the original evaluation order. The derivative is
// only the selected active branch; it is never substituted for the value.
template<bool Derivative=false>
inline TemperatureFaceCorrection temperature_face_correction(const EnergyMesh& mesh,
        std::size_t axis,std::size_t p,double C,ArrayView<const double> temperature) {
    const auto c=mesh.coord(p);const auto position=c[axis];
    if(position+1==mesh.count[axis]||mesh.count[axis]<3||C==0.) return {};
    const auto upos=C>=0. ? position:position+1;
    const auto up=C>=0. ? p:p+mesh.stride[axis];
    const auto width=mesh.width[axis];
    const auto middle=upos==0 ? up+mesh.stride[axis]
        : upos+1==mesh.count[axis] ? up-mesh.stride[axis]:up;
    const auto position_middle=upos==0 ? 1U
        : upos+1==mesh.count[axis] ? upos-1:upos;
    const double dl=.5*(width[position_middle-1]+width[position_middle]);
    const double dr=.5*(width[position_middle]+width[position_middle+1]);
    const double left=(temperature[middle]-temperature[middle-mesh.stride[axis]])/dl;
    const double right=(temperature[middle+mesh.stride[axis]]-temperature[middle])/dr;
    if(!(left*right>0.)) return {};
    const bool take_left=std::abs(left)<=std::abs(right);
    const double slope=std::copysign(std::min(std::abs(left),std::abs(right)),left);
    const double value=C*slope*.5*width[upos]*(C>=0. ? 1.:-1.);
    if constexpr(Derivative)
        return {value,C/(take_left?dl:dr)*.5*width[upos]*(C>=0. ? 1.:-1.),
                take_left?middle-mesh.stride[axis]:middle,
                take_left?middle:middle+mesh.stride[axis]};
    else return {value,0.,0,0};
}

// QD/CC and conservative staggered temperature transport share exactly this
// physical-distance T-minmod reconstruction; callers own the freezing schedule.
// Callers provide independent writable
// full-face offsets; capacity is already the signed positive-axis face value.
// Exterior corrections are zero. At an upwind end cell, the two available
// one-sided interior slopes form the limiter; fewer than three cells give FOU.
inline void temperature_face_offsets(
    const EnergyMesh& mesh,
    const std::array<ArrayView<const double>,3>& capacity,
    ArrayView<const double> temperature,
    const std::array<ArrayView<double>,3>& offset) {
    for(std::size_t axis=0;axis<3;++axis) {
        std::fill_n(offset[axis].data,offset[axis].size,0.);
        for(std::size_t p=0;p<mesh.cells();++p) {
            const auto c=mesh.coord(p);
            if(c[axis]+1==mesh.count[axis]) continue;
            const auto face=mesh.face(axis,p,1);
            offset[axis][face]=temperature_face_correction(mesh,axis,p,
                capacity[axis][face],temperature).value;
        }
    }
}

} // namespace tpmshx::detail
