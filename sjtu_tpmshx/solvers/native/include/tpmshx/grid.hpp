#pragma once
#include "tpmshx/finite_volume.hpp"
#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <vector>

namespace tpmshx::grid {
using Values=std::vector<double>;
struct Scalar { double value; std::uint32_t precision,strong; };
using Scalars=std::vector<Scalar>;
struct End { std::optional<Scalar> center,width,center2,width2; };
struct Port { int direction; bool active; std::array<End,2> ends; };
struct Aligned { Values widths; Scalars lengths; Scalar total; std::vector<std::int64_t> counts; };
struct WallSpec {std::size_t layers,minimum;double first,growth;};
Scalar checked(Scalar value);
Scalar weak(double value);
Scalar add(Scalar a,Scalar b);
Scalar subtract(Scalar a,Scalar b);
Scalar multiply(Scalar a,Scalar b);
Scalar divide(Scalar a,Scalar b);
Scalar power(Scalar base,std::size_t exponent);
std::uint32_t result_precision(Scalar a,Scalar b);
bool less(Scalar a,Scalar b);
Scalars segment_lengths(const Scalars& ordered_bounds);
Scalar python_sum(const Scalars& values);
std::vector<std::uint8_t> aligned_filter(Scalar length,const Scalars& points);
Aligned aligned(std::size_t count,const Scalars& ordered_bounds);
Values uniform(std::size_t count,Scalar length);
Values wall(Scalar width,std::size_t bulk,std::size_t layers,double first,double growth);
Values wall(Scalar width,std::size_t bulk,std::size_t layers,Scalar first,Scalar growth);
WallSpec wall_spec(std::size_t dimensions,std::size_t knots);
Values cumulative_widths(ArrayView<const double> widths,std::uint32_t precision=64);
Scalars port_edges(const Scalars& lengths,const std::vector<Port>& ports,std::size_t axis);
Values port_wall_axis(std::size_t dimensions,std::size_t count,const Scalars& outer_bounds,
                      const Scalars& bulk_bounds,std::size_t& minimum,std::size_t axis=0);
Scalars breaks_2d(const Scalars& lengths,const std::vector<Port>& ports,std::size_t axis);
std::array<std::size_t,3> suggest_grid(const Scalars& lengths,Scalar diameter,std::size_t budget,
                                     std::array<std::size_t,3> minimum);
std::array<double,2> adaptive_grid(const Scalars& lengths,Scalar diameter,Scalar alpha);
std::array<std::int32_t,7> axis_map(std::int32_t direction);
Scalars rectangles(const Port& port,Scalar cross2_length);
Values port_overlap(const Values& widths,Scalar lower,Scalar upper,bool staggered=false,std::uint32_t width_precision=64);
std::array<Values,2> port_fractions(const Values& widths,Scalar lower,Scalar upper,bool uniform=false,
                                  std::uint32_t width_precision=64);
std::array<Values,2> partial_masks(const Port& port,const Values& cross1,
                                  const Values* cross2,std::size_t n_cross2,
                                  std::uint32_t precision1=64,std::uint32_t precision2=64);
Values continuous_centres(std::size_t count,Scalar length,const Values* widths);
Values sigmoid_centres(std::size_t count,Scalar length,const Values* widths,
                       std::uint32_t width_precision=64,std::uint32_t* output_precision=nullptr);
}  // namespace tpmshx::grid
