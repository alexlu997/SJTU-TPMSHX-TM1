#include <tpmshx/stages.hpp>
#include <iostream>

int main() {
    using namespace tpmshx::stages;
    try {
        CaseInput2D input;
        input.length_m = 0.182;
        input.height_m = 0.042;
        input.requested_nx = 20;
        input.requested_ny = 40;
        input.topology = TPMSHX_GYROID;
        input.cell_length_mm = 7.0;
        input.wall_thickness_mm = 0.4;
        input.solid_conductivity_W_mK = 16.0;

        auto& hot_air = input.sides[0];
        hot_air.velocity_m_s = 10.0;
        hot_air.temperature_K = 600.0;
        hot_air.pressure_Pa = 101325.0;

        auto& cold_air = input.sides[1];
        cold_air.velocity_m_s = 10.0;
        cold_air.temperature_K = 300.0;
        cold_air.pressure_Pa = 101325.0;
        cold_air.port.direction = 3; // The cold stream enters at the upper y face.

        RunControl control;
        control.result_id = "native-air-2d";
        control.cpu_threads = 2;

        auto prepared = prepare_case(input);
        auto result = run_case(prepared, control);
        auto performance = evaluate(result);

        std::cout << performance.view().json << '\n';
        return result.view().raw.converged ? 0 : 2;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
