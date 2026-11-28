#pragma once

#include "tpmshx/geometry.hpp"
#include "tpmshx/property_c_api.h"
#include <memory>
#include <string>

namespace tpmshx::preparation {

std::shared_ptr<const geometry::PhiIndex> geometry_index(Topology topology, std::size_t resolution);
geometry::Geometry cached_geometry(Topology topology, double cell_mm, double wall_mm, std::size_t resolution);
std::array<double,5> cached_co2(double temperature, double pressure);
double cached_sco2(const std::string& key, double temperature, double pressure);
tpmshx_preparation_cache_info_v1 scalar_cache_info(std::uint32_t id);
void clear_scalar_cache(std::uint32_t id);

} // namespace tpmshx::preparation
