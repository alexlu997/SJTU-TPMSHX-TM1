#pragma once
#include "tpmshx/model_h_c_api.h"
#include "tpmshx/model_h_3d.hpp"
#include <algorithm>

// Borrowed C audit views. The caller owns both the C++ result and the
// finishing vector until all views are consumed. This does not assign a C
// owner handle; only the API owning the complete result can release it.
namespace tpmshx::model_h_c_views {
inline tpmshx_model_h_array_v1 owned(const std::vector<double>& x) { return {x.data(),x.size()}; }
inline void side_2d(tpmshx_model_h_side_2d_v1& out,const ModelHSideAudit2D& s) {
    out.q_advective=s.q_advective; out.inlet_conduction=s.inlet_conduction; out.exchange=s.exchange;
    out.residual_sum=s.residual_sum; out.residual_max=s.residual_max;
    out.linearized_sum=s.linearized_sum; out.linearized_max=s.linearized_max;
    out.defect_sum=s.defect_sum; out.defect_max=s.defect_max;
    out.mass_net=s.mass_net; out.mass_local_max=s.mass_local_max;
    out.mass_in=s.mass_in; out.mass_out=s.mass_out; out.normalization=s.normalization; out.cell_ratio=s.cell_ratio;
    out.unknown_inflow_faces=s.unknown_inflow_faces;
    std::copy(s.cp_coefficients.begin(),s.cp_coefficients.end(),out.cp_coefficients);
    for (std::size_t i=0;i<4;++i) {
        out.boundary_mass_out[i]=owned(s.boundary_mass_out[i]); out.boundary_h_out[i]=owned(s.boundary_h_out[i]);
    }
    for (std::size_t i=0;i<2;++i) out.h_faces[i]=owned(s.h_faces[i]);
    out.inlet_conduction_faces=owned(s.inlet_conduction_faces); out.residual=owned(s.residual);
    out.linearization_defect=owned(s.linearization_defect);
}
inline void plane(tpmshx_model_h_result_v1& out,std::vector<tpmshx_model_h_check_v1>& finishing,const ModelHResult2D& r) {
    out.dimension=2; out.stop=static_cast<uint32_t>(r.stop); out.iterations=r.iterations;
    out.residual=r.residual; out.q_b=r.q_b; out.audit_available=r.audit_available;
    if (!r.audit_available) return;
    const auto& s=r.audit; auto& a=out.plane;
    for (std::size_t i=0;i<2;++i) side_2d(a.sides[i],s.sides[i]);
    a.solid_sum=s.solid_sum; a.solid_max=s.solid_max; a.solid_cell_ratio=s.solid_cell_ratio;
    a.residual_sum=s.residual_sum; a.telescoping_error=s.telescoping_error;
    a.net_boundary_in=s.net_boundary_in; a.denominator=s.denominator;
    a.energy_imbalance=s.energy_imbalance; a.solid_imbalance=s.solid_imbalance;
    a.boundary_complete=s.boundary_complete; a.finite=s.finite; a.energy_ok=s.energy_ok;
    a.solid_ok=s.solid_ok; a.equations_ok=s.equations_ok; a.passed=s.passed;
    a.solid_residual=owned(s.solid_residual);
    for (const auto& check:r.finishing_checks)
        finishing.push_back({check.iterations,{check.passed,check.equations_ok,0,0,0,0}});
}
inline void side_3d(tpmshx_model_h_side_3d_v1& out,const ModelHSideAudit3D& s) {
    for (std::size_t i=0;i<6;++i) {
        const auto& f=s.boundaries[i];
        out.boundaries[i]={f.mass_out,f.enthalpy_out,f.unknown_mass_in,f.inlet_reverse_mass_out,
                           f.unknown_inflow_count,owned(f.enthalpy_faces)};
    }
    std::copy(s.cp_coefficients.begin(),s.cp_coefficients.end(),out.cp_coefficients);
    out.temperature_min=s.temperature_min; out.temperature_max=s.temperature_max; out.mass_net=s.mass_net;
    out.advective_in=s.advective_in; out.diffusion_in=s.diffusion_in;
    out.numerical_external_in=s.numerical_external_in; out.exchange=s.exchange; out.source=s.source;
    out.residual_sum=s.residual_sum; out.residual_max=s.residual_max; out.normalization=s.normalization;
    out.global_ratio=s.global_ratio; out.cell_ratio=s.cell_ratio; out.boundary_complete=s.boundary_complete;
    out.residual=owned(s.residual); out.inlet_diffusion=owned(s.inlet_diffusion);
}
inline void volume(tpmshx_model_h_result_v1& out,std::vector<tpmshx_model_h_check_v1>& finishing,const ModelHResult3D& r) {
    out.dimension=3; out.stop=static_cast<uint32_t>(r.stop); out.iterations=r.iterations;
    out.residual=r.residual; out.q_b=r.q_b; out.audit_available=r.audit_available; out.has_sources=r.has_sources;
    if (!r.audit_available) return;
    const auto& s=r.audit; auto& a=out.volume;
    for (std::size_t i=0;i<2;++i) side_3d(a.sides[i],s.sides[i]);
    a.volume=s.volume; a.numerical_external_in=s.numerical_external_in; a.explicit_source=s.explicit_source;
    a.solid_sum=s.solid_sum; a.solid_max=s.solid_max; a.full_residual_sum=s.full_residual_sum;
    a.telescoping_error=s.telescoping_error; a.ltne_source_ratio=s.ltne_source_ratio;
    a.boundary_complete=s.boundary_complete; a.passed=s.passed; a.solid_residual=owned(s.solid_residual);
    for (std::size_t i=0;i<6;++i) a.gates[i]=s.gates[i];
    for (const auto& check:r.finishing_checks) {
        tpmshx_model_h_check_v1 c{}; c.iterations=check.iterations;
        for (std::size_t i=0;i<6;++i) c.gates[i]=check.gates[i];
        finishing.push_back(c);
    }
}
} // namespace tpmshx::model_h_c_views
