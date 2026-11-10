#include "tpmshx/result_core.hpp"
#include "tpmshx/scalar_precision.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <limits>

namespace tpmshx::result {
static_assert(sizeof(long double)<=16,"result scalar payload requires long double at most 16 bytes");
namespace {

bool native_little() {
    const std::uint16_t one=1;
    unsigned char first;
    std::memcpy(&first,&one,1);
    return first==1;
}
void check_order(std::uint32_t order) {
    if (order>TPMSHX_RESULT_BIG_ENDIAN) throw std::invalid_argument("invalid result byte order");
}
void check_origin(std::uint32_t origin) {
    if (origin>TPMSHX_RESULT_PYTHON_COMPLEX) throw std::invalid_argument("invalid result scalar origin");
}
template<class T> T load(const void* source,std::uint32_t order) {
    std::array<unsigned char,sizeof(T)> bytes{};
    std::memcpy(bytes.data(),source,sizeof(T));
    if (sizeof(T)>1 && order!=TPMSHX_RESULT_NATIVE_ENDIAN
        && ((order==TPMSHX_RESULT_LITTLE_ENDIAN)!=native_little())) std::reverse(bytes.begin(),bytes.end());
    T value;
    std::memcpy(&value,bytes.data(),sizeof(T));
    return value;
}
template<class T> void store(void* destination,T value) {std::memcpy(destination,&value,sizeof(T));}
float half_value(std::uint16_t value) {
    const auto sign=static_cast<std::uint32_t>(value&0x8000u)<<16;
    auto exponent=static_cast<std::uint32_t>((value>>10)&31u);
    auto fraction=static_cast<std::uint32_t>(value&1023u);
    std::uint32_t bits;
    if (exponent==31) bits=sign|0x7f800000u|(fraction<<13);
    else if (!exponent && !fraction) bits=sign;
    else if (!exponent) {
        int shift=0;
        while (!(fraction&1024u)) {fraction<<=1;++shift;}
        bits=sign|(static_cast<std::uint32_t>(113-shift)<<23)|((fraction&1023u)<<13);
    } else bits=sign|((exponent+112u)<<23)|(fraction<<13);
    float output;
    std::memcpy(&output,&bits,sizeof(output));
    return output;
}
std::uint16_t half_bits(long double input) {
    const double value=geometry::detail::round_scalar(static_cast<double>(input),16);
    const auto sign=std::signbit(value)?0x8000u:0u;
    if (std::isnan(value)) return static_cast<std::uint16_t>(sign|0x7e00u);
    if (std::isinf(value)) return static_cast<std::uint16_t>(sign|0x7c00u);
    const double magnitude=std::abs(value);
    if (!magnitude) return static_cast<std::uint16_t>(sign);
    if (magnitude<0x1p-14) return static_cast<std::uint16_t>(sign|static_cast<unsigned>(std::ldexp(magnitude,24)));
    int exponent;
    std::frexp(magnitude,&exponent);
    const auto encoded=static_cast<unsigned>(exponent+14);
    const auto fraction=static_cast<unsigned>(std::ldexp(magnitude,11-exponent))-1024u;
    return static_cast<std::uint16_t>(sign|(encoded<<10)|fraction);
}
std::size_t product(std::size_t a,std::size_t b) {
    if (b && a>std::numeric_limits<std::size_t>::max()/b)
        throw std::invalid_argument("result array extent overflows size_t");
    return a*b;
}
std::size_t magnitude(std::ptrdiff_t value) {
    return value<0?static_cast<std::size_t>(-(value+1))+1:static_cast<std::size_t>(value);
}
std::size_t add(std::size_t first,std::size_t second) {
    if (second>std::numeric_limits<std::size_t>::max()-first)
        throw std::invalid_argument("result array offset overflows size_t");
    return first+second;
}
void metadata(const void* pointer,std::size_t count,std::size_t width,std::size_t alignment) {
    const auto bytes=product(count,width),address=reinterpret_cast<std::uintptr_t>(pointer);
    if (bytes && (!pointer || address%alignment || bytes-1>std::numeric_limits<std::uintptr_t>::max()-address))
        throw std::invalid_argument("invalid result array metadata storage");
}
}  // namespace

std::size_t item_size(std::uint32_t dtype) {
    switch (dtype) {
    case TPMSHX_RESULT_BOOL: case TPMSHX_RESULT_I8: case TPMSHX_RESULT_U8: return 1;
    case TPMSHX_RESULT_I16: case TPMSHX_RESULT_U16: case TPMSHX_RESULT_F16: return 2;
    case TPMSHX_RESULT_I32: case TPMSHX_RESULT_U32: case TPMSHX_RESULT_F32: return 4;
    case TPMSHX_RESULT_I64: case TPMSHX_RESULT_U64: case TPMSHX_RESULT_F64: case TPMSHX_RESULT_C64: return 8;
    case TPMSHX_RESULT_C128: return 16;
    case TPMSHX_RESULT_LONG_DOUBLE: return sizeof(long double);
    case TPMSHX_RESULT_COMPLEX_LONG_DOUBLE: return 2*sizeof(long double);
    default: throw std::invalid_argument("invalid result dtype");
    }
}
bool integer_type(std::uint32_t dtype) {return dtype>=TPMSHX_RESULT_BOOL && dtype<=TPMSHX_RESULT_U64;}
bool signed_type(std::uint32_t dtype) {
    return dtype==TPMSHX_RESULT_I8 || dtype==TPMSHX_RESULT_I16 || dtype==TPMSHX_RESULT_I32 || dtype==TPMSHX_RESULT_I64;
}
bool complex_type(std::uint32_t dtype) {return dtype>=TPMSHX_RESULT_C64 && dtype<=TPMSHX_RESULT_COMPLEX_LONG_DOUBLE;}
Number read_number(const void* data,std::uint32_t dtype,std::uint32_t order,std::uint32_t origin) {
    item_size(dtype);check_order(order);check_origin(origin);
    if (!data) throw std::invalid_argument("result value storage is NULL");
    Number out;out.dtype=dtype;out.origin=origin;
    const auto* bytes=static_cast<const unsigned char*>(data);
    switch (dtype) {
    case TPMSHX_RESULT_BOOL: out.unsigned_value=load<std::uint8_t>(data,order)!=0;break;
    case TPMSHX_RESULT_I8: out.signed_value=load<std::int8_t>(data,order);break;
    case TPMSHX_RESULT_U8: out.unsigned_value=load<std::uint8_t>(data,order);break;
    case TPMSHX_RESULT_I16: out.signed_value=load<std::int16_t>(data,order);break;
    case TPMSHX_RESULT_U16: out.unsigned_value=load<std::uint16_t>(data,order);break;
    case TPMSHX_RESULT_I32: out.signed_value=load<std::int32_t>(data,order);break;
    case TPMSHX_RESULT_U32: out.unsigned_value=load<std::uint32_t>(data,order);break;
    case TPMSHX_RESULT_I64: out.signed_value=load<std::int64_t>(data,order);break;
    case TPMSHX_RESULT_U64: out.unsigned_value=load<std::uint64_t>(data,order);break;
    case TPMSHX_RESULT_F16: out.real=half_value(load<std::uint16_t>(data,order));break;
    case TPMSHX_RESULT_F32: out.real=load<float>(data,order);break;
    case TPMSHX_RESULT_F64: out.real=load<double>(data,order);break;
    case TPMSHX_RESULT_LONG_DOUBLE: out.real=load<long double>(data,order);break;
    case TPMSHX_RESULT_C64: out.real=load<float>(data,order);out.imaginary=load<float>(bytes+4,order);break;
    case TPMSHX_RESULT_C128: out.real=load<double>(data,order);out.imaginary=load<double>(bytes+8,order);break;
    case TPMSHX_RESULT_COMPLEX_LONG_DOUBLE:
        out.real=load<long double>(data,order);out.imaginary=load<long double>(bytes+sizeof(long double),order);break;
    }
    return out;
}
Number read_scalar(const RawScalar& value) {
    if (value.reserved) throw std::invalid_argument("result scalar reserved field must be zero");
    return read_number(value.data,value.dtype,value.byte_order,value.origin);
}
void store_number(void* destination,const Number& value) {
    if (!destination) throw std::invalid_argument("result output storage is NULL");
    auto* bytes=static_cast<unsigned char*>(destination);
    switch (value.dtype) {
    case TPMSHX_RESULT_BOOL: store(bytes,static_cast<std::uint8_t>(value.unsigned_value!=0));break;
    case TPMSHX_RESULT_I8: store(bytes,static_cast<std::int8_t>(value.signed_value));break;
    case TPMSHX_RESULT_U8: store(bytes,static_cast<std::uint8_t>(value.unsigned_value));break;
    case TPMSHX_RESULT_I16: store(bytes,static_cast<std::int16_t>(value.signed_value));break;
    case TPMSHX_RESULT_U16: store(bytes,static_cast<std::uint16_t>(value.unsigned_value));break;
    case TPMSHX_RESULT_I32: store(bytes,static_cast<std::int32_t>(value.signed_value));break;
    case TPMSHX_RESULT_U32: store(bytes,static_cast<std::uint32_t>(value.unsigned_value));break;
    case TPMSHX_RESULT_I64: store(bytes,value.signed_value);break;
    case TPMSHX_RESULT_U64: store(bytes,value.unsigned_value);break;
    case TPMSHX_RESULT_F16: store(bytes,half_bits(value.real));break;
    case TPMSHX_RESULT_F32: store(bytes,static_cast<float>(value.real));break;
    case TPMSHX_RESULT_F64: store(bytes,static_cast<double>(value.real));break;
    case TPMSHX_RESULT_LONG_DOUBLE: store(bytes,value.real);break;
    case TPMSHX_RESULT_C64:
        store(bytes,static_cast<float>(value.real));store(bytes+4,static_cast<float>(value.imaginary));break;
    case TPMSHX_RESULT_C128:
        store(bytes,static_cast<double>(value.real));store(bytes+8,static_cast<double>(value.imaginary));break;
    case TPMSHX_RESULT_COMPLEX_LONG_DOUBLE:
        store(bytes,value.real);store(bytes+sizeof(long double),value.imaginary);break;
    default: throw std::invalid_argument("invalid result output dtype");
    }
}
RawScalar pack_scalar(const Number& value) {
    check_origin(value.origin);
    RawScalar out{};out.dtype=value.dtype;out.origin=value.origin;
    store_number(out.data,value);
    return out;
}
void copy_number(const void* source,std::uint32_t source_order,void* destination,
                 std::uint32_t destination_order,std::uint32_t dtype) {
    check_order(source_order);check_order(destination_order);
    const auto width=item_size(dtype);
    if (!source || !destination) throw std::invalid_argument("result byte copy requires storage");
    const bool source_little=source_order==TPMSHX_RESULT_NATIVE_ENDIAN?native_little():source_order==TPMSHX_RESULT_LITTLE_ENDIAN;
    const bool destination_little=destination_order==TPMSHX_RESULT_NATIVE_ENDIAN?native_little():destination_order==TPMSHX_RESULT_LITTLE_ENDIAN;
    std::array<unsigned char,32> bytes{};
    std::memcpy(bytes.data(),source,width);
    if (source_little!=destination_little) {
        const auto component=complex_type(dtype)?width/2:width;
        std::reverse(bytes.begin(),bytes.begin()+static_cast<std::ptrdiff_t>(component));
        if (complex_type(dtype)) std::reverse(bytes.begin()+static_cast<std::ptrdiff_t>(component),bytes.begin()+static_cast<std::ptrdiff_t>(width));
    }
    std::memcpy(destination,bytes.data(),width);
}
long double real_value(const Number& value) {
    if (signed_type(value.dtype)) return static_cast<long double>(value.signed_value);
    if (integer_type(value.dtype)) return static_cast<long double>(value.unsigned_value);
    return value.real;
}
bool finite(const Number& value) {
    return integer_type(value.dtype) || (std::isfinite(value.real) && (!complex_type(value.dtype) || std::isfinite(value.imaginary)));
}
bool zero(const Number& value) {
    if (signed_type(value.dtype)) return value.signed_value==0;
    if (integer_type(value.dtype)) return value.unsigned_value==0;
    return value.real==0. && (!complex_type(value.dtype) || value.imaginary==0.);
}
long double round_real(long double value,std::uint32_t dtype) {
    switch (dtype) {
    case TPMSHX_RESULT_F16: return geometry::detail::round_scalar(static_cast<double>(value),16);
    case TPMSHX_RESULT_F32: case TPMSHX_RESULT_C64: return static_cast<float>(value);
    case TPMSHX_RESULT_F64: case TPMSHX_RESULT_C128: return static_cast<double>(value);
    case TPMSHX_RESULT_LONG_DOUBLE: case TPMSHX_RESULT_COMPLEX_LONG_DOUBLE: return value;
    default: throw std::invalid_argument("rounding requires a floating result dtype");
    }
}
Number floating(long double value,std::uint32_t dtype,std::uint32_t origin) {
    Number out;out.dtype=dtype;out.origin=origin;out.real=round_real(value,dtype);return out;
}
Number complex_number(long double real,long double imaginary,std::uint32_t dtype,std::uint32_t origin) {
    if (!complex_type(dtype)) throw std::invalid_argument("complex result requires a complex dtype");
    Number out=floating(real,dtype,origin);out.imaginary=round_real(imaginary,dtype);return out;
}
Number signed_bits(std::uint64_t value,std::uint32_t dtype,std::uint32_t origin) {
    if (!signed_type(dtype)) throw std::invalid_argument("signed result requires an integer dtype");
    Number out;out.dtype=dtype;out.origin=origin;
    if (item_size(dtype)<8) {
        const auto bits=static_cast<unsigned>(item_size(dtype)*8);
        value&=(std::uint64_t{1}<<bits)-1;
        if (value&(std::uint64_t{1}<<(bits-1))) value|=~((std::uint64_t{1}<<bits)-1);
    }
    std::memcpy(&out.signed_value,&value,sizeof(value));return out;
}
Number unsigned_bits(std::uint64_t value,std::uint32_t dtype,std::uint32_t origin) {
    if (!integer_type(dtype) || signed_type(dtype)) throw std::invalid_argument("unsigned result requires an integer dtype");
    Number out;out.dtype=dtype;out.origin=origin;
    const auto bits=static_cast<unsigned>(item_size(dtype)*8);
    out.unsigned_value=dtype==TPMSHX_RESULT_BOOL?value!=0:bits==64?value:value&((std::uint64_t{1}<<bits)-1);
    return out;
}
void append_event(Diagnostics& diagnostics,std::uint32_t flags,std::uint32_t operation,bool scalar) {
    if (!flags) return;
    if (flags>15 || operation<TPMSHX_RESULT_ADD || operation>TPMSHX_RESULT_SQUARE)
        throw std::logic_error("invalid internal result FP event");
    if (diagnostics.event_count>=TPMSHX_RESULT_FP_EVENT_COUNT)
        throw std::logic_error("result FP event extent exceeded");
    diagnostics.events[diagnostics.event_count++]={flags,operation,scalar?1u:0u,0};
}

Array::Array(const RawArray& input):raw_(input) {
    const auto width=item_size(raw_.dtype);
    check_order(raw_.byte_order);check_origin(raw_.origin);
    if (raw_.reserved) throw std::invalid_argument("result array reserved field must be zero");
    metadata(raw_.shape,raw_.rank,sizeof(std::size_t),alignof(std::size_t));
    metadata(raw_.strides,raw_.rank,sizeof(std::ptrdiff_t),alignof(std::ptrdiff_t));
    count_=1;
    for (std::size_t i=0;i<raw_.rank;++i) if (!raw_.shape[i]) count_=0;
    if (count_) for (std::size_t i=0;i<raw_.rank;++i) count_=product(count_,raw_.shape[i]);
    if (!count_) {
        if (raw_.offset>raw_.bytes) throw std::invalid_argument("empty result array offset exceeds storage");
        return;
    }
    std::size_t lower=0,upper=0;
    for (std::size_t i=0;i<raw_.rank;++i) {
        const auto extent=product(raw_.shape[i]-1,magnitude(raw_.strides[i]));
        if (raw_.strides[i]<0) lower=add(lower,extent);else upper=add(upper,extent);
    }
    if (raw_.offset<lower || add(add(raw_.offset,upper),width)>raw_.bytes)
        throw std::invalid_argument("result array view exceeds borrowed storage");
    metadata(raw_.data,raw_.bytes,1,1);
}
const unsigned char* Array::address(std::size_t index) const {
    if (index>=count_) throw std::out_of_range("result array index exceeds shape");
    auto offset=raw_.offset;
    for (std::size_t i=raw_.rank;i>0;--i) {
        const auto coordinate=index%raw_.shape[i-1];index/=raw_.shape[i-1];
        const auto distance=coordinate*magnitude(raw_.strides[i-1]);
        if (raw_.strides[i-1]<0) offset-=distance;else offset+=distance;
    }
    return static_cast<const unsigned char*>(raw_.data)+offset;
}
Number Array::at(std::size_t index) const {return read_number(address(index),raw_.dtype,raw_.byte_order,raw_.origin);}

}  // namespace tpmshx::result
