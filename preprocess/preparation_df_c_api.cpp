#include "tpmshx/preparation_df.hpp"
#include "preparation_c_boundary.hpp"
#include "preparation_properties.hpp"
#include "preparation_df_fields.hpp"

#include <algorithm>
#include <cstdint>
#include <initializer_list>
#include <stdexcept>
#include <vector>

namespace {
namespace p = tpmshx::preparation;
using namespace p::c_api;
struct Buffer { std::uintptr_t first, last; bool empty, output; };
template<class T> Buffer buffer(const T* pointer, std::size_t count, bool output = false) {
    require_buffer(pointer, count);
    const auto first = reinterpret_cast<std::uintptr_t>(pointer);
    return {first, count ? first + product(count, sizeof(T)) - 1 : first, count == 0, output};
}
bool overlaps(const Buffer& first, const Buffer& second) {
    return !first.empty && !second.empty && first.first <= second.last && second.first <= first.last;
}
template<class Buffers, class Function> int guarded(char* error, std::size_t capacity,
    Buffers get_buffers, Function function) noexcept {
    if (!tpmshx::fields::c_api::error_buffer_valid(error, capacity)) return TPMSHX_PREPARATION_INVALID;
    std::vector<Buffer> buffers;
    try {
        buffers = get_buffers();
        const auto error_range = buffer(error, capacity);
        for (const auto& value : buffers)
            if (overlaps(value, error_range)) return TPMSHX_PREPARATION_INVALID;
    } catch (const std::bad_alloc&) { return TPMSHX_PREPARATION_ALLOCATION; }
    catch (...) { return TPMSHX_PREPARATION_INVALID; }
    return boundary(error, capacity, [&] {
        for (std::size_t i = 0; i < buffers.size(); ++i)
            for (std::size_t j = i + 1; j < buffers.size(); ++j)
                if ((buffers[i].output || buffers[j].output) && overlaps(buffers[i], buffers[j]))
                    throw std::invalid_argument("preparation output overlaps another buffer");
        function();
    });
}
void flag(std::uint32_t value) {
    if (value > 1) throw std::invalid_argument("preparation flag must be zero or one");
}
tpmshx::grid::Scalar scalar(tpmshx_grid_scalar_v1 value) {
    return tpmshx::grid::checked({value.value,value.precision,value.strong});
}
template<class Pair> void publish(const std::vector<Pair>& values, double* first, double* second) {
    for (std::size_t i = 0; i < values.size(); ++i) { first[i] = values[i].K; second[i] = values[i].cF; }
}
[[noreturn]] void publish_failure(const p::PropertyError& error,tpmshx_preparation_fp_failure_v1* failure) {
    const auto& diagnostic = error.failure.fp;
    if (diagnostic.event_count > TPMSHX_PREPARATION_FP_EVENT_COUNT
        || diagnostic.python_cause > TPMSHX_PREPARATION_TYPE_ERROR)
        throw StateError(TPMSHX_PREPARATION_RUNTIME,"invalid internal pressure failure diagnostics");
    *failure = diagnostic;
    throw StateError(error.status,error.what());
}
template<class Function> void publish_pressure(tpmshx_preparation_df_pressure_v1* output,
    tpmshx_preparation_fp_failure_v1* failure, Function calculate) {
    *failure = {};
    try {
        const auto result = calculate();
        *output = result;
    } catch (const p::PropertyError& error) {
        publish_failure(error,failure);
    }
}
p::PropertyInput field(tpmshx_property_input_v1 value) {
    return {{value.values,value.count},{value.kind.value,value.kind.precision,value.kind.strong},value.layout};
}
}  // namespace

extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_df_fixed_v1(
    uint32_t topology, const double* length, const double* wall, size_t count,
    double* k, size_t k_count, double* f, size_t f_count, char* error, size_t cap) {
    return guarded(error, cap, [&] { return std::vector<Buffer>{buffer(length,count),buffer(wall,count),buffer(k,k_count,true),buffer(f,f_count,true)}; }, [&] {
        require_output(k,k_count,count); require_output(f,f_count,count);
        const auto result = p::fixed_df_batch(topology,{length,count},{wall,count});
        publish(result,k,f);
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_df_incompressible_v1(
    uint32_t topology, double length, double wall, tpmshx_grid_scalar_v1 speed,
    tpmshx_grid_scalar_v1 density, tpmshx_grid_scalar_v1 viscosity,
    tpmshx_grid_scalar_v1 channel, tpmshx_preparation_df_pressure_v1* output,
    tpmshx_preparation_fp_failure_v1* failure,char* error,size_t cap) {
    return guarded(error,cap,[&] {return std::vector<Buffer>{buffer(output,1,true),buffer(failure,1,true)};},[&] {
        publish_pressure(output,failure,[&] {
            return p::df_incompressible_typed(topology,length,wall,scalar(speed),scalar(density),scalar(viscosity),scalar(channel));
        });
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_df_compressible_v1(
    uint32_t topology,double length,double wall,tpmshx_grid_scalar_v1 flux,
    tpmshx_grid_scalar_v1 temperature,tpmshx_grid_scalar_v1 pressure,
    tpmshx_grid_scalar_v1 viscosity,tpmshx_grid_scalar_v1 channel,uint32_t strict,
    tpmshx_preparation_df_pressure_v1* output,tpmshx_preparation_fp_failure_v1* failure,
    char* error,size_t cap) {
    return guarded(error,cap,[&] {return std::vector<Buffer>{buffer(output,1,true),buffer(failure,1,true)};},[&] {
        flag(strict);
        publish_pressure(output,failure,[&] {
            return p::df_compressible_typed(topology,length,wall,scalar(flux),scalar(temperature),scalar(pressure),scalar(viscosity),scalar(channel),strict!=0);
        });
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_df_pressure_gradient_v1(
    tpmshx_property_input_v1 density,tpmshx_property_input_v1 viscosity,tpmshx_property_input_v1 speed,
    tpmshx_property_input_v1 permeability,tpmshx_property_input_v1 inertial,tpmshx_property_output_v1 output,
    tpmshx_preparation_fp_failure_v1* failure,char* error,size_t cap) {
    return guarded(error,cap,[&] {return std::vector<Buffer>{
        buffer(density.values,density.count),buffer(viscosity.values,viscosity.count),buffer(speed.values,speed.count),
        buffer(permeability.values,permeability.count),buffer(inertial.values,inertial.count),
        buffer(output.values,output.count,true),buffer(output.imaginary,output.count,true),buffer(output.kind,1,true),
        buffer(output.category,1,true),buffer(output.events,output.event_count,true),buffer(failure,1,true)};},[&] {
        require_output(output.values,output.count,density.count);
        require_output(output.imaginary,output.count,density.count);
        require_output(output.events,output.event_count,TPMSHX_PREPARATION_FP_EVENT_COUNT);
        *failure = {};
        p::PropertyResult result;
        try {
            result = p::df_pressure_gradient(field(density),field(viscosity),field(speed),field(permeability),field(inertial));
        } catch (const p::PropertyError& error_data) { publish_failure(error_data,failure); }
        if (result.values.size()!=output.count || result.imaginary.size()!=output.count)
            throw std::runtime_error("pressure-gradient result extent is incorrect");
        for (size_t i=0;i<output.count;++i) {output.values[i]=result.values[i];output.imaginary[i]=result.imaginary[i];}
        *output.kind = {result.kind.value,result.kind.precision,result.kind.strong};
        *output.category = result.category;
        std::copy(result.events.begin(),result.events.end(),output.events);
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_df_correction_select_v1(
    uint32_t topology,uint32_t fluid,uint32_t transfer,const double* length,size_t length_count,
    const double* wall,size_t wall_count,const double* velocity,size_t velocity_count,uint32_t has_velocity,
    tpmshx_preparation_df_selection_v1* output,char* error,size_t cap) {
    return guarded(error,cap,[&] {return std::vector<Buffer>{buffer(length,length_count),buffer(wall,wall_count),buffer(velocity,velocity_count),buffer(output,1,true)};},[&] {
        flag(transfer); flag(has_velocity);
        if (!has_velocity && velocity_count) throw std::invalid_argument("missing velocity has a nonempty buffer");
        const auto result = p::df_select(topology,fluid,transfer!=0,{length,length_count},{wall,wall_count},{velocity,velocity_count},has_velocity!=0);
        *output = result;
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_df_correction_scales_v1(
    uint32_t topology,const tpmshx_preparation_df_selection_v1* selection,const double* length,const double* wall,
    size_t count,double* k,size_t k_count,double* f,size_t f_count,char* error,size_t cap) {
    return guarded(error,cap,[&] {return std::vector<Buffer>{buffer(selection,1),buffer(length,count),buffer(wall,count),buffer(k,k_count,true),buffer(f,f_count,true)};},[&] {
        require_output(k,k_count,count); require_output(f,f_count,count);
        if (selection->branch > 1 || selection->scope > 1 || selection->campaign > 3 || selection->flags > 7)
            throw std::invalid_argument("correction selection is invalid");
        const auto result = p::df_scales(topology,*selection,{length,count},{wall,count});
        publish(result,k,f);
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_df_apply_scale_v1(
    const double* base,const double* scale,size_t count,uint32_t prepared,double* output,size_t output_count,char* error,size_t cap) {
    return guarded(error,cap,[&] {return std::vector<Buffer>{buffer(base,count),buffer(scale,count),buffer(output,output_count,true)};},[&] {
        flag(prepared); require_output(output,output_count,count);
        const auto result = p::df_apply_scale({base,count},{scale,count},prepared!=0);
        for (size_t i=0;i<count;++i) output[i]=result[i];
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_df_summarize_v1(
    const double* values,size_t count,uint32_t scalar,tpmshx_preparation_df_summary_v1* output,char* error,size_t cap) {
    return guarded(error,cap,[&] {return std::vector<Buffer>{buffer(values,count),buffer(output,1,true)};},[&] {
        flag(scalar);
        if (scalar && count != 1) throw std::invalid_argument("scalar summary needs exactly one value");
        const auto result = p::df_summary({values,count},scalar!=0); *output = result;
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_df_co2_factors_v1(
    double* output,size_t count,char* error,size_t cap) {
    return guarded(error,cap,[&] {return std::vector<Buffer>{buffer(output,count,true)};},[&] {
        require_output(output,count,2); const auto result = p::df_co2_factors();
        output[0] = result.K; output[1] = result.cF;
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_df_project_rows_v1(
    size_t nx,size_t ny,const double* length,const double* wall,size_t field_count,uint32_t l_bits,uint32_t t_bits,
    uint32_t l_column_major,uint32_t t_column_major,
    uint32_t direction,size_t target_count,const double* dx,size_t dx_count,uint32_t dx_bits,
    const double* dy,size_t dy_count,uint32_t dy_bits,const double* widths,size_t width_count,
    double* l_rows,size_t l_count,double* t_rows,size_t t_count,int64_t* indices,size_t index_count,char* error,size_t cap) {
    return guarded(error,cap,[&] {return std::vector<Buffer>{buffer(length,field_count),buffer(wall,field_count),buffer(dx,dx_count),buffer(dy,dy_count),buffer(widths,width_count),buffer(l_rows,l_count,true),buffer(t_rows,t_count,true),buffer(indices,index_count,true)};},[&] {
        flag(l_column_major); flag(t_column_major);
        if (field_count!=product(nx,ny) || ((dx_count || dy_count) && (dx_count!=nx || dy_count!=ny))
            || (width_count && width_count!=target_count)) throw std::invalid_argument("projection buffer extents differ from the physical axes");
        require_output(l_rows,l_count,target_count); require_output(t_rows,t_count,target_count); require_output(indices,index_count,target_count);
        const auto result = p::df_project_rows(nx,ny,{length,field_count},{wall,field_count},l_bits,t_bits,
            l_column_major!=0,t_column_major!=0,direction,target_count,
            {dx,dx_count},dx_bits,{dy,dy_count},dy_bits,{widths,width_count});
        for (size_t i=0;i<target_count;++i) {l_rows[i]=result.lengths[i];t_rows[i]=result.walls[i];indices[i]=result.source_index[i];}
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_df_row_means_v1(
    size_t rows,size_t columns,const double* permeability,const double* inertial,size_t field_count,
    uint32_t k_column_major,uint32_t f_column_major,
    double* k,size_t k_count,double* f,size_t f_count,char* error,size_t cap) {
    return guarded(error,cap,[&] {return std::vector<Buffer>{buffer(permeability,field_count),buffer(inertial,field_count),buffer(k,k_count,true),buffer(f,f_count,true)};},[&] {
        flag(k_column_major); flag(f_column_major);
        if (field_count!=product(rows,columns)) throw std::invalid_argument("DF row-mean buffer extent is incorrect");
        require_output(k,k_count,columns); require_output(f,f_count,columns);
        const auto result = p::df_row_means(rows,columns,{permeability,field_count},{inertial,field_count},
            k_column_major!=0,f_column_major!=0);
        publish(result,k,f);
    });
}
