#pragma once
#include "tpmshx/finite_volume.hpp"
#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <utility>
#include <vector>

namespace tpmshx::grid {
using Values=std::vector<double>;
struct End { std::optional<double> center,width,center2,width2; };
struct Port { int direction; bool active; std::array<End,2> ends; };
struct Aligned { Values widths; Values lengths; double total; std::vector<std::int64_t> counts; };
struct WallSpec {std::size_t layers,minimum;double first,growth;};
// Scalar configuration quotients reject a zero divisor, as Python float division does.
double divide(double a,double b);
bool port_window_within(double cross_length,double center,double width);
Values segment_lengths(const Values& ordered_bounds);
double python_sum(const Values& values);
std::vector<std::uint8_t> aligned_filter(double length,const Values& points);
Aligned aligned(std::size_t count,const Values& ordered_bounds);
Values uniform(std::size_t count,double length);
Values wall(double width,std::size_t bulk,std::size_t layers,double first,double growth);
WallSpec wall_spec(std::size_t dimensions,std::size_t knots);
Values cumulative_widths(ArrayView<const double> widths);
Values port_edges(const Values& lengths,const std::vector<Port>& ports,std::size_t axis);
Values port_wall_axis(std::size_t dimensions,std::size_t count,const Values& outer_bounds,
                      const Values& bulk_bounds,std::size_t& minimum,std::size_t axis=0);
Values breaks_2d(const Values& lengths,const std::vector<Port>& ports,std::size_t axis);
std::array<std::size_t,3> suggest_grid(const Values& lengths,double diameter,std::size_t budget,
                                     std::array<std::size_t,3> minimum);
std::array<double,2> adaptive_grid(const Values& lengths,double diameter,double alpha);
std::array<std::int32_t,7> axis_map(std::int32_t direction);
Values rectangles(const Port& port,double cross2_length);
Values port_overlap(const Values& widths,double lower,double upper,bool staggered=false);
std::array<Values,2> port_fractions(const Values& widths,double lower,double upper,bool uniform=false);
std::array<Values,2> partial_masks(const Port& port,const Values& cross1,
                                  const Values* cross2,std::size_t n_cross2);
Values continuous_centres(std::size_t count,double length,const Values* widths);
Values sigmoid_centres(std::size_t count,double length,const Values* widths);
}  // namespace tpmshx::grid

namespace tpmshx {
// These preparation forms accept empty widths and nonfinite bounds.
// The full-solver port header keeps its stricter checked forms.
std::vector<double> port_overlap_1d_unchecked(ArrayView<const double> widths,double lo,double hi,
                                              bool staggered=false);
std::pair<std::vector<double>,std::vector<double>> port_fractions_1d_unchecked(
    ArrayView<const double> widths,double lo,double hi,bool uniform=false);
}  // namespace tpmshx
