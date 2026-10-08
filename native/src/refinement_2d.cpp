#include "tpmshx/refinement_2d.hpp"
#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace tpmshx {
namespace {
using Vector=std::vector<double>;
std::size_t product(std::size_t a,std::size_t b) {
    if (!a || !b || a>std::numeric_limits<std::size_t>::max()/b)
        throw std::invalid_argument("invalid refinement extent");
    return a*b;
}
void extent(ArrayView<const double> a,std::size_t n) {
    if (!a.data || a.size!=n) throw std::invalid_argument("refinement field extent mismatch");
}
void widths(ArrayView<const double> a) {
    if (!a.data || !a.size) throw std::invalid_argument("empty refinement widths");
    for (std::size_t i=0;i<a.size;++i)
        if (!std::isfinite(a[i]) || a[i]<=0) throw std::invalid_argument("invalid refinement cell width");
}
Vector edges(ArrayView<const double> w) {
    widths(w);
    if (w.size==std::numeric_limits<std::size_t>::max()) throw std::invalid_argument("refinement edge extent overflow");
    Vector result(w.size+1,0);
    for (std::size_t i=0;i<w.size;++i) {
        result[i+1]=result[i]+w[i];
        if (!std::isfinite(result[i+1])) throw std::invalid_argument("nonfinite refinement domain extent");
    }
    return result;
}
Vector centers(ArrayView<const double> w) {
    auto values=edges(w); Vector result(w.size);
    for (std::size_t i=0;i<w.size;++i) {
        result[i]=values[i+1]-w[i]/2;
        if (i && result[i]<=result[i-1]) throw std::invalid_argument("refinement centres must be strictly ascending");
    }
    return result;
}
struct Location { std::size_t lo,hi; double fraction; };
Location locate_linear(const Vector& coordinate,double x) {
    if (coordinate.size()==1) return {0,0,0};
    const auto it=std::upper_bound(coordinate.begin(),coordinate.end(),x);
    const auto low=it==coordinate.begin() ? 0U : std::min(static_cast<std::size_t>(it-coordinate.begin()-1),coordinate.size()-2);
    return {low,low+1,(x-coordinate[low])/(coordinate[low+1]-coordinate[low])};
}
// NumPy interp's piecewise linear form, endpoint clamps and nonfinite-value
// recovery. Coordinates here are physical cumulative edges, not cell centres.
template<class Value> double interp(const Vector& coordinate,Value value,double x) {
    if (x<coordinate.front()) return value(0);
    if (x>coordinate.back()) return value(coordinate.size()-1);
    const auto it=std::upper_bound(coordinate.begin(),coordinate.end(),x);
    const auto low=it==coordinate.begin() ? 0U : static_cast<std::size_t>(it-coordinate.begin()-1);
    if (low+1==coordinate.size() || x==coordinate[low]) return value(low);
    const double slope=(value(low+1)-value(low))/(coordinate[low+1]-coordinate[low]);
    double result=std::fma(slope,x-coordinate[low],value(low));
    if (std::isnan(result)) {
        result=std::fma(slope,x-coordinate[low+1],value(low+1));
        if (std::isnan(result) && value(low)==value(low+1)) result=value(low);
    }
    return result;
}
bool same_domain(double a,double b) { return std::abs(a-b)<=1e-15+1e-12*std::abs(b); }
Vector overlaps(const Vector& coarse,const Vector& fine) {
    const auto nc=coarse.size()-1,nf=fine.size()-1; Vector result(product(nc,nf));
    for (std::size_t f=0;f<nf;++f) for (std::size_t c=0;c<nc;++c)
        result[f*nc+c]=std::max(0.0,std::min(fine[f+1],coarse[c+1])-std::max(fine[f],coarse[c]));
    return result;
}
}

Vector split_refinement_cells(ArrayView<const double> w) {
    widths(w); Vector result(product(w.size,2)); double end=0,position=0;
    for (std::size_t i=0;i<w.size;++i) {
        end+=w[i]; result[2*i]=w[i]/2; position+=result[2*i];
        result[2*i+1]=end-position; position+=result[2*i+1];
    }
    return result;
}

Vector refine_cell_field_2d(ArrayView<const double> dx,ArrayView<const double> dy,
    ArrayView<const double> fine_dx,ArrayView<const double> fine_dy,ArrayView<const double> field) {
    extent(field,product(dx.size,dy.size));
    const auto x=centers(dx),y=centers(dy),xf=centers(fine_dx),yf=centers(fine_dy);
    std::vector<Location> lx,ly;
    for (double point:xf) lx.push_back(locate_linear(x,point));
    for (double point:yf) ly.push_back(locate_linear(y,point));
    Vector result(product(xf.size(),yf.size()));
    for (std::size_t i=0;i<xf.size();++i) for (std::size_t j=0;j<yf.size();++j) {
        const auto a=lx[i],b=ly[j]; const double u=a.fraction,v=b.fraction;
        const auto value=[&](std::size_t p,std::size_t q) { return field[p*dy.size+q]; };
        double out;
        if (x.size()==1 && y.size()==1) out=value(0,0);
        else if (x.size()==1) out=std::fma(value(0,b.lo),1-v,value(0,b.hi)*v);
        else if (y.size()==1) out=std::fma(value(a.lo,0),1-u,value(a.hi,0)*u);
        else {
            // The locked SciPy RGI kernel contracts each addition of the
            // next weighted corner; keep that local policy explicit.
            out=value(a.lo,b.lo)*(1-u)*(1-v);
            out=std::fma(value(a.lo,b.hi)*(1-u),v,out);
            out=std::fma(value(a.hi,b.lo)*u,1-v,out);
            out=std::fma(value(a.hi,b.hi)*u,v,out);
        }
        result[i*yf.size()+j]=out;
    }
    return result;
}

std::array<Vector,2> prolong_mass_faces_2d(const std::array<ArrayView<const double>,2>& mass,
    ArrayView<const double> dx,ArrayView<const double> dy,ArrayView<const double> fine_dx,ArrayView<const double> fine_dy) {
    const auto x=edges(dx),y=edges(dy); auto xf=edges(fine_dx),yf=edges(fine_dy);
    if (!same_domain(x.back(),xf.back()) || !same_domain(y.back(),yf.back()))
        throw std::invalid_argument("mass prolongation requires the same physical domain");
    xf.back()=x.back(); yf.back()=y.back();
    extent(mass[0],product(x.size(),dy.size)); extent(mass[1],product(dx.size,y.size()));
    const auto overlap_x=overlaps(x,xf),overlap_y=overlaps(y,yf);
    std::array<Vector,2> result{Vector(product(xf.size(),fine_dy.size),0),Vector(product(fine_dx.size,yf.size()),0)};
    Vector jx(product(xf.size(),dy.size)),jy(product(dx.size,yf.size()));
    for (std::size_t i=0;i<xf.size();++i) for (std::size_t j=0;j<dy.size;++j)
        jx[i*dy.size+j]=interp(x,[&](std::size_t p) { return mass[0][p*dy.size+j]; },xf[i])/dy[j];
    for (std::size_t i=0;i<dx.size;++i) for (std::size_t j=0;j<yf.size();++j)
        jy[i*yf.size()+j]=interp(y,[&](std::size_t p) { return mass[1][i*y.size()+p]; },yf[j])/dx[i];
    for (std::size_t i=0;i<xf.size();++i) for (std::size_t j=0;j<fine_dy.size;++j)
        for (std::size_t c=0;c<dy.size;++c) result[0][i*fine_dy.size+j]+=jx[i*dy.size+c]*overlap_y[j*dy.size+c];
    for (std::size_t i=0;i<fine_dx.size;++i) for (std::size_t j=0;j<yf.size();++j)
        for (std::size_t c=0;c<dx.size;++c) result[1][i*yf.size()+j]+=overlap_x[i*dx.size+c]*jy[c*yf.size()+j];
    return result;
}

Vector refine_inlet_capacity(ArrayView<const double> coarse_widths,ArrayView<const double> fine_widths,
    ArrayView<const double> capacity) {
    const auto coarse=edges(coarse_widths),fine=edges(fine_widths); extent(capacity,coarse_widths.size);
    Vector cumulative(coarse.size(),0);
    for (std::size_t i=0;i<capacity.size;++i) cumulative[i+1]=cumulative[i]+capacity[i];
    Vector result(fine_widths.size); double previous=interp(coarse,[&](std::size_t p) { return cumulative[p]; },fine[0]);
    for (std::size_t i=0;i<fine_widths.size;++i) {
        const double current=interp(coarse,[&](std::size_t p) { return cumulative[p]; },fine[i+1]);
        result[i]=current-previous; previous=current;
    }
    return result;
}
}  // namespace tpmshx
