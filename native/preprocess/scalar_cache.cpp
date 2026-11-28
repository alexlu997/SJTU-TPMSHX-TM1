#include "scalar_cache.hpp"
#include "preparation_properties.hpp"
#include <algorithm>
#include <cstring>
#include <list>
#include <map>
#include <mutex>
#include <tuple>
#include <utility>

namespace tpmshx::preparation {
namespace {

// Keys use IEEE bits so even a NaN cannot invalidate the map ordering.
std::uint64_t bits(double value) {
    std::uint64_t result;
    static_assert(sizeof(result) == sizeof(value));
    std::memcpy(&result, &value, sizeof(result));
    return (result << 1) == 0 ? 0 : result;
}

template<class Key, class Value, std::size_t capacity>
class LruCache {
    using Entries = std::list<std::pair<Key, Value>>;
    Entries entries_;
    std::map<Key, typename Entries::iterator> index_;
    std::mutex mutex_;
    std::size_t hits_ = 0, misses_ = 0;

public:
    template<class Compute>
    Value get(const Key& key, Compute compute) {
        {
            const std::lock_guard<std::mutex> lock(mutex_);
            const auto found = index_.find(key);
            if (found != index_.end()) {
                ++hits_;
                entries_.splice(entries_.begin(), entries_, found->second);
                return found->second->second;
            }
            ++misses_;
        }

        auto value = compute();
        const std::lock_guard<std::mutex> lock(mutex_);
        const auto found = index_.find(key);
        if (found != index_.end()) return found->second->second;
        entries_.emplace_front(key, std::move(value));
        try {
            index_.emplace(key, entries_.begin());
        } catch (...) {
            entries_.pop_front();
            throw;
        }
        if (entries_.size() > capacity) {
            index_.erase(entries_.back().first);
            entries_.pop_back();
        }
        return entries_.front().second;
    }

    tpmshx_preparation_cache_info_v1 info() {
        const std::lock_guard<std::mutex> lock(mutex_);
        return {hits_, misses_, capacity, entries_.size()};
    }

    void clear() {
        const std::lock_guard<std::mutex> lock(mutex_);
        index_.clear();
        entries_.clear();
        hits_ = misses_ = 0;
    }
};

using Bits = std::uint64_t;
LruCache<std::pair<Topology, std::size_t>, std::shared_ptr<const geometry::PhiIndex>, 2> indices;
LruCache<std::tuple<Topology, Bits, Bits, std::size_t>, geometry::Geometry, 32768> geometries;
LruCache<std::pair<Bits, Bits>, std::array<double, 5>, 4096> co2;
LruCache<std::tuple<std::string, Bits, Bits>, double, 4096> sco2;

template<class Function>
auto with_cache(std::uint32_t id, Function function) {
    switch (id) {
    case TPMSHX_CACHE_GEOMETRY: return function(geometries);
    case TPMSHX_CACHE_CO2: return function(co2);
    case TPMSHX_CACHE_SCO2: return function(sco2);
    default: throw std::invalid_argument("unknown preparation cache ID");
    }
}
} // namespace

std::shared_ptr<const geometry::PhiIndex> geometry_index(Topology topology, std::size_t resolution) {
    return indices.get({topology, resolution}, [&] {
        return std::make_shared<const geometry::PhiIndex>(geometry::PhiIndex::from_topology(topology, resolution));
    });
}

geometry::Geometry cached_geometry(Topology topology, double cell_mm, double wall_mm, std::size_t resolution) {
    return geometries.get({topology, bits(cell_mm), bits(wall_mm), resolution}, [&] {
        if (resolution == 0) {
            geometry::validate_scalar_dimensions(cell_mm, wall_mm);
            throw std::invalid_argument("geometry resolution N must be a positive integer within size_t");
        }
        const auto index = geometry_index(topology, resolution);
        return geometry::standard_geometry(*index, geometry::calibration(topology), cell_mm, wall_mm);
    });
}

std::array<double, 5> cached_co2(double temperature, double pressure) {
    return co2.get({bits(temperature), bits(pressure)}, [&] {
        const auto values = co2_pt({}, {&temperature, 1}, {&pressure, 1}, true);
        std::array<double, 5> result;
        if (values.size() != result.size()) throw std::runtime_error("native EOS result extent is incorrect");
        std::copy(values.begin(), values.end(), result.begin());
        return result;
    });
}

double cached_sco2(const std::string& key, double temperature, double pressure) {
    return sco2.get({key, bits(temperature), bits(pressure)}, [&] {
        validate_sco2({&temperature, 1}, {&pressure, 1});
        return sco2_pt(0, {key}, {&temperature, 1}, {&pressure, 1}).at(0);
    });
}

tpmshx_preparation_cache_info_v1 scalar_cache_info(std::uint32_t id) {
    return with_cache(id, [](auto& cache) { return cache.info(); });
}

void clear_scalar_cache(std::uint32_t id) {
    with_cache(id, [](auto& cache) { cache.clear(); });
}
} // namespace tpmshx::preparation
