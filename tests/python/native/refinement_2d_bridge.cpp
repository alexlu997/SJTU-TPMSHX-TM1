#include "tpmshx/refinement_2d.hpp"
#include "tpmshx/thermal_c_api.h"
#include <algorithm>
#include <cstdio>
#include <stdexcept>
extern "C" TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL test_refinement_2d(
    int operation,double** arrays,const size_t* sizes,char* error,size_t error_size) {
    using namespace tpmshx;
    try {
        const auto v=[&](size_t p) { return ArrayView<const double>{arrays[p],sizes[p]}; };
        const auto put=[&](size_t p,const std::vector<double>& output) {
            if (!arrays[p] || sizes[p]!=output.size()) throw std::invalid_argument("refinement test output extent");
            std::copy(output.begin(),output.end(),arrays[p]);
        };
        if (operation==0) put(6,split_refinement_cells(v(0)));
        else if (operation==1) put(6,refine_cell_field_2d(v(0),v(1),v(2),v(3),v(4)));
        else if (operation==2) {
            const auto output=prolong_mass_faces_2d({v(4),v(5)},v(0),v(1),v(2),v(3));
            put(6,output[0]); put(7,output[1]);
        } else if (operation==3) put(6,refine_inlet_capacity(v(0),v(2),v(4)));
        else throw std::invalid_argument("invalid refinement test operation");
        if (error_size) error[0]='\0'; return 0;
    } catch (const std::exception& e) {
        if (error_size) std::snprintf(error,error_size,"%s",e.what()); return 1;
    }
}
