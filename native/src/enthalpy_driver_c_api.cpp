#include "tpmshx/enthalpy_driver_c_api.h"
#include "tpmshx/enthalpy_driver.hpp"
#include "enthalpy_c_views.hpp"

#include <CoolProp/CoolProp.h>
#include <CoolProp/Exceptions.h>

#include <cstdio>
#include <exception>

namespace {
bool cancelled(void* context) {
    const auto& cb = *static_cast<const tpmshx_enthalpy_callbacks_v1*>(context);
    return cb.cancel && cb.cancel(cb.context) != 0;
}
int fail(int status, const char* message, char* error, size_t capacity) noexcept {
    if (error && capacity) std::snprintf(error,capacity,"%s",message);
    return status;
}
}

extern "C" uint32_t TPMSHX_THERMAL_CALL tpmshx_enthalpy_driver_abi_version(void) {
    return TPMSHX_ENTHALPY_DRIVER_ABI_VERSION;
}

extern "C" int TPMSHX_THERMAL_CALL tpmshx_solve_enthalpy_v1(
    const size_t* shape, double* const* arrays, const size_t* sizes,
    const tpmshx_enthalpy_config_v1* config,
    const tpmshx_enthalpy_callbacks_v1* callbacks,
    tpmshx_enthalpy_result_v1* result, char* error, size_t error_capacity) {
    using namespace tpmshx;
    if (!shape || !arrays || !sizes || !config || !result || !error || !error_capacity)
        return fail(TPMSHX_ENTHALPY_INVALID_ARGUMENT,"missing true-h argument or error buffer",error,error_capacity);
    if (config->sides[0].fluid > TPMSHX_ENTHALPY_SCO2 || config->sides[1].fluid > TPMSHX_ENTHALPY_SCO2
        || config->warm_a > 1 || config->warm_b > 1 || config->warm_solid > 1
        || config->coupled_gate > 1 || config->equation_gate > 1)
        return fail(TPMSHX_ENTHALPY_INVALID_ARGUMENT,"invalid true-h fluid or boolean flag",error,error_capacity);
    try {
        const auto v = [&](size_t i) { return ArrayView<const double>{arrays[i],sizes[i]}; };
        const auto out = [&](size_t i) { return ArrayView<double>{arrays[i],sizes[i]}; };
        const GridView grid{shape[0],shape[1],shape[2],v(0),v(1),v(2)};
        const auto side = [&](size_t i, size_t offset) {
            return EnthalpySideView{static_cast<Fluid>(config->sides[i].fluid),
                config->sides[i].inlet_temperature,config->sides[i].inlet_pressure,
                v(offset),v(offset+1),v(offset+2),v(offset+3),v(offset+4),v(offset+5)};
        };
        auto cb = callbacks ? *callbacks : tpmshx_enthalpy_callbacks_v1{};
        EnthalpyControl control{config->max_iterations,config->sweeps,config->omega,
            config->update_tolerance,{},{},config->table_directory ? config->table_directory : "",
            cb.cancel ? cancelled : nullptr,&cb};
        if (config->coupled_gate) control.coupled_energy_tolerance = config->coupled_tolerance;
        if (config->equation_gate) control.equation_energy_tolerance = config->equation_tolerance;
        const auto native = solve_enthalpy(grid,side(0,4),side(1,10),v(3),
            {out(16),out(17),out(18),out(19),out(20),config->warm_a != 0,
             config->warm_b != 0,config->warm_solid != 0},control);
        const auto output=enthalpy_c_view(native);
        *result = output;
        error[0] = '\0';
        return TPMSHX_ENTHALPY_OK;
    } catch (const WaterStateError& exception) {
        return fail(TPMSHX_ENTHALPY_WATER_STATE,exception.what(),error,error_capacity);
    } catch (const CoolProp::CoolPropBaseError& exception) {
        // CoolProp's Python AbstractState declarations use except +ValueError;
        // PropsSI likewise reports failed actual states as ValueError.
        return fail(TPMSHX_ENTHALPY_INVALID_ARGUMENT,exception.what(),error,error_capacity);
    } catch (const std::invalid_argument& exception) {
        return fail(TPMSHX_ENTHALPY_INVALID_ARGUMENT,exception.what(),error,error_capacity);
    } catch (const std::domain_error& exception) {
        return fail(TPMSHX_ENTHALPY_ARITHMETIC_ERROR,exception.what(),error,error_capacity);
    } catch (const std::exception& exception) {
        return fail(TPMSHX_ENTHALPY_NATIVE_ERROR,exception.what(),error,error_capacity);
    } catch (...) {
        return fail(TPMSHX_ENTHALPY_NATIVE_ERROR,"unknown native true-h exception",error,error_capacity);
    }
}
