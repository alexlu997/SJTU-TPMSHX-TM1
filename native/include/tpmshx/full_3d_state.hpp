#pragma once

#include "tpmshx/full_3d.hpp"
#include <cstdint>
#include <variant>

namespace tpmshx {

// Every field owns its values. Strings contain UTF-8; numeric arrays are flat.
using RunStateValue=std::variant<std::vector<double>,std::vector<std::uint64_t>,
    std::vector<std::int64_t>,std::vector<unsigned char>,std::string>;
struct RunStateField {std::string name;RunStateValue value;};
using RunStateRecord=std::vector<RunStateField>;

// Format and build identity precede the exact prepared input and controls.
// Host paths and callback addresses are not numerical identity fields.
RunStateRecord export_full_3d_state(const Full3DInput&,const Full3DControl&,const Full3DRunState&);
Full3DRunState import_full_3d_state(const Full3DInput&,const Full3DControl&,const RunStateRecord&);

} // namespace tpmshx
