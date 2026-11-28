// Derived from scikit-image 0.26.0. See THIRD_PARTY_NOTICES.md for source and licenses.
#include "marching_cubes.hpp"
#include "mc_luts.hpp"
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <limits>
#include <stdexcept>
#include <tuple>
#include <utility>

namespace tpmshx::geometry::marching_cubes {
namespace {
constexpr double epsilon = 0x1p-52;
constexpr int edge_x[12][2] = {{0,1},{1,1},{1,0},{0,0},{0,1},{1,1},{1,0},{0,0},{0,0},{1,1},{1,1},{0,0}};
constexpr int edge_y[12][2] = {{0,0},{0,1},{1,1},{1,0},{0,0},{0,1},{1,1},{1,0},{0,0},{0,0},{1,1},{1,1}};
constexpr int edge_z[12][2] = {{0,0},{0,0},{0,0},{0,0},{1,1},{1,1},{1,1},{1,1},{0,1},{0,1},{0,1},{0,1}};
double dabs(double value) { return value >= 0. ? value : -value; }

struct Cell {
    int nx, x=0, y=0, z=0, index=0;
    std::array<double, 8> v{}, vv{};
    std::array<double, 3> center{};
    bool center_ready=false;
    std::vector<int> layer1, layer2;
    int* layer=nullptr;
    std::vector<std::array<float, 3>> vertices;
    std::vector<int> faces;

    Cell(int width, int height)
        : nx(width), layer1(static_cast<std::size_t>(width)*height*4, -1),
          layer2(layer1.size(), -1) {}

    void new_z_value() {
        layer1.swap(layer2);
        std::fill(layer2.begin(), layer2.end(), -1);
    }
    void set_cube(double level, int px, int py, int pz,
                  const std::array<double, 8>& corners) {
        x=px; y=py; z=pz; index=0; center_ready=false;
        for (int i=0; i<8; ++i) {
            v[i]=corners[i]-level;
            if (v[i]>0.) index += 1<<i;
        }
    }
    void prepare() {
        vv={v[0],v[1],v[3],v[2],v[4],v[5],v[7],v[6]};
    }
    int cache_index(int edge) {
        int i=nx*y+x, j=0;
        if (edge<8) {
            if (edge<4) layer=layer1.data();
            else { edge-=4; layer=layer2.data(); }
            if (edge==1) { i+=1; j=1; }
            else if (edge==2) i+=nx;
            else if (edge==3) j=1;
        } else if (edge<12) {
            layer=layer1.data(); j=2;
            if (edge==9) i+=1;
            else if (edge==10) i+=nx+1;
            else if (edge==11) i+=nx;
        } else { layer=layer1.data(); j=3; }
        return 4*i+j;
    }
    void calculate_center() {
        const double v0=1./(epsilon+dabs(v[0])), v1=1./(epsilon+dabs(v[1]));
        const double v2=1./(epsilon+dabs(v[2])), v3=1./(epsilon+dabs(v[3]));
        const double v4=1./(epsilon+dabs(v[4])), v5=1./(epsilon+dabs(v[5]));
        const double v6=1./(epsilon+dabs(v[6])), v7=1./(epsilon+dabs(v[7]));
        double fx=0., fy=0., fz=0., ff=0.;
        fx+=0.*v0; fy+=0.*v0; fz+=0.*v0; ff+=v0;
        fx+=1.*v1; fy+=0.*v1; fz+=0.*v1; ff+=v1;
        fx+=1.*v2; fy+=1.*v2; fz+=0.*v2; ff+=v2;
        fx+=0.*v3; fy+=1.*v3; fz+=0.*v3; ff+=v3;
        fx+=0.*v4; fy+=0.*v4; fz+=1.*v4; ff+=v4;
        fx+=1.*v5; fy+=0.*v5; fz+=1.*v5; ff+=v5;
        fx+=1.*v6; fy+=1.*v6; fz+=1.*v6; ff+=v6;
        fx+=0.*v7; fy+=1.*v7; fz+=1.*v7; ff+=v7;
        center={x+1.*fx/ff, y+1.*fy/ff, z+1.*fz/ff};
        center_ready=true;
    }
    void add_edge(int edge) {
        const int slot=cache_index(edge);
        int vertex=layer[slot];
        if (edge==12 && !center_ready) calculate_center();
        if (vertex<0) {
            std::array<double, 3> point;
            if (edge==12) point=center;
            else {
                const int dx1=edge_x[edge][0], dx2=edge_x[edge][1];
                const int dy1=edge_y[edge][0], dy2=edge_y[edge][1];
                const int dz1=edge_z[edge][0], dz2=edge_z[edge][1];
                const double w1=1./(epsilon+dabs(vv[dz1*4+dy1*2+dx1]));
                const double w2=1./(epsilon+dabs(vv[dz2*4+dy2*2+dx2]));
                double fx=0., fy=0., fz=0., ff=0.;
                fx+=static_cast<double>(dx1)*w1; fy+=static_cast<double>(dy1)*w1;
                fz+=static_cast<double>(dz1)*w1; ff+=w1;
                fx+=static_cast<double>(dx2)*w2; fy+=static_cast<double>(dy2)*w2;
                fz+=static_cast<double>(dz2)*w2; ff+=w2;
                point={static_cast<double>(x)+1.*fx/ff,
                       static_cast<double>(y)+1.*fy/ff,
                       static_cast<double>(z)+1.*fz/ff};
            }
            vertex=static_cast<int>(vertices.size());
            vertices.push_back({static_cast<float>(point[0]),static_cast<float>(point[1]),static_cast<float>(point[2])});
            layer[slot]=vertex;
        }
        faces.push_back(vertex);
    }
    void add_triangles(const lut::Lut& table, int row, int count) {
        prepare();
        for (int i=0; i<count; ++i)
            for (int j=0; j<3; ++j) add_edge(table.get2(row, i*3+j));
    }
    void add_triangles2(const lut::Lut& table, int row, int subrow, int count) {
        prepare();
        for (int i=0; i<count; ++i)
            for (int j=0; j<3; ++j) add_edge(table.get3(row, subrow, i*3+j));
    }
};

#include "mc_cases.inc"

// NumPy's contiguous real pairwise reduction uses eight lanes and 128 items.
template<class Real>
Real pairwise_sum(const Real* values, std::size_t count) {
    if (count<8) {
        Real result=-0.;
        for (std::size_t i=0; i<count; ++i) result+=values[i];
        return result;
    }
    if (count<=128) {
        Real r[8]={values[0],values[1],values[2],values[3],values[4],values[5],values[6],values[7]};
        std::size_t i=8;
        for (; i<count-(count%8); i+=8)
            for (int lane=0; lane<8; ++lane) r[lane]+=values[i+lane];
        Real result=((r[0]+r[1])+(r[2]+r[3]))+((r[4]+r[5])+(r[6]+r[7]));
        for (; i<count; ++i) result+=values[i];
        return result;
    }
    std::size_t half=count/2;
    half-=half%8;
    return pairwise_sum(values,half)+pairwise_sum(values+half,count-half);
}
template<class Real>
double mesh_area(const Mesh& surface, const std::array<double,3>& spacing) {
    std::vector<std::array<Real,3>> scaled;
    scaled.reserve(surface.vertices.size());
    for (const auto& point:surface.vertices)
        scaled.push_back({static_cast<Real>(static_cast<double>(point[0])*spacing[0]),
                          static_cast<Real>(static_cast<double>(point[1])*spacing[1]),
                          static_cast<Real>(static_cast<double>(point[2])*spacing[2])});
    std::vector<Real> doubled_areas;
    doubled_areas.reserve(surface.faces.size());
    for (const auto& face:surface.faces) {
        const auto& p0=scaled[face[0]]; const auto& p1=scaled[face[1]]; const auto& p2=scaled[face[2]];
        const std::array<Real,3> a={p0[0]-p1[0],p0[1]-p1[1],p0[2]-p1[2]};
        const std::array<Real,3> b={p0[0]-p2[0],p0[1]-p2[1],p0[2]-p2[2]};
        const Real c0=a[1]*b[2]-a[2]*b[1], c1=a[2]*b[0]-a[0]*b[2], c2=a[0]*b[1]-a[1]*b[0];
        doubled_areas.push_back(std::sqrt((c0*c0+c1*c1)+c2*c2));
    }
    // NumPy adds its subtotal to +0, before division in the same scalar type.
    const Real total=Real(0)+pairwise_sum(doubled_areas.data(),doubled_areas.size());
    return static_cast<double>(total/Real(2));
}
}  // namespace

Mesh mesh(const float* volume, std::size_t Nx, std::size_t Ny, std::size_t Nz,
          double level) {
    const auto limit=static_cast<std::size_t>(std::numeric_limits<int>::max());
    if (!volume || Nx<2 || Ny<2 || Nz<2 || Nx>limit || Ny>limit || Nz>limit || Ny>limit/4/Nz)
        throw std::invalid_argument("volume requires a nonempty C-order 3D grid with bounded dimensions");
    // Internal Lewiner x runs along the last NumPy axis.
    const int nx=static_cast<int>(Nz), ny=static_cast<int>(Ny), nz=static_cast<int>(Nx);
    float minimum=volume[0], maximum=volume[0];
    for (std::size_t i=0; i<Nx*Ny*Nz; ++i) {
        if (std::isnan(volume[i])) { minimum=maximum=volume[i]; break; }
        minimum=std::min(minimum,volume[i]); maximum=std::max(maximum,volume[i]);
    }
    const float range_level=static_cast<float>(level);
    if (range_level<minimum || range_level>maximum)
        throw std::invalid_argument("Surface level must be within volume data range.");
    const auto at=[&](int z, int y, int x) -> double {
        return volume[(static_cast<std::size_t>(z)*Ny+y)*Nz+x];
    };
    Cell cell(nx,ny);
    for (int z=0; z<nz-1; ++z) {
        cell.new_z_value();
        for (int y=0; y<ny-1; ++y)
            for (int x=0; x<nx-1; ++x) {
                cell.set_cube(level,x,y,z,{at(z,y,x),at(z,y,x+1),at(z,y+1,x+1),at(z,y+1,x),
                    at(z+1,y,x),at(z+1,y,x+1),at(z+1,y+1,x+1),at(z+1,y+1,x)});
                const int case_id=lut::CASES.get2(cell.index,0);
                if (case_id>0) big_switch(cell,case_id,lut::CASES.get2(cell.index,1));
            }
    }
    if (cell.vertices.empty()) throw std::runtime_error("No surface found at the given iso value.");
    Mesh result;
    result.vertices.reserve(cell.vertices.size());
    for (const auto& point:cell.vertices) result.vertices.push_back({point[2],point[1],point[0]});
    result.faces.reserve(cell.faces.size()/3);
    for (std::size_t i=0; i<cell.faces.size(); i+=3)
        result.faces.push_back({cell.faces[i+2],cell.faces[i+1],cell.faces[i]});
    return result;
}

double area(const float* volume, std::size_t Nx, std::size_t Ny, std::size_t Nz,
            double level, const std::array<double, 3>& spacing) {
    const auto surface=mesh(volume,Nx,Ny,Nz,level);
    if (spacing[0]==1. && spacing[1]==1. && spacing[2]==1.)
        return mesh_area<float>(surface,spacing);
    return mesh_area<double>(surface,spacing);
}
}  // namespace tpmshx::geometry::marching_cubes
