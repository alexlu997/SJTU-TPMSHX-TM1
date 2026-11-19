#include "tpmshx/geometry.hpp"
#include "tpmshx/model_coefficients.hpp"
#include <array>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace g = tpmshx::geometry;

void check(bool passed, const char* message) {
    if (!passed) throw std::runtime_error(message);
}

template<class Operation>
void invalid(Operation operation, const char* expected) {
    try { operation(); }
    catch (const std::invalid_argument& error) {
        check(std::string(error.what()) == expected, "incorrect invalid-model reason");
        return;
    }
    throw std::runtime_error("invalid model was accepted");
}

int main() {
    try {
        const g::PhiIndex index({2, 2, 2}, {0., 1., 1., 1., 1., 1., 1., 2.});
        const std::array<double, 5> levels{-1., 0., .5, 1., 2.};
        const std::array<std::size_t, 5> occupied{0, 1, 1, 7, 8};
        const std::array<std::int64_t, 5> faces{0, 3, 3, 3, 0};
        for (std::size_t i = 0; i < levels.size(); ++i) {
            const auto counts = index.counts(levels[i]);
            check(counts.occupied == occupied[i] && counts.faces == faces[i], "inclusive face count changed");
        }
        auto model = g::calibration(tpmshx::Topology::diamond);
        model.level_set = {-1., 0.};
        invalid([&] { g::minimum_solid_geometry(index, model, {4., 8.}, {.3, .6}); },
                "The level-set model does not certify monotone solid volume");

        std::vector<g::Co2GeometryNode> nodes;
        for (const auto& row : tpmshx::model_coefficients::co2_geometry_nodes[0])
            nodes.push_back({row[0], row[1], row[2], row[3], row[4]});
        for (auto& node : nodes)
            node.epsilon_single = node.cell_mm == 6. && node.wall_mm == .4 ? .45 : .2;
        const g::Co2GeometryTable table(nodes, g::calibration(tpmshx::Topology::diamond).solid_tortuosity);
        const auto minimum = table.minimum_solid_geometry({5.2, 7.8}, {.33, .57});
        check(minimum.cell_mm == 6. && minimum.wall_mm == .4 && minimum.epsilon == .9,
              "CO2 minimum missed an interior node");
        nodes.push_back(nodes.front());
        invalid([&] { g::Co2GeometryTable duplicate(nodes, model.solid_tortuosity); },
                "CO2 geometry requires a complete, unique 5 by 4 grid");
        const auto empty = g::lut_geometry(model.solid_tortuosity, 0., 0., 16.);
        check(empty.material.geometry.hydraulic_diameter == 0. && empty.hydraulic_radius == 0.,
              "empty LUT node did not retain zero diameter");
        std::cout << "geometry kernel checks passed\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
