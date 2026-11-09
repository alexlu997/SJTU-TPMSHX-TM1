#pragma once

#include <cstdint>
#include <string>
#include <variant>
#include <vector>

namespace tpmshx {

// Every field owns its values. Strings contain UTF-8; numeric arrays are flat.
using RunStateValue=std::variant<std::vector<double>,std::vector<std::uint64_t>,
    std::vector<std::int64_t>,std::vector<unsigned char>,std::string>;
struct RunStateField {std::string name;RunStateValue value;};
using RunStateRecord=std::vector<RunStateField>;

} // namespace tpmshx
