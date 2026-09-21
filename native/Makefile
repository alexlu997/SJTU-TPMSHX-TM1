# Run from the repository root: make -f native/Makefile
CXX = c++
CXXFLAGS = -std=c++17 -O2 -Wall -Wextra -Wpedantic -Werror
BUILD_DIR = .cache/native

all: $(BUILD_DIR)/libtpmshx_thermal.a

$(BUILD_DIR)/enthalpy_sweeps.o: native/src/enthalpy_sweeps.cpp native/include/tpmshx/enthalpy_sweeps.hpp
	mkdir -p $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) -I native/include -c $< -o $@

$(BUILD_DIR)/libtpmshx_thermal.a: $(BUILD_DIR)/enthalpy_sweeps.o
	$(AR) rcs $@ $<

.PHONY: all
