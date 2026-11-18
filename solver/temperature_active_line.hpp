#pragma once
#include "temperature_faces.hpp"
#include <memory>
#include <string>
#include <cmath>
#include <Eigen/SparseLU>

namespace tpmshx::detail {

struct ActiveLineWork {
    using Sparse=Eigen::SparseMatrix<double,Eigen::ColMajor,int>;
    using Solver=Eigen::SparseLU<Sparse,Eigen::COLAMDOrdering<int>>;
    struct Layout {
        std::size_t n;
        Sparse matrix;
        Solver solver;
        Eigen::VectorXd solution;
        explicit Layout(std::size_t count):n(count),matrix(static_cast<int>(n),static_cast<int>(n)),solution(n) {
            int nnz=0;for(std::size_t j=0;j<n;++j)nnz+=static_cast<int>(std::min(n,j+3)-(j>2?j-2:0));
            matrix.reserve(nnz);
            for(std::size_t j=0;j<n;++j){matrix.startVec(j);for(std::size_t i=(j>2?j-2:0);i<std::min(n,j+3);++i)matrix.insertBack(i,j)=0.;}
            matrix.finalize();matrix.makeCompressed();solver.setPivotThreshold(1.0);solver.analyzePattern(matrix);
        }
    };
    std::vector<double> band,rhs;
    std::array<std::unique_ptr<Layout>,2> layouts;
    explicit ActiveLineWork(std::size_t n):band(7*n),rhs(n){}
    void clear(std::size_t n){std::fill_n(band.data(),7*n,0.);}
    void add(std::size_t i,std::size_t j,double value){
        if(i>j+2||j>i+2)throw std::logic_error("active temperature derivative exceeds line bandwidth");
        band[4+i-j+7*j]+=value;
    }
    void solve(std::size_t count){
        Layout* selected=nullptr;
        for(auto& layout:layouts)if(layout&&layout->n==count){selected=layout.get();break;}
        if(!selected)for(auto& layout:layouts)if(!layout){layout=std::make_unique<Layout>(count);selected=layout.get();break;}
        if(!selected)throw std::logic_error("active temperature has more than two line layouts");
        auto& w=*selected;
        for(std::size_t j=0;j<count;++j){
            if(!std::isfinite(rhs[j]))throw std::domain_error("active temperature Eigen nonfinite rhs");
            for(int p=w.matrix.outerIndexPtr()[j];p<w.matrix.outerIndexPtr()[j+1];++p){
                const double value=band[4+w.matrix.innerIndexPtr()[p]-j+7*j];
                if(!std::isfinite(value))throw std::domain_error("active temperature Eigen nonfinite matrix");
                w.matrix.valuePtr()[p]=value;
            }
        }
        w.solver.factorize(w.matrix);
        if(w.solver.info()!=Eigen::Success)throw std::domain_error("active temperature Eigen factor info="+std::to_string(static_cast<int>(w.solver.info()))+" "+w.solver.lastErrorMessage().c_str());
        const Eigen::Map<const Eigen::VectorXd> input(rhs.data(),count);
        w.solution=w.solver.solve(input);
        if(w.solver.info()!=Eigen::Success)throw std::domain_error("active temperature Eigen solve info="+std::to_string(static_cast<int>(w.solver.info()))+" "+w.solver.lastErrorMessage().c_str());
        for(std::size_t i=0;i<count;++i)if(!std::isfinite(w.solution[i]))throw std::domain_error("active temperature Eigen nonfinite solution");
        std::copy_n(w.solution.data(),count,rhs.data());
    }

};

template<class Phase>
double active_temperature_line(const tpmshx::detail::EnergyMesh& mesh,Phase& phase,
        tpmshx::ArrayView<double> temperature,tpmshx::ArrayView<const double> solid,
        std::size_t axis,std::size_t start,double alpha,ActiveLineWork& work) {
    using namespace tpmshx;using namespace tpmshx::detail;
    const auto count=mesh.count[axis],n=mesh.cells();const auto origin=mesh.coord(start);
    const ArrayView<const double> actual{temperature.data,n};
    work.clear(count);
    const auto column=[&](std::size_t p)->std::size_t {
        const auto c=mesh.coord(p);
        for(std::size_t a=0;a<3;++a) if(a!=axis&&c[a]!=origin[a]) return count;
        return c[axis];
    };
    for(std::size_t j=0;j<count;++j) {
        const auto p=start+j*mesh.stride[axis];const auto c=mesh.coord(p);
        std::array<TemperatureFaceCorrection,6> corrections{};
        for(std::size_t a=0;a<3;++a) for(int sign:{-1,1}) {
            const auto face=mesh.face(a,p,sign);
            if(mesh.inside(c,a,sign)) {
                const auto low=sign>0 ? p:mesh.neighbor(p,a,sign);
                corrections[2*a+(sign>0)]=temperature_face_correction<true>(mesh,a,low,
                    phase.energy.faces.capacity[a][face],actual);
            }
            phase.offset[a][face]=corrections[2*a+(sign>0)].value;
        }
        // All six actual face values and the branches above refer to exactly
        // this unchanged line state. The line is written only after assembly.
        const auto row=fluid_energy_defect_row(mesh,phase.energy,actual,solid,p);
        work.rhs[j]=row.rhs;work.add(j,j,row.diagonal);
        for(int sign:{-1,1}) if(mesh.inside(c,axis,sign))
            work.add(j,sign<0?j-1:j+1,-row.neighbor[2*axis+(sign>0)]);
        for(std::size_t a=0;a<3;++a) for(int sign:{-1,1}) {
            const auto& correction=corrections[2*a+(sign>0)];
            if(correction.derivative==0.) continue;
            const auto lo=column(correction.low),hi=column(correction.high);
            if(lo<count) work.add(j,lo,-sign*correction.derivative);
            if(hi<count) work.add(j,hi,sign*correction.derivative);
        }
    }
    work.solve(count);
    double change=0.;
    for(std::size_t j=0;j<count;++j) {
        const auto p=start+j*mesh.stride[axis];
        work.rhs[j]=temperature[p]+alpha*work.rhs[j];
        if(!std::isfinite(work.rhs[j])) throw std::domain_error("nonfinite active temperature line");
    }
    for(std::size_t j=0;j<count;++j) {
        const auto p=start+j*mesh.stride[axis];
        change=std::max(change,std::abs(work.rhs[j]-temperature[p]));temperature[p]=work.rhs[j];
    }
    return change;
}

} // namespace tpmshx::detail
