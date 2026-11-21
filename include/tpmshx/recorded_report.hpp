#pragma once
#include <algorithm>
#include <cstdint>
#include <iterator>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <type_traits>
#include <utility>
#include <variant>
#include <vector>

namespace tpmshx::result::stage {
// Public reports retain the order in which their fields are defined.
template<class T> class ReportObject {
    using Item = std::pair<std::string, T>;
    std::vector<Item> values_;
public:
    ReportObject() = default;
    ReportObject(std::initializer_list<Item> values):values_(values) {}
    auto begin() {return values_.begin();}
    auto end() {return values_.end();}
    auto begin() const {return values_.begin();}
    auto end() const {return values_.end();}
    auto find(std::string_view key) {return std::find_if(begin(), end(), [&](const auto& row){return row.first == key;});}
    auto find(std::string_view key) const {return std::find_if(begin(), end(), [&](const auto& row){return row.first == key;});}
    std::size_t count(std::string_view key) const {return find(key) != end();}
    bool empty() const {return values_.empty();}
    std::size_t size() const {return values_.size();}
    T& at(std::string_view key) {
        const auto found = find(key);
        if (found == end()) throw std::out_of_range("missing report field");
        return found->second;
    }
    const T& at(std::string_view key) const {
        const auto found = find(key);
        if (found == end()) throw std::out_of_range("missing report field");
        return found->second;
    }
    template<class U> auto emplace(std::string key, U&& value) {
        auto found = find(key);
        if (found != end()) return std::make_pair(found, false);
        values_.emplace_back(std::move(key), std::forward<U>(value));
        return std::make_pair(std::prev(end()), true);
    }
    template<class U> void insert_or_assign(std::string key, U&& value) {
        const auto found = find(key);
        if (found == end()) values_.emplace_back(std::move(key), std::forward<U>(value));
        else found->second = std::forward<U>(value);
    }
};
// Reports contain recorded data and contain no executable objects.
struct Report {
    using List = std::vector<Report>;
    using Object = ReportObject<Report>;
    std::variant<std::nullptr_t, bool, std::int64_t, std::uint64_t, double, std::string, List, Object> value;
    Report():value(nullptr) {}
    Report(std::nullptr_t):value(nullptr) {}
    Report(bool v):value(v) {}
    Report(int v):value(static_cast<std::int64_t>(v)) {}
    Report(std::int64_t v):value(v) {}
    template<class T, std::enable_if_t<std::is_integral_v<T> && std::is_unsigned_v<T>, int> = 0>
    Report(T v):value(static_cast<std::uint64_t>(v)) {}
    Report(double v):value(v) {}
    Report(const char* v):value(std::string(v)) {}
    Report(std::string v):value(std::move(v)) {}
    Report(List v):value(std::move(v)) {}
    Report(Object v):value(std::move(v)) {}
    Report(std::optional<bool> v):Report() {if(v) value=*v;}
};
std::string json(const Report&);
}
