# Run from the repository root: make -f native/Makefile
CXX = c++
CXXFLAGS = -std=c++17 -O2 -Wall -Wextra -Wpedantic -Werror
CC = cc
CFLAGS = -std=c11 -O2 -Wall -Wextra -Wpedantic -Werror
BUILD_DIR = .cache/native

ifeq ($(shell uname -s),Darwin)
SHARED_SUFFIX = dylib
SHARED_LDFLAGS = -dynamiclib -Wl,-install_name,@rpath/libtpmshx_thermal.dylib
else
SHARED_SUFFIX = so
SHARED_LDFLAGS = -shared
endif

all: $(BUILD_DIR)/libtpmshx_thermal.a

shared: $(BUILD_DIR)/libtpmshx_thermal.$(SHARED_SUFFIX)

$(BUILD_DIR)/enthalpy_sweeps.o: native/src/enthalpy_sweeps.cpp native/include/tpmshx/enthalpy_sweeps.hpp native/include/tpmshx/finite_volume.hpp
	mkdir -p $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) -I native/include -c $< -o $@

$(BUILD_DIR)/thermal_c_api.o: native/src/thermal_c_api.cpp native/include/tpmshx/thermal_c_api.h native/include/tpmshx/enthalpy_sweeps.hpp native/include/tpmshx/finite_volume.hpp
	mkdir -p $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) -I native/include -c $< -o $@

$(BUILD_DIR)/temperature_driver.o: native/src/temperature_driver.cpp native/include/tpmshx/temperature_driver.hpp native/include/tpmshx/finite_volume.hpp
	mkdir -p $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) -I native/include -c $< -o $@

$(BUILD_DIR)/conservative_energy.o: native/src/conservative_energy.cpp native/include/tpmshx/conservative_energy.hpp native/include/tpmshx/enthalpy_sweeps.hpp native/include/tpmshx/finite_volume.hpp
	mkdir -p $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) -I native/include -c $< -o $@

$(BUILD_DIR)/libtpmshx_thermal.a: $(BUILD_DIR)/enthalpy_sweeps.o $(BUILD_DIR)/thermal_c_api.o $(BUILD_DIR)/temperature_driver.o $(BUILD_DIR)/conservative_energy.o
	$(AR) rcs $@ $^

$(BUILD_DIR)/libtpmshx_thermal.$(SHARED_SUFFIX): native/src/enthalpy_sweeps.cpp native/src/thermal_c_api.cpp native/src/temperature_driver.cpp native/src/conservative_energy.cpp native/include/tpmshx/conservative_energy.hpp native/include/tpmshx/enthalpy_sweeps.hpp native/include/tpmshx/finite_volume.hpp native/include/tpmshx/thermal_c_api.h native/include/tpmshx/temperature_driver.hpp
	mkdir -p $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) -fPIC $(SHARED_LDFLAGS) -I native/include native/src/enthalpy_sweeps.cpp native/src/thermal_c_api.cpp native/src/temperature_driver.cpp native/src/conservative_energy.cpp -o $@

$(BUILD_DIR)/thermal_c_smoke.o: native/tests/thermal_c_smoke.c native/include/tpmshx/thermal_c_api.h
	mkdir -p $(BUILD_DIR)
	$(CC) $(CFLAGS) -I native/include -c $< -o $@

$(BUILD_DIR)/thermal_c_static: $(BUILD_DIR)/thermal_c_smoke.o $(BUILD_DIR)/libtpmshx_thermal.a
	$(CXX) $^ -o $@

$(BUILD_DIR)/thermal_c_shared: $(BUILD_DIR)/thermal_c_smoke.o $(BUILD_DIR)/libtpmshx_thermal.$(SHARED_SUFFIX)
	$(CXX) $^ -Wl,-rpath,$(abspath $(BUILD_DIR)) -o $@

$(BUILD_DIR)/thermal_cpp_smoke: native/tests/thermal_cpp_smoke.cpp $(BUILD_DIR)/libtpmshx_thermal.a native/include/tpmshx/enthalpy_sweeps.hpp native/include/tpmshx/finite_volume.hpp
	$(CXX) $(CXXFLAGS) -I native/include $< $(BUILD_DIR)/libtpmshx_thermal.a -o $@

$(BUILD_DIR)/temperature_driver_smoke: native/tests/temperature_driver_smoke.cpp $(BUILD_DIR)/libtpmshx_thermal.a native/include/tpmshx/temperature_driver.hpp native/include/tpmshx/finite_volume.hpp
	$(CXX) $(CXXFLAGS) -I native/include $< $(BUILD_DIR)/libtpmshx_thermal.a -o $@

$(BUILD_DIR)/conservative_energy_smoke: native/tests/conservative_energy_smoke.cpp $(BUILD_DIR)/libtpmshx_thermal.a native/include/tpmshx/conservative_energy.hpp
	$(CXX) $(CXXFLAGS) -I native/include $< $(BUILD_DIR)/libtpmshx_thermal.a -o $@

check: $(BUILD_DIR)/thermal_c_static $(BUILD_DIR)/thermal_c_shared $(BUILD_DIR)/thermal_cpp_smoke $(BUILD_DIR)/temperature_driver_smoke $(BUILD_DIR)/conservative_energy_smoke
	$(BUILD_DIR)/thermal_c_static
	$(BUILD_DIR)/thermal_c_shared
	$(BUILD_DIR)/thermal_cpp_smoke
	$(BUILD_DIR)/temperature_driver_smoke
	$(BUILD_DIR)/conservative_energy_smoke

.PHONY: all shared check
