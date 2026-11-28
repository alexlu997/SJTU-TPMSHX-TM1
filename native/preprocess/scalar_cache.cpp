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
    std::optional<Value> find(const Key& key) {
        const std::lock_guard<std::mutex> lock(mutex_);
        const auto found = index_.find(key);
        if (found != index_.end()) {
            ++hits_;
            entries_.splice(entries_.begin(), entries_, found->second);
            return found->second->second;
        }
        ++misses_;
        return {};
    }

    Value publish(const Key& key, Value value) {
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

    template<class Compute>
    Value get(const Key& key, Compute compute) {
        if (auto found = find(key)) return *found;
        return publish(key, compute());
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

auto nu_key(const Sco2NuSelection& selection) {
    std::array<std::optional<Bits>, 2> alpha;
    for (std::size_t i = 0; i < alpha.size(); ++i)
        if (selection.alpha[i]) alpha[i] = bits(*selection.alpha[i]);
    return std::make_tuple(selection.mode, alpha, selection.parameter_version, selection.source, selection.applicability);
}

auto inlet_key(const PreparationInletKey& key) {
    std::optional<decltype(nu_key(Sco2NuSelection{}))> selection;
    if (key.sco2_nu) selection = nu_key(*key.sco2_nu);
    return std::make_tuple(key.geometry.topology, bits(key.geometry.cell_length_mm), bits(key.geometry.wall_thickness_mm),
        key.fluid, bits(key.velocity_m_s), bits(key.temperature_K), bits(key.pressure_Pa), selection, key.co2_geometry);
}

using TableKey = std::tuple<Topology, std::size_t, std::vector<double>, std::vector<double>, std::array<bool,2>>;
LruCache<decltype(inlet_key(PreparationInletKey{})), InletValue, 4096> inlets;
LruCache<TableKey, TableValue, 32> tables;

template<class Function>
auto with_cache(std::uint32_t id, Function function) {
    switch (id) {
    case TPMSHX_CACHE_GEOMETRY: return function(geometries);
    case TPMSHX_CACHE_CO2: return function(co2);
    case TPMSHX_CACHE_SCO2: return function(sco2);
    case TPMSHX_PREPARATION_CACHE_INLET: return function(inlets);
    case TPMSHX_PREPARATION_CACHE_SIGMOID: return function(tables);
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

InletValue find_inlet(const PreparationInletKey& key) {
    return inlets.find(inlet_key(key)).value_or(nullptr);
}
InletValue publish_inlet(const PreparationInletKey& key, PreparationInletCache value) {
    return inlets.publish(inlet_key(key), std::make_shared<const PreparationInletCache>(std::move(value)));
}
TableValue find_table(Topology topology, std::size_t resolution, const SigmoidLUT2D& axes, std::array<bool,2> descending) {
    return tables.find({topology, resolution, axes.cell_mm, axes.wall_mm, descending}).value_or(nullptr);
}
TableValue publish_table(Topology topology, std::size_t resolution, SigmoidLUT2D value,
                         std::array<bool,2> descending, TableFileFields file_fields) {
    const TableKey key{topology, resolution, value.cell_mm, value.wall_mm, descending};
    return tables.publish(key, std::make_shared<const CachedTable>(CachedTable{std::move(value),std::move(file_fields)}));
}

tpmshx_preparation_cache_info_v1 scalar_cache_info(std::uint32_t id) {
    return with_cache(id, [](auto& cache) { return cache.info(); });
}

void clear_scalar_cache(std::uint32_t id) {
    with_cache(id, [](auto& cache) { cache.clear(); });
}
} // namespace tpmshx::preparation
