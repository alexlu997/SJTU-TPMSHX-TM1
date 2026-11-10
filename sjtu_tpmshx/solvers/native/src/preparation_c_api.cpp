#include "tpmshx/preparation_c_api.h"

extern "C" uint32_t TPMSHX_PREPARATION_CALL tpmshx_preparation_abi_version_v1(void) {
    return TPMSHX_PREPARATION_ABI_VERSION;
}
