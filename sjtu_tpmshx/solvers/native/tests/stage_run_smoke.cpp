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
        control.callbacks.cancel=cancel;
        require(tpmshx_run_case_2d_v1(&prepared.view(),nullptr,&control,&failure,error,sizeof(error))==4,"cancellation status changed");
        require(std::memcmp(&failure,&before,sizeof(failure))==0,"cancelled stage published a result");
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
