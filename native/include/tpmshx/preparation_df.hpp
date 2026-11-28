#pragma once

#include "tpmshx/finite_volume.hpp"
#include "tpmshx/preparation_df_c_api.h"

#include <cstddef>
#include <cstdint>
#include <string>
#include <stdexcept>
#include <utility>
#include <vector>

namespace tpmshx::preparation {

struct DfPair { double K, cF; };
using DfPressure = tpmshx_preparation_df_pressure_v1;
using DfSelection = tpmshx_preparation_df_selection_v1;
using DfSummary = tpmshx_preparation_df_summary_v1;
struct DfRows {
    std::vector<double> lengths, walls;
    std::vector<std::int64_t> source_index;
};

DfPair fixed_df(std::uint32_t topology, double length_mm, double wall_mm);
std::vector<DfPair> fixed_df_batch(std::uint32_t topology,
    ArrayView<const double> lengths, ArrayView<const double> walls);
DfPressure df_incompressible(std::uint32_t topology, double length_mm, double wall_mm,
    double speed, double density, double viscosity, double channel_length);
DfPressure df_compressible(std::uint32_t topology, double length_mm, double wall_mm,
    double mass_flux, double temperature, double inlet_pressure, double viscosity,
    double channel_length, bool strict);
std::uint32_t df_experiment_scope(std::uint32_t topology, std::uint32_t fluid_a,
    std::uint32_t fluid_b, std::uint32_t geometry_mode, bool symmetric,
    double cell_length_mm, double wall_thickness_mm, ArrayView<const double> domain);
inline constexpr auto experimental_layout_error =
    "experimental calibration currently requires uniform L/t; "
    "continuous Shanghai Gyroid air/water fields may use "
    "the 7/0.6 calibration as an exploratory extrapolation";
std::string experimental_domain_error(std::size_t side);
std::string decimal(double value);
std::string significant(double value,int precision);
struct DfExperimentError : std::invalid_argument {
    DfExperimentError(const std::string& message,bool outside_window)
        :std::invalid_argument(message),velocity_window(outside_window) {}
    bool velocity_window;
};
std::pair<DfSelection,DfPair> df_experiment_side(std::uint32_t topology,std::uint32_t fluid,
    double cell,double wall,double speed,bool transfer);
DfSelection df_select(std::uint32_t topology, std::uint32_t fluid, bool transfer,
    ArrayView<const double> lengths, ArrayView<const double> walls,
    ArrayView<const double> velocity, bool has_velocity);
std::vector<DfPair> df_scales(std::uint32_t topology, const DfSelection& selection,
    ArrayView<const double> lengths, ArrayView<const double> walls);
std::vector<double> df_apply_scale(ArrayView<const double> base,
    ArrayView<const double> scale, bool prepared_scalar_factor);
DfSummary df_summary(ArrayView<const double> values, bool scalar);
DfPair df_co2_factors();
DfRows df_project_rows(std::size_t nx, std::size_t ny,
    ArrayView<const double> lengths, ArrayView<const double> walls,
    bool length_column_major, bool wall_column_major,
    std::uint32_t direction, std::size_t target_count,
    ArrayView<const double> dx, ArrayView<const double> dy,
    ArrayView<const double> target_widths);
std::vector<DfPair> df_row_means(std::size_t rows, std::size_t columns,
    ArrayView<const double> permeability, ArrayView<const double> forchheimer,
    bool permeability_column_major, bool forchheimer_column_major);

}  // namespace tpmshx::preparation
