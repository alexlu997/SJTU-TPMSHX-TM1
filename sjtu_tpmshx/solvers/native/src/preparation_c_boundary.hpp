#pragma once

#include "tpmshx/preparation_c_api.h"
#include "field_c_boundary.hpp"
#include <stdexcept>
#include <string>

namespace tpmshx::preparation::c_api {

using fields::c_api::product;
using fields::c_api::require_buffer;
using fields::c_api::require_output;

template<class A, class B> void require_disjoint(
    const A* first, std::size_t first_count, const B* second, std::size_t second_count) {
    require_buffer(first, first_count);
    require_buffer(second, second_count);
    if (!first_count || !second_count) return;
    const auto a = reinterpret_cast<std::uintptr_t>(first);
    const auto b = reinterpret_cast<std::uintptr_t>(second);
    const auto a_last = a + product(first_count, sizeof(A)) - 1;
    const auto b_last = b + product(second_count, sizeof(B)) - 1;
    if (a <= b_last && b <= a_last)
        throw std::invalid_argument("preparation output overlaps another buffer");
}

class StateError : public std::runtime_error {
public:
    StateError(int status, const std::string& text) : std::runtime_error(text), status_(status) {}
    int status() const noexcept { return status_; }
private:
    int status_;
};

template<class Function> int boundary(char* error, std::size_t size, Function function) noexcept {
    using fields::c_api::message;
    if (!fields::c_api::error_buffer_valid(error, size)) return TPMSHX_PREPARATION_INVALID;
    try { function(); message(error, size, ""); return TPMSHX_PREPARATION_OK; }
    catch (const StateError& failure) { message(error, size, failure.what()); return failure.status(); }
    catch (const std::invalid_argument& failure) {
        message(error, size, failure.what()); return TPMSHX_PREPARATION_INVALID;
    }
    catch (const std::bad_alloc&) {
        message(error, size, "preparation allocation failed"); return TPMSHX_PREPARATION_ALLOCATION;
    }
    catch (const std::exception& failure) {
        message(error, size, failure.what()); return TPMSHX_PREPARATION_RUNTIME;
    }
    catch (...) {
        message(error, size, "unknown native preparation failure"); return TPMSHX_PREPARATION_RUNTIME;
    }
}

}  // namespace tpmshx::preparation::c_api
