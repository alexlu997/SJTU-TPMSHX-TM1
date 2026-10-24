#pragma once

#include "tpmshx/temperature_driver.hpp"

namespace tpmshx {

// Retain the G4 rows for two-sided true-h CC warm-up.
// Each advance completes one original chunk without an h(P,T) ledger.
class LegacyTemperatureRun {
public:
    LegacyTemperatureRun(TemperatureScheme,const GridView&,
        const TemperatureFluidView&,const TemperatureFluidView&,
        ArrayView<const double>,TemperatureStateView,const TemperatureControl&,
        bool red_black=false);
    LegacyTemperatureRun(TemperatureScheme,const GridView&,
        const TemperatureFluidView&,const TemperatureFluidView&,
        ArrayView<const double>,TemperatureStateView,const TemperatureControl&,
        const TemperatureRunState&,bool red_black=false);
    ~LegacyTemperatureRun();
    LegacyTemperatureRun(const LegacyTemperatureRun&)=delete;
    LegacyTemperatureRun& operator=(const LegacyTemperatureRun&)=delete;
    TemperaturePhase advance();
    TemperaturePhase phase() const;
    TemperatureRunState snapshot() const;
    TemperatureResult take_result();
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace tpmshx
