#include <tpmshx/stages.hpp>
#include <algorithm>
#include <array>
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
void check_saved(const tpmshx::stages::PreparedUniformCase2D& calibrated,tpmshx::stages::RunControl control) {
    using namespace tpmshx::stages;
    const SavedCase2D saved(calibrated);
    const auto& prepared=calibrated.view().prepared;
    const auto cells=prepared.nx*prepared.ny;
    std::vector<double> area(cells,prepared.area_density_per_m),diameter(cells,prepared.hydraulic_diameter_m);
    std::vector<uint32_t> captured(prepared.range_count,1);
    tpmshx_stage_saved_case_2d_v5 copy=saved;
    copy.area_density_per_m={area.data(),cells};copy.hydraulic_diameter_m={diameter.data(),cells};
    copy.range_captured=captured.data();
    void* handle=nullptr;char error[4096]="preserve-saved-error";
    const auto create=[&](const tpmshx_stage_saved_case_2d_v5& value) {
        return tpmshx_stage_run_2d_create_saved_v5(&value,nullptr,&control,&handle,error,sizeof(error));
    };
    require(prepared.range_count>0,"saved smoke requires prepared ranges");
    auto malformed=copy;malformed.range_captured=reinterpret_cast<const uint32_t*>(&handle);
    require(create(malformed)==1,"saved capture flags alias output");
    require(!handle && std::strcmp(error,"preserve-saved-error")==0,"saved flag alias changed output or error");
    malformed=copy;malformed.area_density_per_m.data=reinterpret_cast<const double*>(error);
    require(create(malformed)==1,"saved geometry aliases error storage");
    require(!handle && std::strcmp(error,"preserve-saved-error")==0,"saved geometry alias changed output or error");
    malformed=copy;--malformed.hydraulic_diameter_m.size;
    require(create(malformed)==1 && !handle,"saved geometry extent mismatch accepted");
    captured[0]=2;
    require(create(copy)==1 && !handle,"saved range capture flag accepted invalid value");
    captured[0]=0;copy.inlet_recorded=0;
    auto state=[&] {
        Run2D run(copy,control);
        require(run.advance_step()==TPMSHX_FULL2D_OUTER_BOUNDARY,"saved stage initial boundary changed");
        require(run.advance_step()==TPMSHX_FULL2D_FLOW,"saved stage flow boundary changed");
        return run.snapshot();
    }();
    {
        Run2D resumed(saved,control,{},&state);
        require(resumed.phase()==TPMSHX_FULL2D_FLOW,"saved v5 lost the restored phase");
        auto experiment=static_cast<tpmshx_stage_saved_case_2d_v5>(saved);
        require(!tpmshx_stage_run_2d_create_saved_v5(&experiment,nullptr,&control,&handle,error,sizeof(error))
            && handle,"saved v5 rejected the original campaign");
        tpmshx_stage_run_2d_release_run_v1(&handle);
        require(!tpmshx_stage_run_2d_restore_saved_v5(&experiment,nullptr,&control,state.view().fields,
            state.view().count,&handle,error,sizeof(error)) && handle,"saved v5 rejected the matched checkpoint");
        tpmshx_stage_run_2d_release_run_v1(&handle);
        const auto rejected=[&](const char* reason,int status=1) {
            require(tpmshx_stage_run_2d_create_saved_v5(&experiment,nullptr,&control,&handle,error,sizeof(error))==status
                && !handle && std::strstr(error,reason),"saved create admitted a mismatched campaign");
            require(tpmshx_stage_run_2d_restore_saved_v5(&experiment,nullptr,&control,state.view().fields,
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
        auto invalid=static_cast<tpmshx_stage_saved_case_2d_v5>(saved);
        invalid.resource_topology={error,2};
        std::strcpy(error,"preserve-saved-error");
        require(create(invalid)==1 && !handle && std::strcmp(error,"preserve-saved-error")==0,
            "saved v5 overwrote a borrowed string");
    }
    control.cpu_threads=1;control.callbacks.cancel=cancel;
    Run2D restored(copy,control,{},&state);
    require(restored.phase()==TPMSHX_FULL2D_FLOW,"saved restore lost its phase");
    restored.finish();
    require(restored.phase()==TPMSHX_FULL2D_CANCELLED,"saved restore ignored cancellation");
    try {auto result=restored.take_result();throw std::runtime_error("cancelled saved stage published a result");}
    catch(const NativeError& failure) {require(failure.status()==6,"saved cancellation status changed");}
}
void check_sdk_saved_families(tpmshx::stages::RunControl control) {
    using namespace tpmshx::stages;
    PreparationOptions options;options.allow_extrapolation=1;
    RunRequest2D fast2d;
    fast2d.max_iter_simple={1,2};fast2d.max_outer_ltne={1,2};
    auto configure_tiny=[](tpmshx_preparation_case_input_2d_v1& value) {
        value.length_m=.06;value.height_m=.03;value.requested_nx=4;value.requested_ny=4;
        value.topology=1;value.cell_length_mm=7.;value.wall_thickness_mm=.4;
        value.solid_conductivity_W_mK=16.;
        for(size_t side=0;side<2;++side) {
            value.sides[side].velocity_m_s=side?6.:8.;
            value.sides[side].temperature_K=side?300.:450.;
            value.sides[side].pressure_Pa=side?120000.:200000.;
            value.sides[side].port.direction=side?3:0;
        }
    };
    auto make_region=[](double x0,double x1,double y0,double y1,double cell,double wall,const char* name=nullptr) {
        tpmshx_preparation_zone_region_v5 value{};
        if(name) {value.name={name,std::strlen(name)};}
        value.bounds[0]=x0;value.bounds[1]=x1;value.bounds[2]=y0;value.bounds[3]=y1;
        value.cell_length_mm=cell;value.wall_thickness_mm=wall;return value;
    };
    // 1. Zoned 2D (PreparedZonedFlowCase2D -> SavedCase2D -> run_case)
    {
        ZonedFlowInput2D zoned;configure_tiny(zoned.input);
        std::array<tpmshx_preparation_zone_region_v5,2> cells{{
            make_region(0.,.5,0.,1.,7.,.4),make_region(.5,1.,0.,1.,6.,.5)}};
        zoned.kind=1;zoned.regions=cells.data();zoned.region_count=cells.size();
        PreparedZonedFlowCase2D prepared=prepare_case(zoned,options);
        const SavedCase2D saved(prepared);
        control.result_id="smoke-zoned-2d";
        auto result=run_case(saved,control,fast2d);
        require(result.view().evidence.dimension==2 && result.view().raw.main.nx==4 && result.view().raw.main.ny==4,
            "zoned 2D SavedCase2D run failed");
    }
    // 2. Sigmoid 2D (PreparedSigmoidFlowCase2D -> SavedCase2D -> run_case)
    {
        SigmoidFlowInput2D sigmoid;configure_tiny(sigmoid.input);
        auto bounds=make_region(0.,1.,0.,1.,7.,.4);
        sigmoid.regions=&bounds;sigmoid.region_count=1;
        std::array<double,36> decisions{};
        for(size_t i=0;i<18;++i) {decisions[2*i]=6.5;decisions[2*i+1]=.45;}
        sigmoid.controls.decision_mm={decisions.data(),decisions.size()};
        auto lut=build_sigmoid_lut(1,2,2,16);
        sigmoid.lut={lut.view().cell_mm,lut.view().wall_mm,lut.view().porosity,
            lut.view().area_density_per_m,lut.view().porosity_fast,lut.view().area_fast};
        PreparedSigmoidFlowCase2D prepared=prepare_case(sigmoid,options);
        const SavedCase2D saved(prepared);
        control.result_id="smoke-sigmoid-2d";
        auto result=run_case(saved,control,fast2d);
        require(result.view().evidence.dimension==2 && result.view().raw.main.nx==4 && result.view().raw.main.ny==4,
            "sigmoid 2D SavedCase2D run failed");
    }
    // 3. Stripe 2D (PreparedStripeCase2D -> SavedCase2D -> run_case)
    {
        ZonedFlowInput2D stripe;configure_tiny(stripe.input);
        std::array<tpmshx_preparation_zone_region_v5,2> bands{{
            make_region(0.,.5,0.,0.,7.,.4,"inlet"),make_region(.5,1.,0.,0.,6.,.5,"outlet")}};
        stripe.kind=0;stripe.axis=1;stripe.regions=bands.data();stripe.region_count=bands.size();
        PreparedStripeCase2D prepared=prepare_stripe_case(stripe,options);
        const SavedCase2D saved(prepared);
        control.result_id="smoke-stripe-2d";
        auto result=run_case(saved,control,fast2d);
        require(result.view().evidence.dimension==2 && result.view().raw.main.nx==4 && result.view().raw.main.ny==4,
            "stripe 2D SavedCase2D run failed");
    }
    // 4. Continuous 3D (SavedPreparedCase3D(const PreparedContinuousCase3D&) -> run_case)
    {
        ContinuousInput3D continuous;
        auto& values=continuous.input;
        values.lengths_m[0]=.06;values.lengths_m[1]=.04;values.lengths_m[2]=.03;
        values.counts[0]=4;values.counts[1]=4;values.counts[2]=4;
        values.topology=1;values.cell_length_mm=7.;values.wall_thickness_mm=.6;
        values.solid_conductivity_W_mK=16.;
        values.sides[0].velocity_m_s=6.;values.sides[0].temperature_K=350.;values.sides[0].pressure_Pa=200000.;
        values.sides[1].fluid=1;values.sides[1].velocity_m_s=.02;
        values.sides[1].temperature_K=320.;values.sides[1].pressure_Pa=200000.;
        values.sides[1].port.direction=3;
        const double decisions[]{4.5,6.,7.5,5.4,.31,.42,.59,.36};
        continuous.controls={2,2,1,0,1,0,{4.,8.},{.3,.6},{decisions,8}};
        PreparedContinuousCase3D prepared=prepare_case(continuous,options);
        const SavedPreparedCase3D saved(prepared);
        RunRequest3D fast3d;
        fast3d.max_iter_simple={1,2};fast3d.max_outer_ltne={1,1};
        fast3d.model_h={4,.5,1e-3};
        RunControl3D control3d;control3d.cpu_threads=2;control3d.result_id="smoke-continuous-3d";
        auto result=run_case(saved,control3d,fast3d);
        require(result.view().raw.stop<=1 && result.view().evidence.dimension==3,
            "continuous 3D SavedPreparedCase3D run failed");
    }
}
}
int main(int argc,char** argv) {
    using namespace tpmshx::stages;
    try {
        require(tpmshx_stage_run_2d_abi_version()==TPMSHX_STAGE_RUN_ABI_VERSION_V5,
            "unexpected 2D stage run ABI version");
        auto prepared=prepare_case(input());
        const SavedCase2D saved(prepared);
        tpmshx_stage_run_result_2d_v1 failure{};
        failure.abi_version=TPMSHX_STAGE_RUN_ABI_VERSION;failure.struct_size=sizeof(failure);failure.raw.q_total=-123.;
        const auto before=failure;
        auto view=*saved.prepared;--view.total_porosity.size;
        tpmshx_stage_saved_case_2d_v5 malformed=saved;malformed.prepared=&view;
        RunControl control;control.result_id="stage-smoke";control.cpu_threads=2;
        char error[4096]{};
        const auto run_saved=[&](const tpmshx_stage_saved_case_2d_v5& value,const tpmshx_stage_run_request_2d_v4* request,
                                 const tpmshx_stage_run_control_v1* selected,char* message,size_t capacity) {
            return tpmshx_run_saved_case_2d_v5(&value,request,selected,&failure,message,capacity);
        };
        require(run_saved(malformed,nullptr,&control,error,sizeof(error))==1,"malformed field accepted");
        require(std::memcmp(&failure,&before,sizeof(failure))==0,"failed stage changed output");
        const std::string storage_error=error;
        require(run_saved(saved,nullptr,reinterpret_cast<const tpmshx_stage_run_control_v1*>(&failure),
            error,sizeof(error))==1,"control aliases the complete output");
        require(storage_error==error && std::memcmp(&failure,&before,sizeof(failure))==0,
                "control alias changed output or escaped boundary validation");
        view=*saved.prepared;view.dx.data=reinterpret_cast<const double*>(&failure);
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
        view=*saved.prepared;view.dx.data=nullptr;
        control.result_id=label;
        require(run_saved(malformed,nullptr,&control,label,sizeof(label))==1,
                "interrupted storage check accepted invalid input");
        require(std::memcmp(label,original_label,sizeof(label))==0 && std::memcmp(&failure,&before,sizeof(failure))==0,
                "interrupted storage check changed an unvisited label");
        control.result_id="stage-smoke";
        control.callbacks.cancel=cancel;
        require(run_saved(saved,nullptr,&control,error,sizeof(error))==6,"cancellation status changed");
        require(std::memcmp(&failure,&before,sizeof(failure))==0,"cancelled stage published a result");
        const tpmshx_energy_options_v1 energy{TPMSHX_ENERGY_TEMPERATURE_SOU,1e-8};
        const tpmshx_full_2d_energy_control_v4 explicit_energy{20,1,.5,1e-6,{TPMSHX_ENERGY_TEMPERATURE_SOU,1e-8,1e-6,1e-6,0}};
        for(const auto option:{tpmshx_model_h_iteration_options_v1{5000,0.,0.},
                              tpmshx_model_h_iteration_options_v1{0,.001,0.},
                              tpmshx_model_h_iteration_options_v1{0,0.,.001}}) {
            RunRequest2D request;request.model_h=option;
            require(run_saved(saved,&request,&control,error,sizeof(error))==6,
                    "model-h controls conflict with implicit energy defaults");
            require(std::memcmp(&failure,&before,sizeof(failure))==0,"model-h cancellation changed output");
            // R1-N2 case 1: active model_h + non-null energy -> rejected (status 1).
            request.energy=&energy;
            require(run_saved(saved,&request,&control,error,sizeof(error))==1,
                    "active model_h with non-null energy was accepted");
            require(std::memcmp(&failure,&before,sizeof(failure))==0,"model_h+energy conflict changed output");
            // R1-N2 case 3: active model_h + partial energy override -> rejected (status 1).
            request.energy=nullptr;request.energy_iterations={1,3};
            require(run_saved(saved,&request,&control,error,sizeof(error))==1,
                    "active model_h with partial energy override was accepted");
            require(std::memcmp(&failure,&before,sizeof(failure))==0,"model_h+partial conflict changed output");
        }
        // R1-N2 case 2: explicit_energy + partial energy override -> rejected (status 1).
        {
            RunRequest2D request;
            request.explicit_energy=&explicit_energy;request.energy_iterations={1,3};
            require(run_saved(saved,&request,&control,error,sizeof(error))==1,
                    "explicit_energy with partial energy override was accepted");
            require(std::memcmp(&failure,&before,sizeof(failure))==0,"explicit+partial conflict changed output");
        }
        control.callbacks.cancel=nullptr;
        CaseInput2D experimental=input();
        experimental.df_mode=1;experimental.wall_thickness_mm=.6;
        auto calibrated=prepare_case(experimental);
        check_saved(calibrated,control);
        check_sdk_saved_families(control);
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
