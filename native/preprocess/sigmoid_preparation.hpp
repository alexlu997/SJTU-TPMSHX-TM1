#pragma once

#include "scalar_cache.hpp"

namespace tpmshx::preparation {

enum class ZonedOperation { capacities, resolve, prepare };

struct SpatialPrefix {
    PreparedZonedCase2D output;
    std::vector<std::pair<bool,std::size_t>> warning_order;
    std::vector<std::string> plain_warnings;
};

// The caller owns the prefix and releases it after finish or after an I/O failure.
struct ZonedPreparation {
    ZonedOperation operation;
    PreparationOptions options;
    ZonedInletFlow2D flow;
    std::array<std::optional<double>,2> targets{};
    bool physical_grid=false;
    bool needs_fields=true;
    SpatialPrefix prefix;
    SigmoidLUT2D requested_axes;
    TableValue table;
};

ZonedPreparation start_zoned(const ZonedFlowRequest2D&, ZonedOperation, const PreparationOptions&,
                             const PreparationCallbacks&, bool defer_missing_table);
PreparedZonedFlowCase2D finish_zoned(ZonedPreparation, const PreparationCallbacks&);
TableValue default_sigmoid_table(Topology, std::size_t cell_nodes, std::size_t wall_nodes, std::size_t resolution);
SigmoidLUT2D build_sigmoid_table(Topology, SigmoidLUT2D axes, std::size_t resolution);

} // namespace tpmshx::preparation
