# A new native build must not accept a checkpoint from a previous binary.
string(RANDOM LENGTH 32 ALPHABET 0123456789abcdef state_build_id)
file(WRITE "${TPMSHX_STATE_HEADER}"
    "#define TPMSHX_STATE_BUILD_ID \"${state_build_id}\"\n"
    "#define TPMSHX_STATE_PLATFORM \"${TPMSHX_STATE_PLATFORM}\"\n")
