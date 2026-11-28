#include <tpmshx/stages.hpp>
#include <tpmshx/temperature_driver_c_api.h>
#include <algorithm>
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
// One raw operating point. Labels are borrowed static text.
struct Point {
    QuickDesignInputV2 value;
    std::array<std::vector<double>,3> seeds;
};
tpmshx_preparation_text_v1 text(const char* value) {return {value,std::strlen(value)};}
void input(Point& point,bool counter=false,bool mean=false) {
    auto& value=point.value;
    value=QuickDesignInputV2{};
    const double scalars[]{7.,.5,.084,.05,.07,16.,1e-5,.2855,.5,688.23,320.,1088700.,200000.};
    for(size_t i=0;i<TPMSHX_QUICK_VALUE_COUNT;++i)value.values[i]=scalars[i];
    value.topology=text("Diamond");value.arrangement=text(counter?"counter":"cross");
    value.property_mode=text(mean?"mean":"const");
    value.fluids[0]=text("air");value.fluids[1]=text("water");value.have_height=counter?0:1;
}
void binary(const std::filesystem::path& directory,const std::string& name,const void* data,size_t bytes) {
    std::ofstream file(directory/(name+".bin"),std::ios::binary);
    file.write(static_cast<const char*>(data),static_cast<std::streamsize>(bytes));require(file.good(),"could not write Quick Design field");
}
void prepared_files(const std::filesystem::path& directory,const QuickDesignInputV2& input,
                    const tpmshx_quick_prepared_v2& value) {
    std::filesystem::create_directories(directory);
    std::ofstream index(directory/"prepared.tsv");
    const auto store=[&](const std::string& name,tpmshx_preparation_array_v1 values) {
        index<<name<<'\t'<<values.size<<'\n';binary(directory,name,values.data,values.size*sizeof(double));
    };
    for(size_t axis=0;axis<3;++axis) {
        store(std::string("d")+"xyz"[axis],value.widths[axis]);
        store(std::string(1,"xyz"[axis])+"_edges",value.edges[axis]);
        if(input.warm_start)store("initial_"+std::to_string(axis),value.initial[axis]);
    }
    store("eps",value.epsilon);store("eps_A",value.epsilon_a);store("K_ss",value.solid_conductivity);
    require(index.good(),"could not write Quick Design prepared index");
    std::ofstream scalars(directory/"prepared-scalars.tsv");scalars<<std::setprecision(17);
    const auto& v=input.values;const auto& c=value.controls;
    const auto span=v[TPMSHX_QUICK_SPAN],tolerance=v[TPMSHX_QUICK_TOLERANCE];
    // Independent reference: the run selects these defaults when the prepared controls omit them.
    const bool plane=value.shape[2]==1;
    const auto qtol=c.have_q_relative_tolerance?c.q_relative_tolerance:
        (plane?std::min(tolerance*2e-3,1e-3):std::max(tolerance*10.,1e-4));
    const auto chunk=c.have_chunk_iterations?c.chunk_iterations:(plane?500u:250u);
    scalars<<"Lx\t"<<v[TPMSHX_QUICK_LENGTH]<<"\ns\t"<<span
        <<"\nheight\t"<<(input.have_height?v[TPMSHX_QUICK_HEIGHT]:span)
        <<"\nL_cell_m\t"<<value.cell_length_m<<"\nA_0\t"<<value.geometry.area_density_per_m
        <<"\nD_h\t"<<value.geometry.hydraulic_diameter_m
        <<"\nt_wall_m\t"<<value.wall_thickness_m<<"\nk_s\t"<<v[TPMSHX_QUICK_CONDUCTIVITY]
        <<"\ntol\t"<<tolerance<<"\nmaxit\t"<<c.max_iterations<<"\nchunk\t"<<chunk
        <<"\nqtol\t"<<qtol<<"\nalpha\t"<<c.alpha<<'\n';
    for(size_t side=0;side<2;++side)scalars<<"pressure_fraction_"<<"AB"[side]<<'\t'<<value.fractions[side]<<'\n';
    require(scalars.good(),"could not write Quick Design prepared scalars");
}
void result_files(const std::filesystem::path& directory,const tpmshx_quick_run_result_v1& value,
                  const Evaluation& performance,const std::vector<unsigned>& events) {
    std::ofstream index(directory/"fields.tsv"),metadata(directory/"metadata.tsv");
    const auto& e=value.evidence;
    for(size_t i=0;i<e.field_count;++i) {
        const auto& f=e.fields[i];const auto& a=f.value;
        require(a.data && a.rank==3,"unexpected Quick Design field format");
        binary(directory,"field_"+std::string(f.name),a.data,a.shape[0]*a.shape[1]*a.shape[2]*sizeof(double));
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
    Point point;input(point);auto& source=point.value;
    tpmshx_quick_prepared_v2 failure{};failure.abi_version=2;failure.struct_size=sizeof(failure);
    failure.cell_length_m=-123.;
    const auto original=failure;char error[4096]{};
    const auto rejected=[&](const char* message) {
        require(tpmshx_prepare_quick_design_v3(&source,nullptr,&failure,error,sizeof(error))!=0,message);
        require(std::memcmp(&failure,&original,sizeof(failure))==0,"failed prepare changed output");
        input(point);
    };
    source.values[TPMSHX_QUICK_HEIGHT]=0.;rejected("invalid explicit height accepted");
    source.topology=text("Octahedron");rejected("invalid topology accepted");
    source.values[TPMSHX_QUICK_TOLERANCE]=std::numeric_limits<double>::quiet_NaN();rejected("invalid tolerance accepted");
    source.arrangement=text("parallel");rejected("invalid arrangement accepted");
    source.values[TPMSHX_QUICK_TEMPERATURE_B]=500.;
    require(tpmshx_prepare_quick_design_v3(&source,nullptr,&failure,error,sizeof(error))==TPMSHX_PREPARATION_WATER_STATE,
        "water state rejection changed");
    input(point);
    require(tpmshx_prepare_quick_design_v3(&source,nullptr,&failure,reinterpret_cast<char*>(&source),sizeof(source))==1,
        "aliased preparation error storage accepted");
    auto prepared=prepare_quick_design(source);
    tpmshx_quick_run_result_v1 run{};run.abi_version=1;run.struct_size=sizeof(run);run.raw.completed_passes=91;
    const auto before=run;tpmshx_quick_run_control_v1 control{};control.result_id="quick-boundary";
    size_t callback_calls=0;control.callbacks={count_cancel,count_progress,&callback_calls};
    const auto run_v2=[&](const tpmshx_quick_prepared_v2* prepared_input,const tpmshx_quick_run_control_v1* control_input,
                          char* message,size_t capacity) {
        return tpmshx_run_quick_design_v2(&source,prepared_input,control_input,&run,message,capacity);
    };
    const auto reject_alias=[&](const tpmshx_quick_prepared_v2* prepared_input,
            const tpmshx_quick_run_control_v1* control_input) {
        require(run_v2(prepared_input,control_input,error,sizeof(error))==TPMSHX_INVALID_ARGUMENT,"aliased run input accepted");
        require(std::memcmp(&run,&before,sizeof(run))==0,"aliased input changed output");
        require(callback_calls==0,"aliased input called a callback");
    };
    reject_alias(&prepared.view(),reinterpret_cast<const tpmshx_quick_run_control_v1*>(&run));
    reject_alias(&prepared.view(),reinterpret_cast<const tpmshx_quick_run_control_v1*>(&run.raw));
    reject_alias(reinterpret_cast<const tpmshx_quick_prepared_v2*>(&run),&control);
    control.result_id=reinterpret_cast<const char*>(&run);
    reject_alias(&prepared.view(),&control);control.result_id="quick-boundary";
    auto aliased=prepared.view();
    for(auto* values:{&aliased.widths[0],&aliased.epsilon,&aliased.epsilon_a,&aliased.solid_conductivity}) {
        const auto saved=*values;values->data=reinterpret_cast<const double*>(&run);
        reject_alias(&aliased,&control);*values=saved;
    }
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
        require(run_v2(&invalid,&control,reinterpret_cast<char*>(borrowed.data()),sizeof(borrowed))==TPMSHX_INVALID_ARGUMENT,
            "early failure accepted aliased error storage");
        require(std::memcmp(borrowed.data(),original_borrowed.data(),sizeof(borrowed))==0,
            "early failure changed borrowed input bytes");
        require(std::memcmp(&run,&original_run,sizeof(run))==0,"early failure changed output");
        require(callback_calls==0,"early failure called a callback");
        run=before;control.result_id="quick-boundary";
    }
    control.result_id=nullptr;
    require(run_v2(&prepared.view(),&control,error,sizeof(error))==TPMSHX_INVALID_ARGUMENT,"missing result label accepted");
    require(std::string(error)=="quick-design run requires a result label","missing label diagnostic changed");
    require(std::memcmp(&run,&before,sizeof(run))==0,"missing label changed output");
    control.result_id="quick-boundary";run.owner=reinterpret_cast<void*>(1);
    const auto occupied=run;
    require(run_v2(&prepared.view(),&control,error,sizeof(error))==TPMSHX_INVALID_ARGUMENT,"nonempty run owner accepted");
    require(std::string(error)=="release the previous quick-design run owner before reuse","owner diagnostic changed");
    require(std::memcmp(&run,&occupied,sizeof(run))==0,"owner rejection changed output");
    require(callback_calls==0,"semantic failure called a callback");
    run=before;
    control.callbacks={};
    auto malformed=prepared.view();--malformed.epsilon.size;
    require(run_v2(&malformed,&control,error,sizeof(error))==1,"malformed prepared field accepted");
    require(std::memcmp(&run,&before,sizeof(run))==0,"failed run changed output");
    require(std::string(error)=="quick-design prepared array has the wrong extent","prepared extent diagnostic changed");
    malformed=prepared.view();++malformed.controls.dir_b;
    require(run_v2(&malformed,&control,error,sizeof(error))==1,"prepared controls disagree with the arrangement");
    require(std::memcmp(&run,&before,sizeof(run))==0,"rejected controls changed output");
    control.callbacks.cancel=cancel;
    require(run_v2(&prepared.view(),&control,error,sizeof(error))==TPMSHX_QUICK_STAGE_CANCELLED,"cancelled run status changed");
    require(std::memcmp(&run,&before,sizeof(run))==0,"cancelled run published evidence");
    require(run_v2(&prepared.view(),&control,reinterpret_cast<char*>(&run),sizeof(run))==1,
        "aliased run error storage accepted");
    require(std::memcmp(&run,&before,sizeof(run))==0,"aliased run modified its output");
}
}
int main(int argc,char** argv) {
    try {
        failures();
        {
            QuickDesignInputV2 source;
            const double scalars[]{7.,.5,.084,.025,.07,16.,1e-5,.03,.02,480.,320.,9e6,9e6};
            for(size_t i=0;i<TPMSHX_QUICK_VALUE_COUNT;++i)source.values[i]=scalars[i];
            source.topology={"Diamond",7};source.arrangement={"counter",7};source.property_mode={"const",5};
            source.fluids[0]={"air",3};source.fluids[1]={"air",3};source.have_height=1;
            tpmshx_quick_run_control_v1 control{};control.result_id="saved-quick-v2";
            auto result=[&] {
                auto prepared=prepare_quick_design(source);
                auto output=run_case(source,prepared,control);
                auto alias=source;
                char error[128]="preserve";
                alias.arrangement={error,7};
                tpmshx_quick_run_result_v1 empty{};empty.abi_version=1;empty.struct_size=sizeof(empty);
                require(tpmshx_run_quick_design_v2(&alias,&prepared.view(),&control,&empty,error,sizeof(error))==1 &&
                    !empty.owner && std::strcmp(error,"preserve")==0,"v2 run changed overlapping storage");
                return output;
            }();
            require(result.view().evidence.field_count==15 && evaluate(result).view().metric_count==14,
                    "v2 run lost detached fields or metrics");
        }
        const char* names[]{"cross-const","cross-mean","counter-const","cross-warm","counter-mean","water-air","sco2-sco2"};
        for(size_t sample=0;sample<7;++sample) {
            Point point;input(point,sample==2 || sample==4,sample==1 || sample==4);
            auto& source=point.value;auto& v=source.values;
            if(sample==5) {
                source.topology=text("Gyroid");v[TPMSHX_QUICK_LENGTH]=.025;v[TPMSHX_QUICK_HEIGHT]=.06;
                source.fluids[0]=text("water");source.fluids[1]=text("air");
                v[TPMSHX_QUICK_TEMPERATURE_A]=355.;v[TPMSHX_QUICK_PRESSURE_A]=2e5;v[TPMSHX_QUICK_MASS_A]=.2;
                v[TPMSHX_QUICK_TEMPERATURE_B]=300.;v[TPMSHX_QUICK_PRESSURE_B]=2e5;v[TPMSHX_QUICK_MASS_B]=.04;
            }
            if(sample==6) {
                v[TPMSHX_QUICK_LENGTH]=.025;v[TPMSHX_QUICK_HEIGHT]=.06;
                source.fluids[0]=text("sco2");source.fluids[1]=text("sco2");
                v[TPMSHX_QUICK_TEMPERATURE_A]=500.;v[TPMSHX_QUICK_PRESSURE_A]=9e6;v[TPMSHX_QUICK_MASS_A]=.2;
                v[TPMSHX_QUICK_TEMPERATURE_B]=350.;v[TPMSHX_QUICK_PRESSURE_B]=8e6;v[TPMSHX_QUICK_MASS_B]=.2;
            }
            const double hot=v[TPMSHX_QUICK_TEMPERATURE_A],cold=v[TPMSHX_QUICK_TEMPERATURE_B];
            if(sample==3) {
                source.warm_start=1;source.initial_shape[0]=60;source.initial_shape[1]=40;source.initial_shape[2]=1;
                const double temperatures[]{hot,cold,(hot+cold)/2.};
                for(size_t side=0;side<3;++side) {
                    point.seeds[side].assign(2400,temperatures[side]);
                    source.initial[side]={point.seeds[side].data(),point.seeds[side].size()};
                }
            }
            std::vector<unsigned> events;tpmshx_quick_run_control_v1 control{};
            control.result_id=names[sample];control.callbacks={nullptr,progress,&events};
            const auto directory=argc>1?std::filesystem::path(argv[1])/names[sample]:std::filesystem::path();
            auto run=[&] {
                auto prepared=prepare_quick_design(source);
                if(sample==3) {
                    point.seeds[0][0]=-999.;require(prepared.view().initial[0].data[0]==hot,
                        "prepared warm start borrowed the caller buffer");
                }
                if(argc>1)prepared_files(directory,source,prepared.view());
                auto result=run_case(source,prepared,control);
                require(prepared.view().initial[0].size==0 || prepared.view().initial[0].data[0]==hot,
                    "run modified the prepared warm start");
                return result;
            }();
            // The prepared owner is gone before any evaluation reads the fields.
            const auto* algorithm=tpmshx_quick_run_temperature_algorithm_v1(&run.view());
            const auto scheme=sample==2 || sample==4?TPMSHX_TEMPERATURE_CC_3D:TPMSHX_TEMPERATURE_CC_2D;
            require(algorithm && std::strcmp(algorithm,tpmshx_temperature_algorithm_v1(scheme))==0,
                "Quick Design result has the wrong temperature recipe");
            auto performance=evaluate(run);
            require(run.view().raw.stop==TPMSHX_CONVERGED,"Quick Design sample did not converge");
            require(run.view().evidence.field_count==15 && performance.view().metric_count==14,"Quick Design result set changed");
            if(argc>1)result_files(directory,run.view(),performance,events);
        }
        std::cout<<"PASS: Quick Design prepare/run/evaluate, warm start, cancellation and detached ownership\n";return 0;
    } catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}
}
