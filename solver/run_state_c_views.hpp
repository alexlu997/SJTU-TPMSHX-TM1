#pragma once

#include "tpmshx/run_state.hpp"
#include "tpmshx/run_state_c_api.h"
#include <limits>
#include <stdexcept>

namespace tpmshx::run_state_c_views {
struct SnapshotOwner {
    RunStateRecord record;
    std::vector<tpmshx_run_state_field_v1> fields;
    explicit SnapshotOwner(RunStateRecord value):record(std::move(value)) {
        fields.reserve(record.size());
        for(const auto& field:record)std::visit([&](const auto& values) {
            fields.push_back({field.name.c_str(),static_cast<uint32_t>(field.value.index()),values.data(),values.size()});
        },field.value);
    }
};
inline RunStateRecord state_record(const tpmshx_run_state_field_v1* fields,std::size_t count) {
    if(!fields || !count)throw std::invalid_argument("native state fields are missing");
    RunStateRecord record;record.reserve(count);
    for(std::size_t i=0;i<count;++i) {
        const auto& field=fields[i];
        if(!field.name || (field.count && !field.data))throw std::invalid_argument("null native state field");
        RunStateField value;value.name=field.name;
        auto copy=[&](auto element) {
            using T=decltype(element);
            if(field.count>std::numeric_limits<std::size_t>::max()/sizeof(T))throw std::invalid_argument("native state field is too large");
            const auto* data=static_cast<const T*>(field.data);
            if(field.count)value.value=std::vector<T>(data,data+field.count);else value.value=std::vector<T>{};
        };
        switch(field.type) {
            case TPMSHX_RUN_STATE_F64:copy(double{});break;
            case TPMSHX_RUN_STATE_U64:copy(std::uint64_t{});break;
            case TPMSHX_RUN_STATE_I64:copy(std::int64_t{});break;
            case TPMSHX_RUN_STATE_U8:copy(static_cast<unsigned char>(0));break;
            case TPMSHX_RUN_STATE_UTF8:value.value=field.count?std::string(static_cast<const char*>(field.data),field.count):std::string{};break;
            default:throw std::invalid_argument("unknown native state field type");
        }
        record.push_back(std::move(value));
    }
    return record;
}
} // namespace tpmshx::run_state_c_views
