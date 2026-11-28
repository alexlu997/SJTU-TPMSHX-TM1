#include "tpmshx/result_core.hpp"

#include <limits>

namespace tpmshx::result {
namespace {

template<class View> std::size_t checked_count(const View& view, std::size_t width) {
    const auto count = element_count(view.rank, view.shape);
    if (count > std::numeric_limits<std::size_t>::max() / width)
        throw std::invalid_argument("result array bytes overflow size_t");
    const auto address = reinterpret_cast<std::uintptr_t>(view.data);
    if (count && (!view.data || address % width || count * width - 1 > std::numeric_limits<std::uintptr_t>::max() - address))
        throw std::invalid_argument("result array requires valid aligned storage");
    return count;
}

}  // namespace

std::size_t element_count(std::size_t rank, const std::size_t* shape) {
    if (rank && (!shape || reinterpret_cast<std::uintptr_t>(shape) % alignof(std::size_t)))
        throw std::invalid_argument("result array requires valid shape storage");
    std::size_t count = 1;
    for (std::size_t i = 0; i < rank; ++i) if (!shape[i]) return 0;
    for (std::size_t i = 0; i < rank; ++i) {
        if (count > std::numeric_limits<std::size_t>::max() / shape[i])
            throw std::invalid_argument("result array extent overflows size_t");
        count *= shape[i];
    }
    return count;
}

void append_event(Diagnostics& diagnostics, std::uint32_t flags, std::uint32_t operation, bool scalar) {
    if (!flags) return;
    if (flags > 15 || operation < TPMSHX_RESULT_ADD || operation > TPMSHX_RESULT_SQUARE)
        throw std::logic_error("invalid internal result FP event");
    if (diagnostics.event_count >= TPMSHX_RESULT_FP_EVENT_COUNT)
        throw std::logic_error("result FP event extent exceeded");
    diagnostics.events[diagnostics.event_count++] = {flags, operation, scalar ? 1u : 0u, 0};
}

Array::Array(const RawArray& input, Kind kind)
    :raw_(input), count_(checked_count(input, sizeof(double))), kind_(kind) {}
std::vector<std::size_t> Array::shape() const {
    if (!raw_.rank) return {};
    return {raw_.shape, raw_.shape + raw_.rank};
}
double Array::at(std::size_t index) const {
    if (index >= count_) throw std::out_of_range("result array index exceeds shape");
    return raw_.data[index];
}

Labels::Labels(const RawLabels& input):raw_(input), count_(checked_count(input, sizeof(std::int32_t))) {}
std::int32_t Labels::at(std::size_t index) const {
    if (index >= count_) throw std::out_of_range("result label index exceeds shape");
    return raw_.data[index];
}

}  // namespace tpmshx::result
