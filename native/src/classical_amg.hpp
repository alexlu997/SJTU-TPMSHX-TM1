#pragma once

#include "tpmshx/pressure_candidate.hpp"

namespace tpmshx::classical_detail {

// Private implementation of the locked Python owner's numerical algorithm.
// A hierarchy belongs to exactly one PressureCandidate / SIMPLE stream.
struct KrylovResult {
    std::vector<double> x;
    int info=0;
    std::size_t iterations=0;
};

class ClassicalAmg {
public:
    explicit ClassicalAmg(const PressureSystem&);
    ~ClassicalAmg();
    ClassicalAmg(const ClassicalAmg&)=delete;
    ClassicalAmg& operator=(const ClassicalAmg&)=delete;
    KrylovResult solve(const PressureSystem&,const std::vector<double>& rhs,
                       double tolerance,std::size_t max_iterations);
    std::size_t bytes() const;
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace tpmshx::classical_detail
