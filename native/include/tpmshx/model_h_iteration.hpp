#pragma once

#include "tpmshx/anderson_state.hpp"

#include <array>
#include <cstddef>
#include <optional>
#include <vector>

namespace tpmshx {

struct ModelHIterationOverrides {
    // Zero retains the route default, including its refined-grid budget.
    std::size_t max_iterations=0;
    double temperature_tolerance=0.,q_relative_tolerance=0.;
    bool active() const { return max_iterations || temperature_tolerance || q_relative_tolerance; }
};

struct ModelHIterationSettings {
    std::size_t max_iterations,chunk_iterations;
    double temperature_tolerance,q_relative_tolerance;
    std::size_t total_iteration_budget;
    bool accelerate=false;
    std::size_t acceleration_sweeps=25,acceleration_history=6;
};

struct ModelHControl2D {
    std::size_t max_iterations, chunk_iterations;
    double q_relative_tolerance;
    bool warm_start = false, accelerate = false, red_black = false;
    bool (*cancel)(void*) = nullptr;
    void (*progress)(void*, std::size_t, std::size_t) = nullptr;
    void* context = nullptr;
    bool second_order_a = true, second_order_b = true;
    // FullCC uses the existing h(T) model with its own strict final-state
    // energy gate. The original model-h certificate/stopping defaults remain.
    bool strict_energy_balance = false;
    double temperature_tolerance = .01;
};

struct ModelHControl3D {
    std::size_t max_iterations, chunk_iterations;
    double q_relative_tolerance, alpha_a, alpha_solid, alpha_b;
    bool warm_start=false, accelerate=false, red_black=false;
    bool (*cancel)(void*)=nullptr;
    void (*progress)(void*,std::size_t,std::size_t)=nullptr;
    void* context=nullptr;
    bool second_order_a=true, second_order_b=true;
    bool strict_energy_balance=false;
    double temperature_tolerance=.01;
    std::size_t cpu_threads=1;
};

enum class ModelHPhase { active, completed, cancelled, failed };

struct ModelHIterationState {
    std::array<std::vector<double>,3> temperature;
    std::vector<double> previous;
    double previous_q=0.;
    bool have_q=false;
    std::optional<ModelHChunkState> chunk;
};

}  // namespace tpmshx
