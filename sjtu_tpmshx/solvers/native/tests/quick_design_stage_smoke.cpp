#include <tpmshx/stages.hpp>
#include <array>
#include <cmath>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <string>
#include <vector>

namespace {
using namespace tpmshx::stages;
void require(bool value,const char* message) {if(!value)throw std::runtime_error(message);}
int cancel(void*) {return 1;}
int count_cancel(void* context) {++*static_cast<size_t*>(context);return 1;}
void count_progress(void* context,unsigned) {++*static_cast<size_t*>(context);}
void progress(void* context,unsigned percent) {static_cast<std::vector<unsigned>*>(context)->push_back(percent);}
QuickDesignInput input(uint32_t arrangement=TPMSHX_CROSS,uint32_t mode=TPMSHX_CONSTANT) {
    QuickDesignInput value;
    value.topology=TPMSHX_DIAMOND;value.arrangement=arrangement;value.property_mode=mode;
    value.cell_length_mm=7.;value.wall_thickness_mm=.5;value.span_m=.084;value.length_m=.05;
    value.have_height=arrangement==TPMSHX_CROSS?1:0;value.height_m=.07;
    value.sides[0]={TPMSHX_AIR,688.23,1088700.,.2855};value.sides[1]={TPMSHX_WATER,320.,200000.,.5};
    return value;
}
void binary(const std::filesystem::path& directory,const std::string& name,const void* data,size_t bytes) {
    std::ofstream file(directory/(name+".bin"),std::ios::binary);
    file.write(static_cast<const char*>(data),static_cast<std::streamsize>(bytes));require(file.good(),"could not write Quick Design field");
}
void prepared_files(const std::filesystem::path& directory,const tpmshx_quick_prepared_v1& value) {
    std::filesystem::create_directories(directory);
    std::ofstream index(directory/"prepared.tsv");
    const auto store=[&](const std::string& name,tpmshx_preparation_array_v1 values) {
        index<<name<<'\t'<<values.size<<'\n';binary(directory,name,values.data,values.size*sizeof(double));
    };
    for(size_t axis=0;axis<3;++axis) {
        store(std::string("d")+"xyz"[axis],value.widths[axis]);
        store(std::string(1,"xyz"[axis])+"_edges",value.edges[axis]);
        if(value.resolved.warm_start)store("initial_"+std::to_string(axis),value.initial[axis]);
    }
    store("eps",value.epsilon);store("eps_A",value.epsilon_a);store("K_ss",value.solid_conductivity);
    require(index.good(),"could not write Quick Design prepared index");
    std::ofstream scalars(directory/"prepared-scalars.tsv");scalars<<std::setprecision(17);
    const auto& c=value.resolved;
    scalars<<"Lx\t"<<c.length<<"\ns\t"<<c.span<<"\nheight\t"<<c.height
        <<"\nL_cell_m\t"<<c.cell_length<<"\nA_0\t"<<c.area_density<<"\nD_h\t"<<c.hydraulic_diameter
        <<"\nt_wall_m\t"<<value.wall_thickness_m<<"\nk_s\t"<<value.solid_conductivity_W_mK
        <<"\ntol\t"<<value.tolerance<<"\ngeometry_resolution\t"<<value.geometry_resolution
        <<"\nmaxit\t"<<c.max_iterations<<"\nchunk\t"<<c.chunk_iterations
        <<"\nqtol\t"<<c.q_relative_tolerance<<"\nalpha\t"<<c.alpha<<'\n';
    for(size_t side=0;side<2;++side)scalars<<"pressure_fraction_"<<"AB"[side]<<'\t'<<c.sides[side].inlet_pressure_fraction<<'\n';
    require(scalars.good(),"could not write Quick Design prepared scalars");
}
void result_files(const std::filesystem::path& directory,const tpmshx_quick_run_result_v1& value,
                  const Evaluation& performance,const std::vector<unsigned>& events) {
    std::ofstream index(directory/"fields.tsv"),metadata(directory/"metadata.tsv");
    const auto& e=value.evidence;
    for(size_t i=0;i<e.field_count;++i) {
        const auto& f=e.fields[i];const auto& a=f.value;
        require(a.dtype==TPMSHX_RESULT_F64 && a.rank==3,"unexpected Quick Design field format");
        binary(directory,"field_"+std::string(f.name),a.data,a.bytes);
        index<<f.name<<'\t'<<a.shape[0]<<'\t'<<a.shape[1]<<'\t'<<a.shape[2]<<'\n';
        metadata<<e.field_metadata[i].name<<'\t'<<e.field_metadata[i].unit<<'\t'<<e.field_metadata[i].state<<'\n';
    }
    std::ofstream scalars(directory/"run-scalars.tsv");scalars<<std::setprecision(17);
    const auto& raw=value.raw;
    scalars<<"converged\t"<<(raw.stop==TPMSHX_CONVERGED?1:0)<<"\ncompleted_passes\t"<<raw.completed_passes<<'\n';
    for(size_t p=0;p<raw.completed_passes;++p) {
        const auto& pass=raw.passes[p];
        scalars<<"pass_"<<p<<"_converged\t"<<(pass.stop==TPMSHX_CONVERGED?1:0)
            <<"\npass_"<<p<<"_iterations\t"<<pass.iterations<<"\npass_"<<p<<"_residual\t"<<pass.residual<<'\n';
    }
    for(size_t side=0;side<2;++side) {
        const auto& pass=raw.passes[raw.completed_passes-1].sides[side];const char label="AB"[side];
        scalars<<"pressure_in_"<<label<<'\t'<<raw.pressure[side].inlet
            <<"\npressure_out_"<<label<<'\t'<<raw.pressure[side].outlet
            <<"\npressure_choked_"<<label<<'\t'<<raw.pressure[side].choked<<'\n';
        const char* names[]{"rho","mu","k","cp","Pr","speed"};
        const double values[]{pass.rho,pass.mu,pass.k,pass.cp,pass.pr,pass.speed};
        for(size_t i=0;i<6;++i)scalars<<names[i]<<'_'<<label<<'\t'<<values[i]<<'\n';
    }
    std::ofstream report(directory/"metrics.json");report<<performance.view().json<<'\n';
    std::ofstream progress_file(directory/"progress.tsv");for(auto percent:events)progress_file<<percent<<'\n';
    require(index.good() && metadata.good() && scalars.good() && report.good() && progress_file.good(),
        "could not write Quick Design evidence");
}
void failures() {
    auto source=input();
    tpmshx_quick_prepared_v1 failure{};failure.abi_version=1;failure.struct_size=sizeof(failure);failure.resolved.length=-123.;
    const auto original=failure;char error[4096]{};
    source.have_height=1;source.height_m=0.;
    require(tpmshx_prepare_quick_design_v1(&source,&failure,error,sizeof(error))==1,"invalid explicit height accepted");
    require(std::string(error)=="quick-design height must be finite and positive","height error changed");
    require(std::memcmp(&failure,&original,sizeof(failure))==0,"failed prepare changed output");
    source=input();source.warm_start=1;
    std::vector<double> seed(120,320.);
    for(size_t axis=0;axis<3;++axis) {source.initial_shape[axis]=axis?1:120;source.initial[axis]={seed.data(),seed.size()};}
    require(tpmshx_prepare_quick_design_v1(&source,&failure,error,sizeof(error))==1,"invalid warm shape accepted");
    require(std::string(error)=="quick-design warm start must match the prepared grid","warm shape error changed");
    require(std::memcmp(&failure,&original,sizeof(failure))==0,"warm shape failure changed output");
    source=input();source.topology=8;
    require(tpmshx_prepare_quick_design_v1(&source,&failure,error,sizeof(error))==1,"invalid topology accepted");
    source=input();source.have_tolerance=1;source.tolerance=std::numeric_limits<double>::quiet_NaN();
    require(tpmshx_prepare_quick_design_v1(&source,&failure,error,sizeof(error))==1,"invalid tolerance accepted");
    source=input();source.arrangement=5;
    require(tpmshx_prepare_quick_design_v1(&source,&failure,error,sizeof(error))==1,"invalid arrangement accepted");
    source=input();source.sides[1].temperature_K=500.;
    require(tpmshx_prepare_quick_design_v1(&source,&failure,error,sizeof(error))==TPMSHX_PREPARATION_WATER_STATE,
        "water state rejection changed");
    source=input();
    require(tpmshx_prepare_quick_design_v1(&source,&failure,reinterpret_cast<char*>(&source),sizeof(source))==1,
        "aliased preparation error storage accepted");
    auto prepared=prepare_quick_design(input());
    tpmshx_quick_run_result_v1 run{};run.abi_version=1;run.struct_size=sizeof(run);run.raw.completed_passes=91;
    const auto before=run;tpmshx_quick_run_control_v1 control{};control.result_id="quick-boundary";
    size_t callback_calls=0;control.callbacks={count_cancel,count_progress,&callback_calls};
    const auto reject_alias=[&](const tpmshx_quick_prepared_v1* prepared_input,
            const tpmshx_quick_run_control_v1* control_input) {
        require(tpmshx_run_quick_design_v1(prepared_input,control_input,&run,error,sizeof(error))==TPMSHX_INVALID_ARGUMENT,
            "aliased run input accepted");
        require(std::memcmp(&run,&before,sizeof(run))==0,"aliased input changed output");
        require(callback_calls==0,"aliased input called a callback");
    };
    reject_alias(&prepared.view(),reinterpret_cast<const tpmshx_quick_run_control_v1*>(&run));
    reject_alias(&prepared.view(),reinterpret_cast<const tpmshx_quick_run_control_v1*>(&run.raw));
    reject_alias(reinterpret_cast<const tpmshx_quick_prepared_v1*>(&run),&control);
    control.result_id=reinterpret_cast<const char*>(&run);
    reject_alias(&prepared.view(),&control);control.result_id="quick-boundary";
    auto aliased=prepared.view();
    for(auto* values:{&aliased.widths[0],&aliased.epsilon,&aliased.epsilon_a,&aliased.solid_conductivity}) {
        const auto saved=*values;values->data=reinterpret_cast<const double*>(&run);
        reject_alias(&aliased,&control);*values=saved;
    }
    aliased.resolved.warm_start=1;
    aliased.initial[0]={reinterpret_cast<const double*>(&run),1};
    reject_alias(&aliased,&control);
    for(unsigned failure=0;failure<3;++failure) {
        std::array<double,32> borrowed;
        std::memset(borrowed.data(),0x5a,sizeof(borrowed));
        std::memcpy(borrowed.data(),"borrowed-label",sizeof("borrowed-label"));
        const auto original_borrowed=borrowed;
        auto invalid=prepared.view();
        if(failure==0) {
            invalid.widths[0]={nullptr,1};
            control.result_id=reinterpret_cast<const char*>(borrowed.data());
        } else {
            invalid.epsilon={borrowed.data(),borrowed.size()};
            if(failure==1)invalid.widths[0]={reinterpret_cast<const double*>(&run),1};
            else run.owner=reinterpret_cast<void*>(1);
        }
        const auto original_run=run;
        require(tpmshx_run_quick_design_v1(&invalid,&control,&run,
            reinterpret_cast<char*>(borrowed.data()),sizeof(borrowed))==TPMSHX_INVALID_ARGUMENT,
            "early failure accepted aliased error storage");
        require(std::memcmp(borrowed.data(),original_borrowed.data(),sizeof(borrowed))==0,
            "early failure changed borrowed input bytes");
        require(std::memcmp(&run,&original_run,sizeof(run))==0,"early failure changed output");
        require(callback_calls==0,"early failure called a callback");
        run=before;control.result_id="quick-boundary";
    }
    control.result_id=nullptr;
    require(tpmshx_run_quick_design_v1(&prepared.view(),&control,&run,error,sizeof(error))==TPMSHX_INVALID_ARGUMENT,
        "missing result label accepted");
    require(std::string(error)=="quick-design run requires a result label","missing label diagnostic changed");
    require(std::memcmp(&run,&before,sizeof(run))==0,"missing label changed output");
    control.result_id="quick-boundary";run.owner=reinterpret_cast<void*>(1);
    const auto occupied=run;
    require(tpmshx_run_quick_design_v1(&prepared.view(),&control,&run,error,sizeof(error))==TPMSHX_INVALID_ARGUMENT,
        "nonempty run owner accepted");
    require(std::string(error)=="release the previous quick-design run owner before reuse","owner diagnostic changed");
    require(std::memcmp(&run,&occupied,sizeof(run))==0,"owner rejection changed output");
    require(callback_calls==0,"semantic failure called a callback");
    run=before;
    control.callbacks={};
    auto malformed=prepared.view();--malformed.epsilon.size;
    require(tpmshx_run_quick_design_v1(&malformed,&control,&run,error,sizeof(error))==1,"malformed prepared field accepted");
    require(std::memcmp(&run,&before,sizeof(run))==0,"failed run changed output");
    require(std::string(error)=="quick-design prepared array has the wrong extent","prepared extent diagnostic changed");
    control.callbacks.cancel=cancel;
    require(tpmshx_run_quick_design_v1(&prepared.view(),&control,&run,error,sizeof(error))==TPMSHX_QUICK_STAGE_CANCELLED,"cancelled run status changed");
    require(std::memcmp(&run,&before,sizeof(run))==0,"cancelled run published evidence");
    require(tpmshx_run_quick_design_v1(&prepared.view(),&control,&run,reinterpret_cast<char*>(&run),sizeof(run))==1,
        "aliased run error storage accepted");
    require(std::memcmp(&run,&before,sizeof(run))==0,"aliased run modified its output");
}
}
int main(int argc,char** argv) {
    try {
        failures();
        const char* names[]{"cross-const","cross-mean","counter-const","cross-warm","counter-mean","water-air","sco2-sco2"};
        for(size_t sample=0;sample<7;++sample) {
            auto source=input(sample==2 || sample==4?TPMSHX_COUNTER:TPMSHX_CROSS,
                sample==1 || sample==4?TPMSHX_MEAN:TPMSHX_CONSTANT);
            if(sample==5) {
                source.topology=TPMSHX_GYROID;source.length_m=.025;source.height_m=.06;
                source.sides[0]={TPMSHX_WATER,355.,2e5,.2};source.sides[1]={TPMSHX_AIR,300.,2e5,.04};
            }
            if(sample==6) {
                source.length_m=.025;source.height_m=.06;
                source.sides[0]={TPMSHX_SCO2,500.,9e6,.2};source.sides[1]={TPMSHX_SCO2,350.,8e6,.2};
            }
            std::array<std::vector<double>,3> seeds;
            if(sample==3) {
                source.warm_start=1;source.initial_shape[0]=60;source.initial_shape[1]=40;source.initial_shape[2]=1;
                const double temperatures[]{source.sides[0].temperature_K,source.sides[1].temperature_K,
                    (source.sides[0].temperature_K+source.sides[1].temperature_K)/2.};
                for(size_t side=0;side<3;++side) {seeds[side].assign(2400,temperatures[side]);source.initial[side]={seeds[side].data(),seeds[side].size()};}
            }
            std::vector<unsigned> events;tpmshx_quick_run_control_v1 control{};
            control.result_id=names[sample];control.callbacks={nullptr,progress,&events};
            const auto directory=argc>1?std::filesystem::path(argv[1])/names[sample]:std::filesystem::path();
            auto run=[&] {
                auto prepared=prepare_quick_design(source);
                if(sample==3) {
                    seeds[0][0]=-999.;require(prepared.view().initial[0].data[0]==source.sides[0].temperature_K,
                        "prepared warm start borrowed the caller buffer");
                }
                if(argc>1)prepared_files(directory,prepared.view());
                auto result=run_case(prepared,control);
                require(prepared.view().initial[0].size==0 || prepared.view().initial[0].data[0]==source.sides[0].temperature_K,
                    "run modified the prepared warm start");
                return result;
            }();
            // The prepared owner is gone before any evaluation reads the fields.
            auto performance=evaluate(run);
            require(run.view().raw.stop==TPMSHX_CONVERGED,"Quick Design sample did not converge");
            require(run.view().evidence.field_count==15 && performance.view().metric_count==14,"Quick Design result set changed");
            if(argc>1)result_files(directory,run.view(),performance,events);
        }
        std::cout<<"PASS: Quick Design prepare/run/evaluate, warm start, cancellation and detached ownership\n";return 0;
    } catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}
}
