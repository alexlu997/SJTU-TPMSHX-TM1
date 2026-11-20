#pragma once

#include "tpmshx/stage_run_c_api.h"

#include <algorithm>
#include <ostream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace tpmshx::stages {

inline void finish_execution(tpmshx_stage_execution_v1& out,const tpmshx_result_evidence_v1& result,
                             const tpmshx_stage_run_records_v1& records) {
    out.records=&records;
    out.unknown=std::string_view(result.thermal_mode)=="true_h"?"h":"T";
    out.last_main_model_h=out.model_h.count;
    if(std::string_view(result.thermal_mode)=="model_h" || result.thermal.temperature)
        for(size_t i=0;i<out.model_h.count;++i)
            if(!out.model_h.records[i].refined)out.last_main_model_h=i;
}

inline size_t add_scope_notice(std::vector<std::string>& notices,std::string message) {
    const auto existing=std::find(notices.begin(),notices.end(),message);
    if(existing!=notices.end())return static_cast<size_t>(existing-notices.begin());
    notices.push_back(std::move(message));
    return notices.size()-1;
}

inline void write_sco2_scope(std::ostream& message,double pressure) {
    message<<"; Nu uses scalar P_in="<<pressure<<" Pa. "
        "Joint qualification remains unverified: the old CFD evidence uses "
        "heating at Twall=Tref+50 K and period-2/3 bulk properties. "
        "The reported subset requires P>=10 MPa AND Tb>=Tpc(P)-2 K within "
        "that campaign; Tpc, joint Pr/P/T coverage, actual wall temperature "
        "and heating/cooling qualification are not established here. "
        "Pressure or Re-window membership alone is not a PASS.";
    if(pressure<10e6)
        message<<" P_in<10 MPa does not meet the subset necessary pressure condition.";
    if(pressure>15e6)
        message<<" P_in>15 MPa exceeds the old campaign pressure envelope (8/10/12/15 MPa).";
}

inline void capture_energy_relations(tpmshx_stage_run_records_v1& records,const tpmshx_result_evidence_v1& result) {
    const std::string_view mode=result.thermal_mode;
    const tpmshx_property_sample_v1* latest[2]{};
    for(size_t i=0;i<records.sampling.count;++i) {
        const auto& row=records.sampling.records[i];
        if(std::string_view(row.quantity)!="energy_relation" || std::string_view(row.stage)!="thermal")continue;
        if(row.side>1)throw std::invalid_argument("invalid energy sampling side");
        if(!latest[row.side] || row.outer_index>=latest[row.side]->outer_index)latest[row.side]=&row;
    }
    for(size_t i=0;i<2;++i) {
        auto& out=records.energy[i];
        out.solved=result.thermal.temperature?result.thermal.temperature->phases[i].solved:result.executed_sides[i].solved;
        if(!out.solved) {out.relation="prescribed_temperature";continue;}
        bool eos=mode=="true_h" || mode=="conservative_energy";
        bool integral=mode=="model_h" || result.thermal.temperature;
        if(const auto* row=latest[i]) {
            const std::string_view operation=row->operation;
            eos=std::string_view(row->provider)=="HEOS" && operation=="local_evaluation";
            integral=operation=="integral_cp_T";
            if(!eos && !integral && operation!="frozen_capacity_temperature")
                throw std::invalid_argument("unsupported executed thermal sampling operation");
        }
        out.relation=eos?"eos_h_TP":integral?"integral_cp_T":"capacity_temperature";
        out.provider=eos?"HEOS":"model_resource";
        out.state_update=eos?(mode=="conservative_energy"?"HEOS_PT":"T(h,P)"):
                             integral?(mode=="true_h"?"T(h)":"h(T)"):"model_relation";
        if(eos) {
            const std::string_view fluid=result.executed_sides[i].fluid;
            out.eos_fluid=fluid=="air"?"Air":fluid=="water"?"Water":"CO2";
        }
    }
}

inline void range_coordinates(const size_t* shape, size_t rank, size_t flat, size_t* coordinates) {
    for (size_t axis = rank; axis > 0; --axis) {
        const size_t extent = shape[axis - 1];
        if (!extent) throw std::invalid_argument("captured range has an empty axis");
        coordinates[axis - 1] = flat % extent;
        flat /= extent;
    }
    if (flat) throw std::invalid_argument("range observation index exceeds its grid");
}

struct RangeStorage {
    std::vector<std::string> source;
    std::vector<const char*> source_view;
    std::string side,stage,layout,quantity,unit;
    std::vector<size_t> shape,minimum_index,maximum_index;
    double minimum=0.,maximum=0.;
    tpmshx_stage_range_sample_v1 value{};
    void finish(bool finite,size_t min_index,size_t max_index,bool captured=true) {
        for(const auto& s:source)source_view.push_back(s.c_str());
        value.captured=captured?1:0;value.side=side.c_str();value.stage=stage.c_str();value.layout=layout.c_str();
        value.quantity=quantity.c_str();value.unit=unit.c_str();
        value.constraint=!source.empty() && source[0]=="geometry"?"hard_bounds":nullptr;
        value.source=source_view.data();value.source_count=source_view.size();
        value.shape=shape.data();value.rank=shape.size();
        if(captured && finite) {
            value.minimum=&minimum;value.maximum=&maximum;
            minimum_index.resize(shape.size());maximum_index.resize(shape.size());
            range_coordinates(shape.data(),shape.size(),min_index,minimum_index.data());
            range_coordinates(shape.data(),shape.size(),max_index,maximum_index.data());
            value.minimum_index=minimum_index.data();value.maximum_index=maximum_index.data();
        }
    }
};

// The raw run owns the samples. The stage owns the labels and index views.
struct StageRangeRecords {
    std::vector<std::string> labels;
    std::vector<tpmshx_stage_range_record_v1> rows;

    void capture(const tpmshx_range_observation_v1* samples,size_t count) {
        if(count && !samples)throw std::invalid_argument("missing native range observations");
        labels.reserve(count);
        rows.reserve(count);
        for(size_t i=0;i<count;++i) {
            const auto& r=samples[i];
            if(!r.view || !r.model || !r.topology || !r.stage || !r.layout || r.side>1 || r.ndim>3)
                throw std::invalid_argument("native range observation has invalid metadata");
            const std::string_view view=r.view,model=r.model;
            const bool nu=view=="nu" || view=="nu_raw" || view=="nu_pr";
            if(view=="nu_raw")labels.emplace_back("["+std::string(model)+" Nu raw] "+r.topology);
            else if(nu) {
                const char* prefix=nullptr;
                if(model=="air")prefix="[Nu extrap] ";
                else if(model=="water")prefix="[water Nu extrap] ";
                else if(model=="sco2")prefix="[sCO2 Nu extrap] ";
                else if(model=="co2")prefix="[CO2 Nu extrap] ";
                else throw std::invalid_argument("native Nu observation has an unknown fluid");
                labels.emplace_back(std::string(prefix)+r.topology);
            } else labels.emplace_back(model);
            tpmshx_stage_range_record_v1 row{};
            row.sample=&r;row.label=labels.back().c_str();
            row.quantity=view=="nu_pr"?"Pr":nu?"Re":"T";row.unit=nu?"-":"K";
            row.source_count=nu?3:2;
            if(r.have_finite) {
                range_coordinates(r.shape,r.ndim,r.minimum_index,row.minimum_index);
                range_coordinates(r.shape,r.ndim,r.maximum_index,row.maximum_index);
            }
            rows.push_back(row);
        }
    }
};
}  // namespace tpmshx::stages
