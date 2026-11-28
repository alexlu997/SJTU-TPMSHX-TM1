#pragma once

#include "tpmshx/preparation_case.hpp"
#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <string_view>

namespace tpmshx::preparation {
inline bool blank_text(std::string_view text) {
    // Python strips these Unicode spaces and the listed ASCII controls.
    constexpr std::array<std::string_view,19> spaces{{
        "\xC2\x85","\xC2\xA0","\xE1\x9A\x80","\xE2\x80\x80","\xE2\x80\x81",
        "\xE2\x80\x82","\xE2\x80\x83","\xE2\x80\x84","\xE2\x80\x85","\xE2\x80\x86",
        "\xE2\x80\x87","\xE2\x80\x88","\xE2\x80\x89","\xE2\x80\x8A","\xE2\x80\xA8",
        "\xE2\x80\xA9","\xE2\x80\xAF","\xE2\x81\x9F","\xE3\x80\x80"}};
    while (!text.empty()) {
        const auto first=static_cast<unsigned char>(text.front());
        if ((first>=9 && first<=13) || (first>=28 && first<=32)) {text.remove_prefix(1);continue;}
        const auto found=std::find_if(spaces.begin(),spaces.end(),[&](auto space) {
            return text.substr(0,space.size())==space;
        });
        if (found==spaces.end()) return false;
        text.remove_prefix(found->size());
    }
    return true;
}
inline void validate_nu(const Sco2NuSelection& selected) {
    if (selected.mode>1) throw std::invalid_argument("unsupported sCO2 Nu mode");
    for (std::size_t i=0;i<2;++i) {
        const auto value=selected.alpha[i];
        if (!value && !selected.mode) continue;
        if (!value || !std::isfinite(*value) || *value<=0.)
            throw std::invalid_argument(std::string("sCO2 Nu alpha_")+(i?'G':'D')+" must be finite and positive");
    }
    const std::array<std::pair<const char*,const std::string*>,3> texts{{
        {"parameter_version",&selected.parameter_version},{"source",&selected.source},{"applicability",&selected.applicability}}};
    for (const auto& text:texts) if (selected.mode && blank_text(*text.second))
        throw std::invalid_argument(std::string("sCO2 Nu requires ")+text.first);
}
}  // namespace tpmshx::preparation
