// Isolated EOS qualification CLI; no Python runtime or production binding.
// eos_smoke --tables ABSOLUTE_DIRECTORY [--workers 1|2]
// stdin: id HEOS|BICUBIC&HEOS CO2|Water TP|HP temperature_or_enthalpy pressure
// stdout: TSV, SI units. Error bytes are losslessly hex-encoded in the last
// column; failed rows retain NaN outputs and never reuse an earlier state.
#include <AbstractState.h>
#include <Configuration.h>
#include <CoolProp.h>

#include <array>
#include <chrono>
#include <cmath>
#include <filesystem>
#include <iomanip>
#include <iostream>
#include <limits>
#include <map>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

namespace {
using Clock = std::chrono::steady_clock;
using Key = std::pair<std::string,std::string>;
const double nan = std::numeric_limits<double>::quiet_NaN();

struct Request {
    std::string id, backend, fluid, pair;
    double value = nan, pressure = nan;
    std::string error;
};
struct Result {
    int status = 0;
    std::array<double,6> fields{nan,nan,nan,nan,nan,nan}; // T,rho,cp,mu,k,h
    int phase = -1;
    double melting_temperature = nan;
    std::string error;
};
struct StateError : std::runtime_error { using std::runtime_error::runtime_error; };

void co2_scope(double temperature, double pressure) {
    if (!std::isfinite(temperature) || !std::isfinite(pressure))
        throw StateError("sCO2 state must be finite");
    if (temperature < 280.0 || temperature > 700.0)
        throw StateError("sCO2 temperature must be within 280..700 K");
    if (pressure < 7.9e6 || pressure > 16.e6)
        throw StateError("sCO2 pressure must be within 7.9..16 MPa");
}

class Evaluator {
    std::unique_ptr<CoolProp::AbstractState> state, water_guard;
    std::string fluid;

    double check_water(double temperature, double pressure) {
        if (!std::isfinite(temperature) || !std::isfinite(pressure)
            || temperature <= 0.0 || pressure <= 0.0)
            throw StateError("water requires finite positive K and Pa(abs)");
        try {
            water_guard->update(CoolProp::PT_INPUTS,pressure,temperature);
            const auto phase = water_guard->phase();
            if (phase == CoolProp::iphase_supercritical_liquid)
                throw StateError("high-pressure liquid: T-only model applicability unconfirmed");
            if (phase != CoolProp::iphase_liquid)
                throw StateError("only stable single-phase liquid water is supported");
            if (!water_guard->has_melting_line())
                throw StateError("solid/liquid stability unconfirmed");
            const double melting = water_guard->melting_line(CoolProp::iT,CoolProp::iP,pressure);
            if (!std::isfinite(melting) || temperature <= melting)
                throw StateError("freezing boundary or solid/metastable water unsupported");
            return melting;
        } catch (const StateError&) {
            throw;
        } catch (const std::exception& exception) {
            // Retain the original CoolProp diagnostic, as Python's water
            // guard does. A successful EOS update alone is not phase proof.
            throw StateError(exception.what());
        }
    }

public:
    Evaluator(const std::string& backend, const std::string& fluid_name)
        : state(CoolProp::AbstractState::factory(backend,fluid_name)), fluid(fluid_name) {
        if (fluid == "Water") water_guard.reset(CoolProp::AbstractState::factory("HEOS","Water"));
        // CoolProp 7.2 has a process-global tabular dataset library. Finish
        // its construction/table I/O serially before independent state
        // objects are handed to concurrent workers. Updates remain parallel.
        state->update(CoolProp::PT_INPUTS,fluid == "CO2" ? 8.e6 : 2.e5,300.);
        if (water_guard) check_water(300.,2.e5);
    }

    Result evaluate(const Request& request) {
        Result result;
        try {
            if (!std::isfinite(request.value) || !std::isfinite(request.pressure)
                || request.pressure <= 0.0)
                throw StateError("EOS input requires finite value and positive Pa(abs)");
            if (fluid == "CO2") {
                if (request.pair == "TP") co2_scope(request.value,request.pressure);
                else if (request.pressure < 7.9e6 || request.pressure > 16.e6)
                    throw StateError("sCO2 pressure must be within 7.9..16 MPa");
            } else if (request.pair == "TP") {
                result.melting_temperature = check_water(request.value,request.pressure);
            }
            if (request.pair == "TP")
                state->update(CoolProp::PT_INPUTS,request.pressure,request.value);
            else
                state->update(CoolProp::HmassP_INPUTS,request.value,request.pressure);
            const double temperature = state->T();
            if (fluid == "CO2") co2_scope(temperature,request.pressure);
            else result.melting_temperature = check_water(temperature,request.pressure);
            const std::array<double,6> values{temperature,state->rhomass(),state->cpmass(),
                state->viscosity(),state->conductivity(),state->hmass()};
            for (const double value : values)
                if (!std::isfinite(value)) throw std::domain_error("EOS produced a nonfinite property");
            if (values[0] <= 0.0 || values[1] <= 0.0 || values[2] <= 0.0
                || values[3] <= 0.0 || values[4] <= 0.0)
                throw std::domain_error("EOS produced a nonpositive physical property");
            result.fields = values;
            result.phase = static_cast<int>(state->phase());
        } catch (const StateError& exception) {
            result = Result{};
            result.status = 1;
            result.error = exception.what();
        } catch (const std::exception& exception) {
            result = Result{};
            result.status = 2;
            result.error = exception.what();
        }
        return result;
    }
};

double parse_number(const std::string& text) {
    std::size_t consumed = 0;
    const double value = std::stod(text,&consumed);
    if (consumed != text.size()) throw std::invalid_argument("invalid numeric input: " + text);
    return value;
}

Request parse_request(const std::string& line, std::size_t row) {
    Request request;
    request.id = "row"+std::to_string(row);
    try {
        std::istringstream stream(line);
        std::string value, pressure, extra;
        if (!(stream >> request.id >> request.backend >> request.fluid >> request.pair >> value >> pressure)
            || stream >> extra)
            throw StateError("expected: id backend fluid TP|HP value pressure");
        if (request.backend != "HEOS" && request.backend != "BICUBIC&HEOS")
            throw StateError("unsupported EOS backend; expected HEOS or BICUBIC&HEOS");
        if (request.fluid != "CO2" && request.fluid != "Water")
            throw StateError("unsupported fluid; project empirical Air is not replaced by HEOS Air");
        if (request.pair != "TP" && request.pair != "HP")
            throw StateError("unsupported input pair; expected TP or HP");
        request.value = parse_number(value);
        request.pressure = parse_number(pressure);
    } catch (const std::exception& exception) {
        request.error = exception.what();
    }
    return request;
}

std::string error_hex(const std::string& error) {
    const char* digits = "0123456789abcdef";
    std::string encoded;
    encoded.reserve(error.size()*2);
    for (unsigned char byte : error) {
        encoded.push_back(digits[byte >> 4]);
        encoded.push_back(digits[byte & 15]);
    }
    return encoded;
}

struct Worker {
    std::map<Key,std::unique_ptr<Evaluator>> states;
    std::map<Key,std::string> construction_errors;
};
}

int main(int argc, char** argv) {
    try {
        if (argc == 2 && std::string(argv[1]) == "--version") {
            std::cout << CoolProp::get_global_param_string("version") << '\t'
                      << CoolProp::get_global_param_string("gitrevision") << '\n';
            return 0;
        }
        std::filesystem::path table_directory;
        std::size_t workers = 1;
        for (int argument = 1; argument < argc; ++argument) {
            const std::string option(argv[argument]);
            if (option == "--tables" && argument+1 < argc) table_directory = argv[++argument];
            else if (option == "--workers" && argument+1 < argc) {
                const std::string value(argv[++argument]);
                if (value != "1" && value != "2") throw StateError("workers must be 1 or 2");
                workers = value == "1" ? 1 : 2;
            } else throw StateError("usage: eos_smoke --tables ABSOLUTE_DIRECTORY [--workers 1|2]");
        }
        if (table_directory.empty() || !table_directory.is_absolute())
            throw StateError("an explicit absolute table directory is required");
        std::filesystem::create_directories(table_directory);
        const std::string tables = table_directory.lexically_normal().generic_string()+"/";
        CoolProp::set_config_string(ALTERNATIVE_TABLES_DIRECTORY,tables);
        // Keep CoolProp 7.2 defaults/reference state. Only the table directory
        // changes in this standalone process; compressed tables remain default.
        std::vector<Request> requests;
        std::string line;
        while (std::getline(std::cin,line))
            if (!line.empty()) requests.push_back(parse_request(line,requests.size()));
        const auto start = Clock::now();
        std::vector<Worker> contexts(workers);
        for (std::size_t index = 0; index < requests.size(); ++index) {
            const auto& request = requests[index];
            if (!request.error.empty()) continue;
            const Key key{request.backend,request.fluid};
            auto& worker = contexts[index%workers];
            if (worker.states.count(key) || worker.construction_errors.count(key)) continue;
            try { worker.states.emplace(key,std::make_unique<Evaluator>(key.first,key.second)); }
            catch (const std::exception& exception) { worker.construction_errors[key] = exception.what(); }
        }
        const auto ready = Clock::now();
        std::vector<Result> results(requests.size());
        const auto evaluate_group = [&](std::size_t worker_index) {
            auto& context = contexts[worker_index];
            for (std::size_t index = worker_index; index < requests.size(); index += workers) {
                const auto& request = requests[index];
                if (!request.error.empty()) {
                    results[index].status = 1;
                    results[index].error = request.error;
                    continue;
                }
                const Key key{request.backend,request.fluid};
                const auto failure = context.construction_errors.find(key);
                if (failure != context.construction_errors.end()) {
                    results[index].status = 2;
                    results[index].error = failure->second;
                } else results[index] = context.states.at(key)->evaluate(request);
            }
        };
        if (workers == 1) evaluate_group(0);
        else {
            std::thread a(evaluate_group,0), b(evaluate_group,1);
            a.join(); b.join();
        }
        const auto finished = Clock::now();
        std::cout << std::setprecision(17) << std::scientific;
        std::cout << "#version\t" << CoolProp::get_global_param_string("version") << '\n';
        std::cout << "#tables\t" << CoolProp::get_config_string(ALTERNATIVE_TABLES_DIRECTORY) << '\n';
        std::cout << "#workers\t" << workers << '\n';
        std::cout << "#initialization_s\t" << std::chrono::duration<double>(ready-start).count() << '\n';
        std::cout << "#batch_s\t" << std::chrono::duration<double>(finished-ready).count() << '\n';
        std::cout << "id\tstatus\tbackend\tfluid\tpair\tinput\tpressure_Pa\tT_K\trho_kg_m3\tcp_J_kgK\tmu_Pas\tk_W_mK\th_J_kg\tphase\tmelting_K\terror_hex\n";
        for (std::size_t index = 0; index < requests.size(); ++index) {
            const auto& request = requests[index];
            const auto& result = results[index];
            std::cout << request.id << '\t' << result.status << '\t' << request.backend << '\t'
                      << request.fluid << '\t' << request.pair << '\t' << request.value << '\t' << request.pressure;
            for (const double value : result.fields) std::cout << '\t' << value;
            std::cout << '\t' << result.phase << '\t' << result.melting_temperature
                      << '\t' << error_hex(result.error) << '\n';
        }
        return 0; // Per-row failures are explicit data, not silently omitted.
    } catch (const std::exception& exception) {
        std::cerr << exception.what() << '\n';
        return 2;
    }
}
