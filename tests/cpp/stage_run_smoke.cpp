#include <tpmshx/stages.hpp>
#include <algorithm>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <string>
#include <vector>

namespace {
void require(bool value,const char* message) {if(!value)throw std::runtime_error(message);}
int cancel(void*) {return 1;}
tpmshx::stages::CaseInput2D input() {
    tpmshx::stages::CaseInput2D value;
    value.length_m=.182;value.height_m=.042;value.requested_nx=20;value.requested_ny=40;
    value.topology=1;value.cell_length_mm=7.;value.wall_thickness_mm=.4;value.solid_conductivity_W_mK=16.;
    for(auto& side:value.sides) {side.velocity_m_s=10.;side.pressure_Pa=101325.;}
    value.sides[0].temperature_K=600.;value.sides[1].temperature_K=300.;value.sides[1].port.direction=3;
    return value;
}
void write(const std::filesystem::path& directory,const tpmshx_stage_run_result_2d_v1& result) {
    std::filesystem::create_directories(directory);
    std::ofstream index(directory/"fields.tsv");
    for(size_t i=0;i<result.evidence.field_count;++i) {
        const auto& field=result.evidence.fields[i];
        const auto& array=field.value;
        require(array.data && array.rank==2,"unexpected stage field format");
        std::ofstream output(directory/(std::string(field.name)+".bin"),std::ios::binary);
        output.write(reinterpret_cast<const char*>(array.data),
            static_cast<std::streamsize>(array.shape[0]*array.shape[1]*sizeof(double)));
        require(output.good(),"could not write stage field");
        index<<field.name<<'\t'<<array.shape[0]<<'\t'<<array.shape[1]<<'\n';
    }
    require(index.good(),"could not write stage field index");
}
void check_saved(const tpmshx::stages::PreparedFlowCase2Dv10& calibrated,tpmshx::stages::RunControl control) {
    using namespace tpmshx::stages;
    const SavedCase2Dv4 saved(calibrated);
    const auto& prepared=calibrated.view().values.prepared.values;
    const auto cells=prepared.nx*prepared.ny;
    std::vector<double> area(cells,prepared.area_density_per_m),diameter(cells,prepared.hydraulic_diameter_m);
    std::vector<uint32_t> captured(prepared.range_count,1);
    tpmshx_stage_saved_case_2d_v4 copy=saved;
    auto& values=copy.values.values.values;
    values.area_density_per_m={area.data(),cells};values.hydraulic_diameter_m={diameter.data(),cells};
    values.range_captured=captured.data();
    void* handle=nullptr;char error[4096]="preserve-saved-error";
    const auto create=[&](const tpmshx_stage_saved_case_2d_v4& value) {
        return tpmshx_stage_run_2d_create_saved_v4(&value,nullptr,&control,&handle,error,sizeof(error));
    };
    require(prepared.range_count>0,"saved smoke requires prepared ranges");
    auto malformed=copy;malformed.values.values.values.range_captured=reinterpret_cast<const uint32_t*>(&handle);
    require(create(malformed)==1,"saved capture flags alias output");
    require(!handle && std::strcmp(error,"preserve-saved-error")==0,"saved flag alias changed output or error");
    malformed=copy;malformed.values.values.values.area_density_per_m.data=reinterpret_cast<const double*>(error);
    require(create(malformed)==1,"saved geometry aliases error storage");
    require(!handle && std::strcmp(error,"preserve-saved-error")==0,"saved geometry alias changed output or error");
    malformed=copy;--malformed.values.values.values.hydraulic_diameter_m.size;
    require(create(malformed)==1 && !handle,"saved geometry extent mismatch accepted");
    captured[0]=2;
    require(create(copy)==1 && !handle,"saved range capture flag accepted invalid value");
    captured[0]=0;copy.values.values.values.inlet_recorded=0;
    auto state=[&] {
        Run2D run(copy,control);
        require(run.advance_step()==TPMSHX_FULL2D_OUTER_BOUNDARY,"saved stage initial boundary changed");
        require(run.advance_step()==TPMSHX_FULL2D_FLOW,"saved stage flow boundary changed");
        return run.snapshot();
    }();
    {
        Run2D resumed(saved,control,{},&state);
        require(resumed.phase()==TPMSHX_FULL2D_FLOW,"saved v4 lost the restored phase");
        auto experiment=static_cast<tpmshx_stage_saved_case_2d_v4>(saved);
        require(!tpmshx_stage_run_2d_create_saved_v4(&experiment,nullptr,&control,&handle,error,sizeof(error))
            && handle,"saved v4 rejected the original campaign");
        tpmshx_stage_run_2d_release_run_v1(&handle);
        require(!tpmshx_stage_run_2d_restore_saved_v4(&experiment,nullptr,&control,state.view().fields,
            state.view().count,&handle,error,sizeof(error)) && handle,"saved v4 rejected the matched checkpoint");
        tpmshx_stage_run_2d_release_run_v1(&handle);
        const auto rejected=[&](const char* reason,int status=1) {
            require(tpmshx_stage_run_2d_create_saved_v4(&experiment,nullptr,&control,&handle,error,sizeof(error))==status
                && !handle && std::strstr(error,reason),"saved create admitted a mismatched campaign");
            require(tpmshx_stage_run_2d_restore_saved_v4(&experiment,nullptr,&control,state.view().fields,
                state.view().count,&handle,error,sizeof(error))==status && !handle && std::strstr(error,reason),
                "saved restore admitted a mismatched campaign");
        };
        experiment.experiment.velocity_m_s[0]=100.;
        rejected("HX experiment calibration requires",8);
        experiment.experiment.velocity_m_s[0]=std::numeric_limits<double>::quiet_NaN();
        rejected("invalid saved experimental inlet velocity");
        experiment.experiment.velocity_m_s[0]=10.;
        experiment.experiment.geometry_mode=2;
        rejected("experimental calibration currently requires uniform");
        experiment.experiment.geometry_mode=0;
        experiment.experiment.domain_m[0]=.180;
        rejected("side A is HX-effective");
        experiment.experiment.fluids[0]=experiment.experiment.fluids[1]=3;
        rejected("fluids disagree");
        experiment.experiment.fluids[0]=experiment.experiment.fluids[1]=0;
        experiment.experiment.configured_flow[0]=experiment.experiment.configured_flow[1]=1;
        rejected("side A is HX-effective");
        experiment.experiment.configured_flow[0]=experiment.experiment.configured_flow[1]=0;
        experiment.experiment.wall_thickness_mm=.4;
        rejected("nominal geometry disagrees");
        experiment.experiment.domain_m[0]=std::numeric_limits<double>::quiet_NaN();
        require(tpmshx_stage_run_2d_check_experiment_v4(&experiment.experiment,error,sizeof(error))==1
            && std::strstr(error,"invalid saved experimental settings"),"experiment query accepted a nonfinite domain");
        experiment.experiment.domain_m[0]=.182;
        experiment.experiment.velocity_m_s[0]=0.;
        require(tpmshx_stage_run_2d_check_experiment_v4(&experiment.experiment,error,sizeof(error))==1
            && std::strstr(error,"invalid saved experimental inlet velocity"),"experiment query accepted zero velocity");
        require(tpmshx_stage_port_windows_fit_2d_v1(.125,.0625,.125,.0625,.125)==1
            && tpmshx_stage_port_windows_fit_2d_v1(.125,.0625,.125,.125,.125)==0,
            "saved port windows must fit the physical cross axis");
        auto invalid=static_cast<tpmshx_stage_saved_case_2d_v4>(saved);
        invalid.values.resource_topology={error,2};
        std::strcpy(error,"preserve-saved-error");
        require(create(invalid)==1 && !handle && std::strcmp(error,"preserve-saved-error")==0,
            "saved v4 overwrote a borrowed string");
    }
    control.cpu_threads=1;control.callbacks.cancel=cancel;
    Run2D restored(copy,control,{},&state);
    require(restored.phase()==TPMSHX_FULL2D_FLOW,"saved restore lost its phase");
    restored.finish();
    require(restored.phase()==TPMSHX_FULL2D_CANCELLED,"saved restore ignored cancellation");
    try {auto result=restored.take_result();throw std::runtime_error("cancelled saved stage published a result");}
    catch(const NativeError& failure) {require(failure.status()==6,"saved cancellation status changed");}
}
}
int main(int argc,char** argv) {
    using namespace tpmshx::stages;
    try {
        auto prepared=prepare_case(input());
        const SavedCase2Dv4 saved(prepared);
        tpmshx_stage_run_result_2d_v1 failure{};
        failure.abi_version=TPMSHX_STAGE_RUN_ABI_VERSION;failure.struct_size=sizeof(failure);failure.raw.q_total=-123.;
        const auto before=failure;
        auto view=*saved.values.values.values.prepared;--view.values.total_porosity.size;
        tpmshx_stage_saved_case_2d_v4 malformed=saved;malformed.values.values.values.prepared=&view;
        RunControl control;control.result_id="stage-smoke";control.cpu_threads=2;
        char error[4096]{};
        const auto run_saved=[&](const tpmshx_stage_saved_case_2d_v4& value,const tpmshx_stage_run_request_2d_v3* request,
                                 const tpmshx_stage_run_control_v1* selected,char* message,size_t capacity) {
            return tpmshx_run_saved_case_2d_v4(&value,request,selected,&failure,message,capacity);
        };
        require(run_saved(malformed,nullptr,&control,error,sizeof(error))==1,"malformed field accepted");
        require(std::memcmp(&failure,&before,sizeof(failure))==0,"failed stage changed output");
        const std::string storage_error=error;
        require(run_saved(saved,nullptr,reinterpret_cast<const tpmshx_stage_run_control_v1*>(&failure),
            error,sizeof(error))==1,"control aliases the complete output");
        require(storage_error==error && std::memcmp(&failure,&before,sizeof(failure))==0,
                "control alias changed output or escaped boundary validation");
        view=*saved.values.values.values.prepared;view.values.dx.data=reinterpret_cast<const double*>(&failure);
        require(run_saved(malformed,nullptr,&control,error,sizeof(error))==1,
                "prepared array aliases the complete output");
        require(storage_error==error && std::memcmp(&failure,&before,sizeof(failure))==0,
                "array alias changed output or escaped boundary validation");
        control.result_id=reinterpret_cast<const char*>(&failure);
        require(run_saved(saved,nullptr,&control,error,sizeof(error))==1,"result label aliases output");
        require(storage_error==error && std::memcmp(&failure,&before,sizeof(failure))==0,
                "label alias changed output or escaped boundary validation");
        char label[128]="preserve-label";
        char original_label[sizeof(label)];std::memcpy(original_label,label,sizeof(label));
        view=*saved.values.values.values.prepared;view.values.dx.data=nullptr;
        control.result_id=label;
        require(run_saved(malformed,nullptr,&control,label,sizeof(label))==1,
                "interrupted storage check accepted invalid input");
        require(std::memcmp(label,original_label,sizeof(label))==0 && std::memcmp(&failure,&before,sizeof(failure))==0,
                "interrupted storage check changed an unvisited label");
        control.result_id="stage-smoke";
        control.callbacks.cancel=cancel;
        require(run_saved(saved,nullptr,&control,error,sizeof(error))==6,"cancellation status changed");
        require(std::memcmp(&failure,&before,sizeof(failure))==0,"cancelled stage published a result");
        for(const auto option:{tpmshx_model_h_iteration_options_v1{5000,0.,0.},
                              tpmshx_model_h_iteration_options_v1{0,.001,0.},
                              tpmshx_model_h_iteration_options_v1{0,0.,.001}}) {
            RunRequest2Dv3 request;request.values.values.model_h=option;
            require(run_saved(saved,&request,&control,error,sizeof(error))==6,
                    "model-h controls conflict with implicit energy defaults");
            require(std::memcmp(&failure,&before,sizeof(failure))==0,"model-h cancellation changed output");
            const tpmshx_energy_options_v1 energy{TPMSHX_ENERGY_TEMPERATURE_SOU,1e-8};request.values.values.energy=&energy;
            request.values.values.explicit_energy=nullptr;request.energy_iterations={1,3};
            require(run_saved(saved,&request,&control,error,sizeof(error))==1,
                    "explicit conflicting energy options accepted");
            require(std::memcmp(&failure,&before,sizeof(failure))==0,"option conflict changed output");
        }
        control.callbacks.cancel=nullptr;
        CaseInput2Dv2 experimental;
        experimental.values=input();
        experimental.values.df_mode=1;experimental.values.wall_thickness_mm=.6;
        auto calibrated=prepare_case(experimental);
        check_saved(calibrated,control);
        auto run=[&] {auto local=prepare_case(input());return run_case(local,control);}();
        // The prepared owner has gone. All saved evidence must remain valid.
        const auto* records=tpmshx_stage_run_2d_records_v1(&run.view());
        require(records && records->sampling.count && records->sampling.records,"missing 2D property sampling");
        require(!tpmshx_stage_run_2d_records_v1(&failure),"invalid result published 2D records");
        const auto* executed=tpmshx_stage_run_2d_execution_view_v1(&run.view());
        require(executed && executed->execution.records==records && !std::strcmp(executed->execution.unknown,"T")
                && executed->execution.algorithm
                && executed->settings.outer_count==run.view().raw.outer_history_count,"missing 2D executed thermal settings");
        auto performance=evaluate(run);
        require(run.view().raw.converged,"baseline stage solve did not converge");
        require(performance.view().metric_count==17,"stage metric set changed");
        if(argc>1) {
            write(argv[1],run.view());std::ofstream report(std::filesystem::path(argv[1])/"metrics.json");
            report<<performance.view().json<<'\n';require(report.good(),"could not write stage metrics");
        }
        std::cout<<"PASS: native prepare/run/evaluate, cancellation and independent result lifetime\n";
        return 0;
    } catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}
}
