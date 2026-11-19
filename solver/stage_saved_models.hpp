#pragma once
#include "tpmshx/model_coefficients.hpp"
#include "tpmshx/preparation_case_c_api.h"
#include "../preprocess/preparation_nu.hpp"

namespace tpmshx::stages {
inline std::string_view text_view(tpmshx_preparation_text_v1 text) {
    return text.size ? std::string_view(text.data,text.size) : std::string_view{};
}

inline bool same_nu(const tpmshx_preparation_sco2_nu_v2& a,const tpmshx_preparation_sco2_nu_v2& b) {
    for (size_t i=0;i<2;++i)
        if (a.have_alpha[i]!=b.have_alpha[i] || (a.have_alpha[i] && a.alpha[i]!=b.alpha[i])) return false;
    return a.mode==b.mode && text_view(a.parameter_version)==text_view(b.parameter_version)
        && text_view(a.source)==text_view(b.source) && text_view(a.applicability)==text_view(b.applicability);
}

inline void validate_saved_models(const tpmshx_preparation_model_ref_v1 (&refs)[4],
        const tpmshx_preparation_sco2_nu_v2& settings,const tpmshx_preparation_sco2_nu_v2 (&resource_nu)[2],
        const tpmshx_preparation_text_v1 (&resource_fluids)[2],tpmshx_preparation_text_v1 resource_topology,
        std::array<uint32_t,2> fluid_ids,uint32_t topology,bool three_d) {
    namespace models=tpmshx::model_coefficients;
    const char* fluids[]{"air","water","sco2","co2"};
    for (size_t i=0;i<4;++i) {
        const auto name=text_view(refs[i].name), version=text_view(refs[i].version);
        const bool valid=i<2 ? ((name=="fluid" && version==models::fluid_version) ||
                                (name=="co2_fluid" && version==models::co2_fluid_version))
            : i==2 ? ((name=="geometry" && version==models::geometry_version) ||
                      (name=="co2_geometry" && version==models::co2_geometry_version))
                   : name=="darcy_forchheimer" && version==models::darcy_forchheimer_version;
        if (!valid) throw std::invalid_argument("unknown model resource: "+std::string(name)+"@"+std::string(version));
    }
    for (const auto* nu:{&settings,&resource_nu[0],&resource_nu[1]}) {
        tpmshx::preparation::Sco2NuSelection selection;
        selection.mode=nu->mode;
        for (size_t i=0;i<2;++i) {
            if(nu->have_alpha[i]>1)throw std::invalid_argument("stage run option flags require 0 or 1");
            if (nu->have_alpha[i]) selection.alpha[i]=nu->alpha[i];
        }
        selection.parameter_version=text_view(nu->parameter_version);
        selection.source=text_view(nu->source);
        selection.applicability=text_view(nu->applicability);
        tpmshx::preparation::validate_nu(selection);
    }
    for (size_t side=0;side<2;++side) {
        const auto label=std::string(side?"B":"A");
        const auto fluid=text_view(resource_fluids[side]);
        if ((text_view(refs[side].name)=="co2_fluid")!=(fluid=="co2"))
            throw std::invalid_argument("CO2 requires its versioned fluid resource");
        const bool mismatch=fluid_ids[side]>3 || fluid!=fluids[fluid_ids[side]];
        if (three_d && mismatch)
            throw std::invalid_argument("prepared fluid "+label+" and model resource disagree");
        if (!same_nu(resource_nu[side],settings))
            throw std::invalid_argument("prepared Nu settings and fluid "+label+" resource disagree");
        if (mismatch)
            throw std::invalid_argument("prepared fluid "+label+" and its model resource disagree");
    }
    if (text_view(resource_topology)!=(topology==0?"Diamond":"Gyroid"))
        throw std::invalid_argument("prepared topology and Darcy-Forchheimer resource disagree");
}

}
