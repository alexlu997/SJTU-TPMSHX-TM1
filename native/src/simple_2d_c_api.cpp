#include "tpmshx/simple_2d_c_api.h"
#include "tpmshx/simple_2d.hpp"
#include "simple_2d_c_views.hpp"

#include <algorithm>
#include <cstring>
#include <limits>
#include <memory>
#include <stdexcept>

struct tpmshx_simple_2d_handle {
    tpmshx::Simple2DSolver solver;
    tpmshx_simple_2d_handle(const tpmshx::GridView& grid,
                          tpmshx::ArrayView<const unsigned char> outlet)
        : solver(grid,outlet) {}
};

namespace {
void text(char* output, std::size_t capacity, const char* value) noexcept {
    if (!output || !capacity) return;
    const auto size = std::min(capacity-1,std::strlen(value));
    std::memcpy(output,value,size); output[size] = '\0';
}
template <typename Function> int guarded(Function function, char* error, std::size_t capacity) noexcept {
    text(error,capacity,"");
    try { function(); return TPMSHX_SIMPLE_OK; }
    catch (const std::invalid_argument& e) { text(error,capacity,e.what()); return TPMSHX_SIMPLE_INVALID_ARGUMENT; }
    catch (const std::domain_error& e) { text(error,capacity,e.what()); return TPMSHX_SIMPLE_ARITHMETIC_ERROR; }
    catch (const std::exception& e) { text(error,capacity,e.what()); return TPMSHX_SIMPLE_NATIVE_ERROR; }
    catch (...) { text(error,capacity,"unknown native SIMPLE error"); return TPMSHX_SIMPLE_NATIVE_ERROR; }
}
bool cancel(void* context) {
    const auto& callbacks = *static_cast<const tpmshx_simple_callbacks_v1*>(context);
    return callbacks.cancel && callbacks.cancel(callbacks.context) != 0;
}
void progress(void* context, std::size_t iteration, double residual) {
    const auto& callbacks = *static_cast<const tpmshx_simple_callbacks_v1*>(context);
    if (callbacks.progress) callbacks.progress(callbacks.context,iteration,residual);
}
void flag(uint32_t value) {
    if (value > 1) throw std::invalid_argument("SIMPLE flags must be 0 or 1");
}
}

extern "C" {
uint32_t TPMSHX_THERMAL_CALL tpmshx_simple_2d_abi_version(void) {
    return TPMSHX_SIMPLE_2D_ABI_VERSION;
}

int TPMSHX_THERMAL_CALL tpmshx_simple_2d_create_v1(
    size_t nx, size_t ny, const double* dx, const double* dy, const uint8_t* outlet,
    tpmshx_simple_2d_handle** handle, char* error, size_t capacity) {
    return guarded([&] {
        if (!handle || !dx || !dy || !outlet)
            throw std::invalid_argument("null SIMPLE create argument");
        const double depth = 1.;
        const tpmshx::GridView grid{nx,ny,1,{dx,nx},{dy,ny},{&depth,1}};
        auto created = std::make_unique<tpmshx_simple_2d_handle>(grid,
            tpmshx::ArrayView<const unsigned char>{outlet,nx});
        *handle = created.release();
    },error,capacity);
}

void TPMSHX_THERMAL_CALL tpmshx_simple_2d_destroy(tpmshx_simple_2d_handle* handle) { delete handle; }

int TPMSHX_THERMAL_CALL tpmshx_simple_2d_solve_v1(
    tpmshx_simple_2d_handle* handle, double* const* arrays, const size_t* sizes,
    const tpmshx_simple_2d_config_v1* config,
    const tpmshx_simple_callbacks_v1* callbacks,
    tpmshx_simple_2d_result_v1* output, char* error, size_t capacity) {
    return guarded([&] {
        if (!handle || !arrays || !sizes || !config || !output)
            throw std::invalid_argument("null SIMPLE solve argument");
        const auto input = [&](std::size_t i) { return tpmshx::ArrayView<const double>{arrays[i],sizes[i]}; };
        const auto state = [&](std::size_t i) { return tpmshx::ArrayView<double>{arrays[i],sizes[i]}; };
        const auto& c = *config;
        for (auto f : {c.ideal_gas,c.massflux_inlet,c.close_outlet_on_exit,c.have_inlet_density_reference}) flag(f);
        const tpmshx::Simple2DMaterialView material{input(0),input(1),input(2),input(3),input(4),input(5)};
        const tpmshx::Simple2DStateView fields{state(6),state(7),state(8),state(9),state(10),state(11),state(12),state(13)};
        tpmshx::Simple2DBoundaryView boundary{input(14),input(15),c.reference_inlet_velocity,c.taper_flux_scale,{}};
        if (c.have_inlet_density_reference) boundary.inlet_density_reference = c.inlet_density_reference;
        tpmshx::Simple2DControl control{c.max_iterations,c.inner_sweeps,c.alpha_velocity,c.alpha_pressure,
            c.alpha_density,c.pressure_reference_absolute,c.gas_constant,c.cf_anisotropy,
            c.ideal_gas != 0,c.massflux_inlet != 0,c.close_outlet_on_exit != 0,
            {c.f2.momentum_tolerance,c.f2.local_mass_tolerance,c.f2.global_mass_tolerance,c.f2.backflow_maximum,
             c.f2.velocity_check_tolerance,c.f2.stall_ratio,c.f2.confirmations,c.f2.momentum_interval,c.f2.stall_window}};
        tpmshx_simple_callbacks_v1 local_callbacks{};
        if (callbacks) {
            local_callbacks = *callbacks;
            control.cancel = callbacks->cancel ? cancel : nullptr;
            control.progress = callbacks->progress ? progress : nullptr;
            control.context = &local_callbacks;
        }
        const auto r = handle->solver.solve(material,boundary,fields,control);
        const auto result=tpmshx::simple_2d_c_view(r,handle->solver.massflux_target());
        *output = result;
    },error,capacity);
}

int TPMSHX_THERMAL_CALL tpmshx_simple_2d_history_v1(
    const tpmshx_simple_2d_handle* handle, uint32_t kind, double* values, size_t capacity,
    size_t* required, char* error, size_t error_capacity) {
    return guarded([&] {
        if (!handle || !required || kind > 3 || (!values && capacity))
            throw std::invalid_argument("invalid SIMPLE history query");
        const auto& h = handle->solver.history();
        const std::vector<double>* scalar = kind == 0 ? &h.legacy : (kind == 1 ? &h.local_mass : &h.global_mass);
        if (kind == 3 && h.momentum.size() > std::numeric_limits<std::size_t>::max()/8)
            throw std::invalid_argument("SIMPLE history exceeds addressable size");
        *required = kind == 3 ? h.momentum.size()*8 : scalar->size();
        if (!values) return;
        if (capacity < *required) throw std::invalid_argument("SIMPLE history output buffer is too short");
        if (kind != 3) { std::copy(scalar->begin(),scalar->end(),values); return; }
        for (const auto& record : h.momentum) {
            *values++ = static_cast<double>(record.iteration); *values++ = record.residual.maximum;
            for (std::size_t i = 0; i < 2; ++i) *values++ = record.residual.numerator[i];
            for (std::size_t i = 0; i < 2; ++i) *values++ = record.residual.denominator[i];
            for (std::size_t i = 0; i < 2; ++i) *values++ = record.residual.component[i];
        }
    },error,error_capacity);
}
}
