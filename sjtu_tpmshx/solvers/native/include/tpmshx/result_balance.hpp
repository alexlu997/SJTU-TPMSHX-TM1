#pragma once

#include "tpmshx/result_balance_c_api.h"
#include "tpmshx/result_core.hpp"
#include "tpmshx/result_arithmetic.hpp"

#include <cstddef>

namespace tpmshx::result::balance {

using NormValues = tpmshx_result_norm_values_v1;
using MassValues = tpmshx_result_mass_values_v1;
using PlaneValues = tpmshx_result_plane_values_v1;
using EnergyPhase = tpmshx_result_energy_phase_v1;
using EnergyValues = tpmshx_result_energy_values_v1;

NormValues norms(const RawArray& residual, Diagnostics&);
MassValues mass(const RawArray* faces, std::size_t dimension, Diagnostics&);
PlaneValues plane_sums(const RawArray* planes, std::size_t plane_count, Diagnostics&);
EnergyValues energy(const EnergyPhase* phases, std::size_t phase_count, double reservoir);
Number zone_mean(const RawArray& values, const RawArray* weights, Diagnostics&);
Number zone_std(const RawArray& values, const RawArray* weights, std::uint32_t square_fused, Diagnostics&);
Number zone_minimum(const RawArray& values, Diagnostics&);
Number zone_maximum(const RawArray& values, Diagnostics&);
Number zone_spread(const RawArray& values, Diagnostics&);
arithmetic::Tensor zone_power_two(const RawArray& values, std::uint32_t square_fused, Diagnostics&);
arithmetic::Tensor zone_speed_from_squared(const RawArray& u, const RawArray& v, Diagnostics&);
double zone_cv(double deviation, double mean);

}  // namespace tpmshx::result::balance
