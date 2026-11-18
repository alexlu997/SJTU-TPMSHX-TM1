#pragma once

#include "tpmshx/fluid_properties.hpp"

namespace tpmshx {

enum class EnergyRelation { integral_cp_T, eos_h_TP, capacity_temperature, prescribed_temperature };
enum class ConductivitySource { prepared, outer_transport, local_eos, prescribed };
enum class HeatTransferSampling {
    inlet, outer_mean_inlet_reference,
    thermal_local_at_inlet_pressure, inlet_then_thermal_local_at_inlet_pressure, prescribed
};

// These choices retain the selected route's physical meaning before iteration.
struct SidePhysics {
    Fluid transport_fluid;
    EnergyRelation energy;
    ConductivitySource conductivity;
    HeatTransferSampling heat_transfer;

    bool eos_energy() const { return energy==EnergyRelation::eos_h_TP; }
    bool local_heat_transfer(bool warm=true) const {
        return heat_transfer==HeatTransferSampling::thermal_local_at_inlet_pressure
            || (warm && heat_transfer==HeatTransferSampling::inlet_then_thermal_local_at_inlet_pressure);
    }
    const char* transport_provider() const { return uses_co2_eos(transport_fluid)?"HEOS":"model_resource"; }
};

}  // namespace tpmshx
