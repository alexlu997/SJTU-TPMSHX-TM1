#include "tpmshx/result_c_api.h"
#include "result_c_boundary.hpp"

#include <limits>

extern "C" {

std::uint32_t tpmshx_result_abi_version_v1(void) {return TPMSHX_RESULT_ABI_VERSION;}

int tpmshx_result_platform_info_v1(tpmshx_result_platform_v1* output,char* error,std::size_t capacity) {
    tpmshx::result::Diagnostics diagnostics{};
    return tpmshx::result::c_api::boundary(&diagnostics,error,capacity,
        [&](auto& buffers){buffers.output(output);},
        [&](auto&){*output={static_cast<std::uint32_t>(sizeof(long double)),
            static_cast<std::uint32_t>(std::numeric_limits<long double>::digits),
            static_cast<std::uint32_t>(std::numeric_limits<long double>::max_exponent),0};});
}

}
