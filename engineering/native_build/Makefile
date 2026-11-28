# Run from the repository root: make -f engineering/native_build/Makefile
CXX = c++
CXXFLAGS = -std=c++17 -O2 -Wall -Wextra -Wpedantic -Werror
BUILD_DIR = .cache/native
TPMSHX_EIGEN_INCLUDE ?= .cache/native-deps/src/Eigen-5.0.1
EIGEN_CPPFLAGS = -DEIGEN_MPL2_ONLY -isystem "$(TPMSHX_EIGEN_INCLUDE)"

all: $(BUILD_DIR)/libtpmshx_thermal.a

check-eigen:
	@test -f "$(TPMSHX_EIGEN_INCLUDE)/Eigen/SparseLU" || { printf '%s\n' "Missing Eigen/SparseLU in $(TPMSHX_EIGEN_INCLUDE); set TPMSHX_EIGEN_INCLUDE to the existing locked Eigen headers." >&2; exit 1; }

$(BUILD_DIR)/enthalpy_sweeps.o: native/solver/enthalpy_sweeps.cpp native/solver/energy_fv_rows.hpp native/include/tpmshx/conservative_energy.hpp native/include/tpmshx/enthalpy_sweeps.hpp native/include/tpmshx/finite_volume.hpp
	mkdir -p $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) -I native/include -c $< -o $@

$(BUILD_DIR)/temperature_driver.o: native/solver/temperature_driver.cpp native/solver/temperature_run_state.hpp native/solver/temperature_active_line.hpp native/solver/temperature_faces.hpp native/solver/energy_fv_rows.hpp native/include/tpmshx/temperature_driver.hpp native/include/tpmshx/conservative_energy.hpp native/include/tpmshx/enthalpy_sweeps.hpp native/include/tpmshx/finite_volume.hpp | check-eigen
	mkdir -p $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) $(EIGEN_CPPFLAGS) -I native/include -c $< -o $@

$(BUILD_DIR)/conservative_energy.o: native/solver/conservative_energy.cpp native/solver/energy_fv_rows.hpp native/include/tpmshx/conservative_energy.hpp native/include/tpmshx/enthalpy_sweeps.hpp native/include/tpmshx/finite_volume.hpp
	mkdir -p $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) -I native/include -c $< -o $@

$(BUILD_DIR)/libtpmshx_thermal.a: $(BUILD_DIR)/enthalpy_sweeps.o $(BUILD_DIR)/temperature_driver.o $(BUILD_DIR)/conservative_energy.o
	$(RM) $@
	$(AR) rcs $@ $^

$(BUILD_DIR)/temperature_driver_smoke: tests/cpp/temperature_driver_smoke.cpp $(BUILD_DIR)/libtpmshx_thermal.a native/solver/temperature_faces.hpp native/solver/energy_fv_rows.hpp native/include/tpmshx/temperature_driver.hpp native/include/tpmshx/conservative_energy.hpp native/include/tpmshx/finite_volume.hpp
	$(CXX) $(CXXFLAGS) -I native/include $< $(BUILD_DIR)/libtpmshx_thermal.a -o $@

$(BUILD_DIR)/conservative_energy_smoke: tests/cpp/conservative_energy_smoke.cpp $(BUILD_DIR)/libtpmshx_thermal.a native/include/tpmshx/conservative_energy.hpp
	$(CXX) $(CXXFLAGS) -I native/include $< $(BUILD_DIR)/libtpmshx_thermal.a -o $@

check: $(BUILD_DIR)/temperature_driver_smoke $(BUILD_DIR)/conservative_energy_smoke
	$(BUILD_DIR)/temperature_driver_smoke
	$(BUILD_DIR)/conservative_energy_smoke

.PHONY: all check check-eigen
