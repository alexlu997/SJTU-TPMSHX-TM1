#include <tpmshx/stages.hpp>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
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
        require(array.dtype==TPMSHX_RESULT_F64 && array.rank==2,"unexpected stage field format");
        std::ofstream output(directory/(std::string(field.name)+".bin"),std::ios::binary);
        output.write(static_cast<const char*>(array.data),static_cast<std::streamsize>(array.bytes));
        require(output.good(),"could not write stage field");
        index<<field.name<<'\t'<<array.shape[0]<<'\t'<<array.shape[1]<<'\n';
    }
    require(index.good(),"could not write stage field index");
}
void check_saved(const tpmshx_preparation_case_2d_v1& prepared,tpmshx::stages::RunControl control) {
    using namespace tpmshx::stages;
    tpmshx_preparation_case_2d_v2 view{};
    view.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;view.struct_size=sizeof(view);view.values=prepared;
    const auto cells=prepared.nx*prepared.ny;
    std::vector<double> area(cells,prepared.area_density_per_m),diameter(cells,prepared.hydraulic_diameter_m);
    std::vector<double> permeability[2],forchheimer[2];
    for(size_t side=0;side<2;++side) {
        permeability[side].assign(cells,prepared.sides[side].row_permeability.data[0]);
        forchheimer[side].assign(cells,prepared.sides[side].row_forchheimer.data[0]);
        view.values.sides[side].permeability={permeability[side].data(),cells};
        view.values.sides[side].forchheimer={forchheimer[side].data(),cells};
    }
    std::vector<uint32_t> captured(prepared.range_count,1);
    SavedCase2D saved;saved.prepared=&view;saved.area_density_per_m={area.data(),cells};
    saved.hydraulic_diameter_m={diameter.data(),cells};saved.range_captured=captured.data();
    void* handle=nullptr;char error[4096]="preserve-saved-error";
    auto malformed=saved;malformed.range_captured=reinterpret_cast<const uint32_t*>(&handle);
    require(prepared.range_count>0,"saved smoke requires prepared ranges");
    require(tpmshx_stage_run_2d_create_saved_v1(&malformed,nullptr,&control,&handle,error,sizeof(error))==1,
        "saved capture flags alias output");
    require(!handle && std::strcmp(error,"preserve-saved-error")==0,"saved flag alias changed output or error");
    malformed=saved;malformed.area_density_per_m.data=reinterpret_cast<const double*>(error);
    require(tpmshx_stage_run_2d_create_saved_v1(&malformed,nullptr,&control,&handle,error,sizeof(error))==1,
        "saved geometry aliases error storage");
    require(!handle && std::strcmp(error,"preserve-saved-error")==0,"saved geometry alias changed output or error");
    malformed=saved;--malformed.hydraulic_diameter_m.size;
    require(tpmshx_stage_run_2d_create_saved_v1(&malformed,nullptr,&control,&handle,error,sizeof(error))==1 && !handle,
        "saved geometry extent mismatch accepted");
    captured[0]=2;
    require(tpmshx_stage_run_2d_create_saved_v1(&saved,nullptr,&control,&handle,error,sizeof(error))==1 && !handle,
        "saved range capture flag accepted invalid value");
    captured[0]=0;saved.inlet_recorded=0;
    auto state=[&] {
        Run2D run(saved,control);
        require(run.advance_step()==TPMSHX_FULL2D_OUTER_BOUNDARY,"saved stage initial boundary changed");
        require(run.advance_step()==TPMSHX_FULL2D_FLOW,"saved stage flow boundary changed");
        return run.snapshot();
    }();
    control.cpu_threads=1;control.callbacks.cancel=cancel;
    Run2D restored(saved,control,{},&state);
    require(restored.phase()==TPMSHX_FULL2D_FLOW,"saved restore lost its phase");
    require(restored.advance_step()==TPMSHX_FULL2D_CANCELLED,"saved restore ignored cancellation");
    try {auto result=restored.take_result();throw std::runtime_error("cancelled saved stage published a result");}
    catch(const NativeError& failure) {require(failure.status()==6,"saved cancellation status changed");}
}
}
int main(int argc,char** argv) {
    using namespace tpmshx::stages;
    try {
        auto prepared=prepare_case(input());
        tpmshx_stage_run_result_2d_v1 failure{};
        failure.abi_version=TPMSHX_STAGE_RUN_ABI_VERSION;failure.struct_size=sizeof(failure);failure.raw.q_total=-123.;
        const auto before=failure;
        auto malformed=prepared.view();--malformed.total_porosity.size;
        RunControl control;control.result_id="stage-smoke";control.cpu_threads=2;
        char error[4096]{};
        require(tpmshx_run_case_2d_v1(&malformed,nullptr,&control,&failure,error,sizeof(error))==1,"malformed field accepted");
        require(std::memcmp(&failure,&before,sizeof(failure))==0,"failed stage changed output");
        const std::string storage_error=error;
        require(tpmshx_run_case_2d_v1(&prepared.view(),nullptr,
            reinterpret_cast<const tpmshx_stage_run_control_v1*>(&failure),&failure,error,sizeof(error))==1,
            "control aliases the complete output");
        require(storage_error==error && std::memcmp(&failure,&before,sizeof(failure))==0,
                "control alias changed output or escaped boundary validation");
        malformed=prepared.view();malformed.dx.data=reinterpret_cast<const double*>(&failure);
        require(tpmshx_run_case_2d_v1(&malformed,nullptr,&control,&failure,error,sizeof(error))==1,
                "prepared array aliases the complete output");
        require(storage_error==error && std::memcmp(&failure,&before,sizeof(failure))==0,
                "array alias changed output or escaped boundary validation");
        control.result_id=reinterpret_cast<const char*>(&failure);
        require(tpmshx_run_case_2d_v1(&prepared.view(),nullptr,&control,&failure,error,sizeof(error))==1,
                "result label aliases output");
        require(storage_error==error && std::memcmp(&failure,&before,sizeof(failure))==0,
                "label alias changed output or escaped boundary validation");
        char label[128]="preserve-label";
        char original_label[sizeof(label)];std::memcpy(original_label,label,sizeof(label));
        malformed=prepared.view();malformed.dx.data=nullptr;
        control.result_id=label;
        require(tpmshx_run_case_2d_v1(&malformed,nullptr,&control,&failure,label,sizeof(label))==1,
                "interrupted storage check accepted invalid input");
        require(std::memcmp(label,original_label,sizeof(label))==0 && std::memcmp(&failure,&before,sizeof(failure))==0,
                "interrupted storage check changed an unvisited label");
        control.result_id="stage-smoke";
        control.callbacks.cancel=cancel;
        require(tpmshx_run_case_2d_v1(&prepared.view(),nullptr,&control,&failure,error,sizeof(error))==4,"cancellation status changed");
        require(std::memcmp(&failure,&before,sizeof(failure))==0,"cancelled stage published a result");
        for(const auto option:{tpmshx_model_h_iteration_options_v1{5000,0.,0.},
                              tpmshx_model_h_iteration_options_v1{0,.001,0.},
                              tpmshx_model_h_iteration_options_v1{0,0.,.001}}) {
            RunRequest2D request;request.model_h=option;
            require(tpmshx_run_case_2d_v1(&prepared.view(),&request,&control,&failure,error,sizeof(error))==4,
                    "model-h controls conflict with implicit energy defaults");
            require(std::memcmp(&failure,&before,sizeof(failure))==0,"model-h cancellation changed output");
            const tpmshx_energy_options_v1 energy{TPMSHX_ENERGY_TEMPERATURE_SOU,1e-8};request.energy=&energy;
            require(tpmshx_run_case_2d_v1(&prepared.view(),&request,&control,&failure,error,sizeof(error))==1,
                    "explicit conflicting energy options accepted");
            require(std::memcmp(&failure,&before,sizeof(failure))==0,"option conflict changed output");
        }
        control.callbacks.cancel=nullptr;
        check_saved(prepared.view(),control);
        auto run=[&] {auto local=prepare_case(input());return run_case(local,control);}();
        // The prepared owner has gone. All saved evidence must remain valid.
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
