// Qualification bridge only. The application does not load this library.
#include "tpmshx/simple_pressure.hpp"
#include "tpmshx/thermal_c_api.h"

#include <algorithm>
#include <cstdio>
#include <iterator>
#include <stdexcept>

namespace {
using namespace tpmshx;

struct Views {
    const std::size_t* shape;
    double** arrays;
    const std::size_t* sizes;
    ArrayView<const double> c(std::size_t i) const { return {arrays[i], sizes[i]}; }
    ArrayView<double> m(std::size_t i) const { return {arrays[i], sizes[i]}; }
    GridView grid() const { return {shape[0], shape[1], shape[2], c(0), c(1), c(2)}; }
    SimpleFacesView<const double> velocity() const { return {c(3), c(4), c(5)}; }
    SimpleFacesView<double> writable_velocity() const { return {m(3), m(4), m(5)}; }
    SimpleFacesView<const double> coefficients() const { return {c(6), c(7), c(8)}; }
};

template <typename F> int checked(F operation, char* error, std::size_t capacity) {
    if (capacity && error) error[0] = '\0';
    try {
        operation();
        return 0;
    } catch (const std::invalid_argument& e) {
        if (capacity && error) std::snprintf(error, capacity, "%s", e.what());
        return 1;
    } catch (const std::domain_error& e) {
        if (capacity && error) std::snprintf(error, capacity, "%s", e.what());
        return 2;
    } catch (const std::exception& e) {
        if (capacity && error) std::snprintf(error, capacity, "%s", e.what());
        return 3;
    }
}
}  // namespace

extern "C" TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL test_simple_pressure_create(
    int dimension, const std::size_t* shape, double** arrays, const std::size_t* sizes,
    const unsigned char* outlet, std::size_t outlet_size, void** handle,
    char* error, std::size_t capacity) {
    *handle = nullptr;
    return checked([&] {
        const Views v{shape, arrays, sizes};
        *handle = new SimplePressureAssembly(dimension, v.grid(), {outlet, outlet_size});
    }, error, capacity);
}

extern "C" TPMSHX_THERMAL_API void TPMSHX_THERMAL_CALL test_simple_pressure_destroy(void* handle) {
    delete static_cast<SimplePressureAssembly*>(handle);
}

extern "C" TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL test_simple_pressure_assemble(
    void* handle, const std::size_t* shape, double** arrays, const std::size_t* sizes,
    int* row_offsets, int* columns, double* values, double* rhs, unsigned char* pins,
    std::size_t buffer_nnz, std::size_t* nnz, char* error, std::size_t capacity) {
    return checked([&] {
        if (!handle) throw std::invalid_argument("missing pressure assembly handle");
        const Views v{shape, arrays, sizes};
        const auto& system = static_cast<SimplePressureAssembly*>(handle)->assemble(
            v.grid(), v.velocity(), v.coefficients(), v.c(9));
        if (system.values.size() > buffer_nnz) throw std::invalid_argument("test CSR buffer is too small");
        std::copy(system.row_offsets.begin(), system.row_offsets.end(), row_offsets);
        std::copy(system.columns.begin(), system.columns.end(), columns);
        std::copy(system.values.begin(), system.values.end(), values);
        std::copy(system.rhs.begin(), system.rhs.end(), rhs);
        std::copy(system.pin_mask.begin(), system.pin_mask.end(), pins);
        *nnz = system.values.size();
    }, error, capacity);
}

extern "C" TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL test_simple_pressure_primitive(
    int operation, int dimension, const std::size_t* shape, double** arrays,
    const std::size_t* sizes, const unsigned char* outlet, std::size_t outlet_size,
    const unsigned char* excluded, std::size_t excluded_size, double alpha_p,
    double* metrics, char* error, std::size_t capacity) {
    return checked([&] {
        const Views v{shape, arrays, sizes};
        const SimpleBoundaryView boundary{v.c(14), v.c(15), {outlet, outlet_size}};
        if (operation == 1) {
            correct_simple_pressure(dimension, v.grid(), boundary, v.m(10), v.c(11),
                v.writable_velocity(), v.coefficients(), v.c(12), v.c(13), alpha_p);
        } else if (operation == 2) {
            close_simple_outlet(dimension, v.grid(), {outlet, outlet_size},
                v.writable_velocity(), v.c(12), v.c(13));
        } else if (operation == 3) {
            apply_simple_y_boundary(dimension, v.grid(), boundary,
                v.writable_velocity(), v.c(12), v.c(13));
        } else if (operation == 4) {
            const auto mass = simple_mass_audit(dimension, v.grid(), v.velocity(),
                v.c(9), {excluded, excluded_size});
            const auto legacy = simple_legacy_mass_residual(dimension, v.grid(), v.velocity(), v.c(9));
            simple_face_mass_flux(dimension, v.grid(), v.velocity(), v.c(9), {v.m(16), v.m(17), v.m(18)});
            const double result[] = {mass.local_residual, static_cast<double>(mass.counted_cells),
                mass.mass_in, mass.mass_out, mass.global_residual, mass.backflow_fraction,
                legacy.residual, legacy.reference};
            std::copy(std::begin(result), std::end(result), metrics);
        } else {
            throw std::invalid_argument("unknown SIMPLE qualification operation");
        }
    }, error, capacity);
}
