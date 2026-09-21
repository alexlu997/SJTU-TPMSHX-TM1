# Run from the repository root: make -f native/Makefile
CXX = c++
CXXFLAGS = -std=c++17 -O2 -Wall -Wextra -Wpedantic -Werror
BUILD_DIR = .cache/native

ifeq ($(shell uname -s),Darwin)
SHARED_SUFFIX = dylib
SHARED_LDFLAGS = -dynamiclib
else
SHARED_SUFFIX = so
SHARED_LDFLAGS = -shared
endif

all: $(BUILD_DIR)/libtpmshx_thermal.a

shared: $(BUILD_DIR)/libtpmshx_thermal.$(SHARED_SUFFIX)

$(BUILD_DIR)/enthalpy_sweeps.o: native/src/enthalpy_sweeps.cpp native/include/tpmshx/enthalpy_sweeps.hpp
	mkdir -p $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) -I native/include -c $< -o $@

$(BUILD_DIR)/libtpmshx_thermal.a: $(BUILD_DIR)/enthalpy_sweeps.o
	$(AR) rcs $@ $<

$(BUILD_DIR)/libtpmshx_thermal.$(SHARED_SUFFIX): native/src/enthalpy_sweeps.cpp native/src/thermal_c_api.cpp native/include/tpmshx/enthalpy_sweeps.hpp native/include/tpmshx/thermal_c_api.h
	mkdir -p $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) -fPIC $(SHARED_LDFLAGS) -I native/include native/src/enthalpy_sweeps.cpp native/src/thermal_c_api.cpp -o $@

.PHONY: all shared
