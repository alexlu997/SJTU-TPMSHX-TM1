#pragma once

#include "tpmshx/result_core.hpp"

#include <array>
#include <algorithm>
#include <cstdio>
#include <limits>
#include <new>
#include <vector>

namespace tpmshx::result::c_api {

class Buffers {
public:
    Buffers(Diagnostics* diagnostics,char* error,std::size_t capacity) noexcept {
        error_index_=register_span(error,capacity,1,1,true);
        diagnostic_index_=register_span(diagnostics,1,sizeof(Diagnostics),alignof(Diagnostics),true);
        if (!capacity) fail("result calls require nonempty error storage");
    }
    template<class T> void input(const T* pointer,std::size_t count=1) noexcept {
        register_span(pointer,count,sizeof(T),alignof(T),false);
    }
    void bytes(const void* pointer,std::size_t count) noexcept {register_span(pointer,count,1,1,false);}
    template<class T> void output(T* pointer,std::size_t count=1) noexcept {
        register_span(pointer,count,sizeof(T),alignof(T),true);
    }
    void output_bytes(void* pointer,std::size_t count) noexcept {register_span(pointer,count,1,1,true);}
    void array(const RawArray& value) noexcept {
        array_storage(value,false);
    }
    void output_array(const RawArray* value) noexcept {
        const auto index=register_span(value,1,sizeof(RawArray),alignof(RawArray),false);
        if (readable(index)) array_storage(*value,true);
        else unknown_=true;
    }
    void array_storage(const RawArray& value,bool writable) noexcept {
        register_span(value.data,value.bytes,1,1,writable);
        input(value.shape,value.rank);
        input(value.strides,value.rank);
        if (array_count_==arrays_.size()) {unknown_=true;fail("too many result array arguments");return;}
        array_writable_[array_count_]=writable;
        arrays_[array_count_++]=value;
    }
    void arrays(const RawArray* values,std::size_t count) noexcept {
        const auto index=register_span(values,count,sizeof(RawArray),alignof(RawArray),false);
        if (count>arrays_.size()-array_count_) {unknown_=true;fail("too many result array arguments");return;}
        if (!readable(index)) {unknown_=true;return;}
        for (std::size_t i=0;i<count;++i) array(values[i]);
    }
    void validate() const {
        if (failure_) throw std::invalid_argument(failure_);
        for (std::size_t i=0;i<span_count_;++i) for (std::size_t j=0;j<i;++j)
            if ((spans_[i].writable || spans_[j].writable) && overlap(spans_[i],spans_[j]))
                throw std::invalid_argument("result writable storage overlaps another buffer");
        for (std::size_t i=0;i<array_count_;++i) {
            const Array checked(arrays_[i]);
            if (array_writable_[i] && checked.size()) validate_output_elements(arrays_[i]);
        }
    }
    bool error_safe() const noexcept {return report_safe(error_index_);}
    bool diagnostics_safe() const noexcept {return report_safe(diagnostic_index_);}
private:
    struct Span {
        std::uintptr_t first{},last{};
        bool writable{},known{true},empty{true},aligned{true};
    };
    static constexpr auto absent=std::numeric_limits<std::size_t>::max();
    std::array<Span,128> spans_{};
    std::array<RawArray,32> arrays_{};
    std::array<bool,32> array_writable_{};
    std::size_t span_count_{},array_count_{},error_index_{absent},diagnostic_index_{absent};
    const char* failure_{};
    bool unknown_{};
    void fail(const char* text) noexcept {if (!failure_) failure_=text;}
    static void validate_output_elements(const RawArray& value) {
        std::vector<std::pair<std::size_t,std::size_t>> axes;
        for (std::size_t i=0;i<value.rank;++i) if (value.shape[i]>1) {
            const auto stride=value.strides[i];
            const auto distance=stride<0?static_cast<std::size_t>(-(stride+1))+1:static_cast<std::size_t>(stride);
            axes.emplace_back(distance,value.shape[i]);
        }
        std::sort(axes.begin(),axes.end());
        auto covered=item_size(value.dtype);
        for (const auto& axis:axes) {
            if (axis.first<covered) throw std::invalid_argument("result output elements must have separate storage");
            covered+=axis.first*(axis.second-1);
        }
    }
    std::size_t register_span(const void* pointer,std::size_t count,std::size_t width,
                             std::size_t alignment,bool writable) noexcept {
        if (span_count_==spans_.size()) {unknown_=true;fail("too many result buffers");return absent;}
        const auto index=span_count_++;
        auto& span=spans_[index];span.writable=writable;
        if (!count) return index;
        span.empty=false;span.first=reinterpret_cast<std::uintptr_t>(pointer);
        if (count>std::numeric_limits<std::size_t>::max()/width) {
            span.known=false;fail("result buffer extent overflows size_t");return index;
        }
        const auto length=count*width;
        if (length-1>std::numeric_limits<std::uintptr_t>::max()-span.first) {
            span.known=false;fail("result buffer address range overflows");return index;
        }
        span.last=span.first+length-1;
        span.aligned=pointer && span.first%alignment==0;
        if (!span.aligned) fail("result buffer requires valid aligned storage");
        return index;
    }
    bool readable(std::size_t index) const noexcept {
        return index!=absent && spans_[index].known && spans_[index].aligned;
    }
    static bool overlap(const Span& first,const Span& second) noexcept {
        return !first.empty && !second.empty && first.first<=second.last && second.first<=first.last;
    }
    bool report_safe(std::size_t index) const noexcept {
        if (index==absent || unknown_) return false;
        const auto& selected=spans_[index];
        if (selected.empty || !selected.known || !selected.aligned) return false;
        for (std::size_t i=0;i<span_count_;++i)
            if (!spans_[i].known || (i!=index && overlap(selected,spans_[i]))) return false;
        return true;
    }
};

template<class Register,class Execute> int boundary(Diagnostics* diagnostics,char* error,std::size_t capacity,
                                                   Register register_buffers,Execute execute) noexcept {
    FloatingEnvironment environment;
    Buffers buffers(diagnostics,error,capacity);
    Diagnostics local{};
    int status=TPMSHX_RESULT_OK;
    const char* message="";
    std::string saved_message;
    try {
        register_buffers(buffers);
        buffers.validate();
        execute(local);
    } catch (const NumericError& failure) {
        local.python_cause=failure.cause;local.error_number=failure.error_number;
        status=TPMSHX_RESULT_NUMERIC;
        try {saved_message=failure.what();message=saved_message.c_str();} catch (...) {message="native result numerical failure";}
    } catch (const std::invalid_argument& failure) {
        status=TPMSHX_RESULT_INVALID;
        try {saved_message=failure.what();message=saved_message.c_str();} catch (...) {message="invalid native result input";}
    } catch (const std::bad_alloc&) {
        status=TPMSHX_RESULT_ALLOCATION;message="native result allocation failed";
    } catch (const std::exception& failure) {
        status=TPMSHX_RESULT_RUNTIME;
        try {saved_message=failure.what();message=saved_message.c_str();} catch (...) {message="native result runtime failure";}
    } catch (...) {status=TPMSHX_RESULT_RUNTIME;message="unknown native result failure";}
    if (buffers.diagnostics_safe()) *diagnostics=local;
    if (buffers.error_safe()) std::snprintf(error,capacity,"%s",message);
    return status;
}

}  // namespace tpmshx::result::c_api
