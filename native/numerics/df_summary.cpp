#include "tpmshx/preparation_df.hpp"

#include <cmath>
#include <stdexcept>

namespace tpmshx::preparation {
DfSummary df_summary(ArrayView<const double> values, bool scalar) {
    if (!values.size) throw std::invalid_argument("zero-size array to reduction operation minimum which has no identity");
    if (scalar) return {values[0], values[0], 1u};
    double low = values[0], high = values[0];
    for (std::size_t i = 1; i < values.size; ++i) {
        const double value = values[i];
        if (std::isnan(value)) { low = value; high = value; break; }
        low = value <= low ? value : low;
        high = value >= high ? value : high;
    }
    return {low, high, 0u};
}

}  // namespace tpmshx::preparation
