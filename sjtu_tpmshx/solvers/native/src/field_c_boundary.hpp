#pragma once

#include <cstddef>
#include <cstdint>
#include <exception>
#include <limits>
#include <new>
#include <stdexcept>

namespace tpmshx::fields::c_api {

inline bool error_buffer_valid(char* error, std::size_t size) noexcept {
    if (!error || !size) return false;
    const auto address = reinterpret_cast<std::uintptr_t>(error);
    return size - 1 <= std::numeric_limits<std::uintptr_t>::max() - address;
}

inline std::size_t product(std::size_t first, std::size_t second) {
    if (second && first > std::numeric_limits<std::size_t>::max() / second)
        throw std::invalid_argument("field buffer element count overflows size_t");
    return first * second;
}

template<class T> void require_buffer(const T* pointer, std::size_t count) {
    const auto bytes = product(count, sizeof(T));
    if (!count) return;
    if (!pointer) throw std::invalid_argument("nonempty field buffer is null");
    const auto address = reinterpret_cast<std::uintptr_t>(pointer);
    if (bytes > static_cast<std::size_t>(std::numeric_limits<std::ptrdiff_t>::max())
        || address % alignof(T)
        || bytes - 1 > std::numeric_limits<std::uintptr_t>::max() - address)
        throw std::invalid_argument("field buffer address, range or alignment is invalid");
}

template<class T> void require_output(T* pointer, std::size_t actual, std::size_t expected) {
    if (actual != expected) throw std::invalid_argument("field output element count is incorrect");
    require_buffer(pointer, actual);
}

inline void message(char* error, std::size_t size, const char* text) noexcept {
    if (!error || !size) return;
    std::size_t index = 0;
    while (index + 1 < size && text[index]) { error[index] = text[index]; ++index; }
    error[index] = '\0';
}

template<class Function> int boundary(char* error, std::size_t size, Function function) noexcept {
    if (!error_buffer_valid(error, size)) return 1;
    try { function(); message(error, size, ""); return 0; }
    catch (const std::invalid_argument& failure) { message(error, size, failure.what()); return 1; }
    catch (const std::bad_alloc&) { message(error, size, "field allocation failed"); return 2; }
    catch (const std::exception& failure) { message(error, size, failure.what()); return 3; }
    catch (...) { message(error, size, "unknown native field failure"); return 3; }
}

}  // namespace tpmshx::fields::c_api
