// Isolated property/QD Nu caller; no Python runtime or production selection.
// stdin: id props fluid T_K P_Pa
//        id transport fluid T_K P_Pa
//        id water water T_K P_Pa
//        id nu fluid Diamond|Gyroid Re L_m Dh_m
//        id fullnu fluid Diamond|Gyroid Re L_m Dh_m Pr C_eff
//        id roughness air baseline|norris_1a|bhatti_shah_1b Re eps_m Dh_m
// stdout TSV: id/status/rho/mu/k/cp/Pr/Nu/melting_K/error_hex.
#include "tpmshx/fluid_properties.hpp"

#include <array>
#include <atomic>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace {
const double nan = std::numeric_limits<double>::quiet_NaN();
struct Request {
    std::string id, operation, error;
    tpmshx::Fluid fluid = tpmshx::Fluid::air;
    tpmshx::Topology topology = tpmshx::Topology::diamond;
    tpmshx::RoughnessMode roughness=tpmshx::RoughnessMode::baseline;
    double a = nan, b = nan, c = nan, pr=nan, multiplier=1.;
};
struct Result {
    int status = 0;
    std::array<double,7> values{nan,nan,nan,nan,nan,nan,nan};
    std::string error;
};

double real(const std::string& value) {
    std::size_t used = 0;
    const double number = std::stod(value,&used);
    if (used != value.size()) throw std::invalid_argument("invalid property number");
    return number;
}

Request parse(const std::string& line, std::size_t index) {
    Request row;
    row.id = "row"+std::to_string(index);
    try {
        std::istringstream input(line);
        std::string fluid, topology, a, b, c, extra;
        if (!(input >> row.id >> row.operation >> fluid))
            throw std::invalid_argument("expected id operation fluid and state");
        if (fluid == "air") row.fluid = tpmshx::Fluid::air;
        else if (fluid == "water") row.fluid = tpmshx::Fluid::water;
        else if (fluid == "sco2") row.fluid = tpmshx::Fluid::sco2;
        else throw std::invalid_argument("unsupported property fluid");
        if (row.operation == "nu" || row.operation == "fullnu") {
            if (!(input >> topology >> a >> b >> c))
                throw std::invalid_argument("expected topology Re L_m Dh_m");
            if (row.operation=="fullnu") {
                std::string pr,multiplier;
                if (!(input>>pr>>multiplier)) throw std::invalid_argument("expected actual Pr C_eff");
                row.pr=real(pr); row.multiplier=real(multiplier);
            }
            if (input>>extra) throw std::invalid_argument("unexpected trailing Nu data");
            if (topology == "Diamond") row.topology = tpmshx::Topology::diamond;
            else if (topology == "Gyroid") row.topology = tpmshx::Topology::gyroid;
            else throw std::invalid_argument("unsupported property topology");
            row.c = real(c);
        } else if (row.operation=="roughness") {
            std::string mode;
            if (!(input>>mode>>a>>b>>c) || input>>extra) throw std::invalid_argument("expected roughness mode Re eps_m Dh_m");
            if (mode=="baseline") row.roughness=tpmshx::RoughnessMode::baseline;
            else if (mode=="norris_1a") row.roughness=tpmshx::RoughnessMode::norris_1a;
            else if (mode=="bhatti_shah_1b") row.roughness=tpmshx::RoughnessMode::bhatti_shah_1b;
            else throw std::invalid_argument("unknown roughness mode");
            row.c=real(c);
        } else if (row.operation == "props" || row.operation == "water" || row.operation=="transport") {
            if (!(input >> a >> b) || input >> extra)
                throw std::invalid_argument("expected temperature_K pressure_Pa");
            if (row.operation == "water" && row.fluid != tpmshx::Fluid::water)
                throw std::invalid_argument("water check requires water");
        } else throw std::invalid_argument("unsupported property operation");
        row.a = real(a); row.b = real(b);
    } catch (const std::exception& error) { row.error = error.what(); }
    return row;
}

Result evaluate(tpmshx::PropertyEvaluator& context, const Request& request) {
    Result result;
    try {
        if (!request.error.empty()) throw std::invalid_argument(request.error);
        if (request.operation == "props" || request.operation=="transport") {
            const auto value = request.operation=="props" ? context.evaluate(request.fluid,request.a,request.b)
                : context.transport(request.fluid,request.a,request.b);
            result.values = {value.rho,value.mu,value.k,value.cp,value.pr,nan,nan};
        } else if (request.operation == "water") {
            result.values[6] = context.check_water(request.a,request.b);
        } else if (request.operation=="roughness") {
            result.values[5]=tpmshx::nu_extra_roughness_factor(request.a,request.roughness,request.b,request.c);
        } else if (request.operation=="fullnu") {
            result.values[5]=tpmshx::fluid_nusselt(request.fluid,request.topology,request.a,
                                                request.pr,request.b,request.c,request.multiplier);
        } else {
            result.values[5] = context.quick_design_nu(request.fluid,request.topology,
                                                       request.a,request.b,request.c);
        }
    } catch (const std::invalid_argument& error) {
        result = Result{}; result.status = 1; result.error = error.what();
    } catch (const std::exception& error) {
        result = Result{}; result.status = 2; result.error = error.what();
    }
    return result;
}

std::string hex(const std::string& message) {
    const char* digits = "0123456789abcdef";
    std::string result;
    for (const unsigned char byte : message) {
        result += digits[byte >> 4]; result += digits[byte & 15];
    }
    return result;
}
}  // namespace

int main(int argc, char** argv) {
    try {
        std::size_t workers = 1;
        if (argc == 3 && std::string(argv[1]) == "--workers"
            && (std::string(argv[2]) == "1" || std::string(argv[2]) == "2"))
            workers = std::string(argv[2]) == "1" ? 1 : 2;
        else if (argc != 1) throw std::invalid_argument("usage: fluid_properties_smoke [--workers 1|2]");
        std::vector<Request> requests;
        std::string line;
        while (std::getline(std::cin,line))
            if (!line.empty()) requests.push_back(parse(line,requests.size()));
        std::vector<Result> results(requests.size());
        // Constructors below allocate no HEOS state. Both contexts must first
        // construct/update their own EOS state inside the concurrent workers.
        std::array<tpmshx::PropertyEvaluator,2> contexts;
        std::atomic<std::size_t> ready{0};
        std::atomic<bool> start{false};
        const auto group = [&](std::size_t worker) {
            ++ready;
            while (!start.load()) std::this_thread::yield();
            for (std::size_t i = worker; i < requests.size(); i += workers)
                results[i] = evaluate(contexts[worker],requests[i]);
        };
        if (workers == 1) { start.store(true); group(0); }
        else {
            std::thread a(group,0), b(group,1);
            while (ready.load() != workers) std::this_thread::yield();
            start.store(true);
            a.join(); b.join();
        }
        std::cout << std::scientific << std::setprecision(17);
        std::cout << "#workers\t" << workers << '\n';
        std::cout << "id\tstatus\trho\tmu\tk\tcp\tPr\tNu\tmelting_K\terror_hex\n";
        for (std::size_t i = 0; i < requests.size(); ++i) {
            std::cout << requests[i].id << '\t' << results[i].status;
            for (double value : results[i].values) {
                std::cout << '\t';
                if (std::isnan(value)) std::cout << "nan";
                else std::cout << value;
            }
            std::cout << '\t' << hex(results[i].error) << '\n';
        }
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 2;
    }
}
