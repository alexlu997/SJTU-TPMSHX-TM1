#include "tpmshx/solver_c_api.h"
#include "tpmshx/quick_design_driver.hpp"

#include <cstdio>
#include <exception>

namespace {
bool cancelled(void* context) {
    const auto& cb = *static_cast<const tpmshx_callbacks_v1*>(context);
    return cb.cancel && cb.cancel(cb.context) != 0;
}
void progress(void* context, unsigned percent) {
    const auto& cb = *static_cast<const tpmshx_callbacks_v1*>(context);
    if (cb.progress) cb.progress(cb.context,percent);
}
int fail(int status, const char* message, char* error, size_t capacity) noexcept {
    if (error && capacity) std::snprintf(error,capacity,"%s",message);
    return status;
}
}

extern "C" uint32_t TPMSHX_THERMAL_CALL tpmshx_solver_abi_version(void) {
    return TPMSHX_SOLVER_ABI_VERSION;
}

extern "C" int TPMSHX_THERMAL_CALL tpmshx_solve_quick_design_v1(
    const size_t* shape, double* const* arrays, const size_t* sizes,
    const tpmshx_qd_config_v1* config, const tpmshx_callbacks_v1* callbacks,
    tpmshx_qd_result_v1* result, char* error, size_t error_capacity) {
    using namespace tpmshx;
    if (!shape || !arrays || !sizes || !config || !result || !error || !error_capacity)
        return fail(TPMSHX_INVALID_ARGUMENT,"missing Quick Design argument or error buffer",error,error_capacity);
    if (config->topology > TPMSHX_GYROID || config->arrangement > TPMSHX_COUNTER
        || config->property_mode > TPMSHX_MEAN || config->warm_start > 1
        || config->sides[0].fluid > TPMSHX_SCO2 || config->sides[1].fluid > TPMSHX_SCO2)
        return fail(TPMSHX_INVALID_ARGUMENT,"unsupported Quick Design enum or warm_start",error,error_capacity);
    try {
        const auto view = [&](size_t i) { return ArrayView<const double>{arrays[i],sizes[i]}; };
        const auto out = [&](size_t i) { return ArrayView<double>{arrays[i],sizes[i]}; };
        const GridView grid{shape[0],shape[1],shape[2],view(0),view(1),view(2)};
        const QuickDesignGeometry geometry{config->length,config->span,config->height,
            config->cell_length,config->area_density,config->hydraulic_diameter,view(3),view(4),view(5)};
        const auto side = [&](size_t i) {
            const auto& s = config->sides[i];
            return QuickDesignSide{static_cast<Fluid>(s.fluid),s.inlet_temperature,
                s.inlet_pressure,s.mass_flow,s.inlet_pressure_fraction};
        };
        // Copy only the callback table, so the adapter never casts away const.
        auto cb = callbacks ? *callbacks : tpmshx_callbacks_v1{};
        const QuickDesignControl control{config->max_iterations,config->chunk_iterations,
            config->q_relative_tolerance,config->alpha,config->warm_start != 0,
            cb.cancel ? cancelled : nullptr,cb.progress ? progress : nullptr,&cb};
        const auto native = solve_quick_design(grid,geometry,static_cast<Topology>(config->topology),
            static_cast<QuickDesignArrangement>(config->arrangement),
            static_cast<QuickDesignProperties>(config->property_mode),side(0),side(1),
            {out(6),out(7),out(8)},control);
        tpmshx_qd_result_v1 output{};
        output.stop = static_cast<uint32_t>(native.stop);
        output.completed_passes = native.completed_passes;
        for (size_t p = 0; p < native.completed_passes; ++p) {
            const auto& source = native.passes[p];
            auto& destination = output.passes[p];
            destination.stop = static_cast<uint32_t>(source.thermal.stop);
            destination.iterations = source.thermal.iterations;
            destination.residual = source.thermal.residual;
            destination.q_b = source.thermal.q_b;
            for (size_t s = 0; s < 2; ++s) {
                const auto& from = source.sides[s];
                const auto& props = from.properties;
                destination.sides[s] = {from.evaluation_temperature,props.rho,props.mu,props.k,props.cp,
                    props.pr,from.reynolds,from.speed,from.hv,from.conductivity};
            }
        }
        if (native.completed_passes)
            for (size_t s = 0; s < 2; ++s) {
                const auto& from = native.pressure[s];
                output.pressure[s] = {from.inlet,from.outlet,from.choked ? 1u : 0u};
            }
        *result = output;
        error[0] = '\0';
        return TPMSHX_OK;
    } catch (const QuickDesignWaterFieldError& exception) {
        return fail(TPMSHX_WATER_FIELD,exception.what(),error,error_capacity);
    } catch (const WaterStateError& exception) {
        return fail(TPMSHX_WATER_INPUT,exception.what(),error,error_capacity);
    } catch (const std::invalid_argument& exception) {
        return fail(TPMSHX_INVALID_ARGUMENT,exception.what(),error,error_capacity);
    } catch (const std::domain_error& exception) {
        return fail(TPMSHX_ARITHMETIC_ERROR,exception.what(),error,error_capacity);
    } catch (const std::exception& exception) {
        return fail(TPMSHX_NATIVE_ERROR,exception.what(),error,error_capacity);
    } catch (...) {
        return fail(TPMSHX_NATIVE_ERROR,"unknown native Quick Design exception",error,error_capacity);
    }
}
