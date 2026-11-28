#pragma once

#include "tpmshx/geometry.hpp"
#include "tpmshx/preparation_case.hpp"
#include <memory>
#include <string>

namespace tpmshx::preparation {

std::shared_ptr<const geometry::PhiIndex> geometry_index(Topology topology, std::size_t resolution);
geometry::Geometry cached_geometry(Topology topology, double cell_mm, double wall_mm, std::size_t resolution);
std::array<double,5> cached_co2(double temperature, double pressure);
double cached_sco2(const std::string& key, double temperature, double pressure);
using InletValue = std::shared_ptr<const PreparationInletCache>;
using TableValue = std::shared_ptr<const SigmoidLUT2D>;
InletValue find_inlet(const PreparationInletKey&);
InletValue publish_inlet(const PreparationInletKey&, PreparationInletCache);
TableValue find_table(Topology, std::size_t resolution, const SigmoidLUT2D& axes,
                      std::array<bool,2> descending = {});
TableValue publish_table(Topology, std::size_t resolution, SigmoidLUT2D table,
                         std::array<bool,2> descending = {});

tpmshx_preparation_cache_info_v1 scalar_cache_info(std::uint32_t id);
void clear_scalar_cache(std::uint32_t id);

} // namespace tpmshx::preparation
