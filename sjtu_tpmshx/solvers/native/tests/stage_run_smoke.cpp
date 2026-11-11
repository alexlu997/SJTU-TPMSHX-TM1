#include <tpmshx/stages.hpp>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>

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
        require(tpmshx_run_case_2d_v1(&prepared.view(),nullptr,
            reinterpret_cast<const tpmshx_stage_run_control_v1*>(&failure),&failure,error,sizeof(error))==1,
            "control aliases the complete output");
        require(std::strstr(error,"overlaps") && std::memcmp(&failure,&before,sizeof(failure))==0,
                "control alias changed output or escaped boundary validation");
        malformed=prepared.view();malformed.dx.data=reinterpret_cast<const double*>(&failure);
        require(tpmshx_run_case_2d_v1(&malformed,nullptr,&control,&failure,error,sizeof(error))==1,
                "prepared array aliases the complete output");
        require(std::strstr(error,"overlaps") && std::memcmp(&failure,&before,sizeof(failure))==0,
                "array alias changed output or escaped boundary validation");
        control.result_id=reinterpret_cast<const char*>(&failure);
        require(tpmshx_run_case_2d_v1(&prepared.view(),nullptr,&control,&failure,error,sizeof(error))==1,
                "result label aliases output");
        require(std::strstr(error,"overlaps") && std::memcmp(&failure,&before,sizeof(failure))==0,
                "label alias changed output or escaped boundary validation");
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
