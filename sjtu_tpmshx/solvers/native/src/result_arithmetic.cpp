#include "tpmshx/result_arithmetic.hpp"
#include "numpy_complex_divide.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <limits>
#include <numeric>

#if defined(__APPLE__)
extern "C" void tpmshx_result_complex_sqrt_f32(float real,float imaginary,float* result);
extern "C" void tpmshx_result_complex_sqrt_f64(double real,double imaginary,double* result);
extern "C" void tpmshx_result_complex_sqrt_long_double(long double real,long double imaginary,long double* result);
#endif

namespace tpmshx::result::arithmetic {
namespace {
constexpr auto B=TPMSHX_RESULT_BOOL, I8=TPMSHX_RESULT_I8, U8=TPMSHX_RESULT_U8;
constexpr auto I16=TPMSHX_RESULT_I16, U16=TPMSHX_RESULT_U16;
constexpr auto I32=TPMSHX_RESULT_I32, U32=TPMSHX_RESULT_U32;
constexpr auto I64=TPMSHX_RESULT_I64, U64=TPMSHX_RESULT_U64;
constexpr auto F16=TPMSHX_RESULT_F16, F32=TPMSHX_RESULT_F32, F64=TPMSHX_RESULT_F64;
constexpr auto LD=TPMSHX_RESULT_LONG_DOUBLE, C64=TPMSHX_RESULT_C64, C128=TPMSHX_RESULT_C128;
constexpr auto CLD=TPMSHX_RESULT_COMPLEX_LONG_DOUBLE;
constexpr auto PF=TPMSHX_RESULT_PYTHON_FLOAT, PI=TPMSHX_RESULT_PYTHON_INT;
constexpr auto PB=TPMSHX_RESULT_PYTHON_BOOL, PC=TPMSHX_RESULT_PYTHON_COMPLEX;
constexpr auto NS=TPMSHX_RESULT_NUMPY_SCALAR, NA=TPMSHX_RESULT_NUMPY_ARRAY;

bool strong(const Number& n) {return n.origin==NS || n.origin==NA;}
std::uint32_t component(std::uint32_t type) {return type==C64?F32:type==C128?F64:type==CLD?LD:type;}
std::uint32_t complex_dtype(std::uint32_t type) {return type==LD?CLD:type==F64?C128:C64;}
unsigned bits(std::uint32_t type) {return type==B?1u:static_cast<unsigned>(item_size(type)*8);}
std::uint64_t mask(std::uint32_t type) {return bits(type)==64?~std::uint64_t{}:(std::uint64_t{1}<<bits(type))-1;}
std::uint64_t raw_integer(const Number& n) {return signed_type(n.dtype)?static_cast<std::uint64_t>(n.signed_value):n.unsigned_value;}
std::uint32_t integer_dtype(unsigned width,bool sign) {
    if (width<=8) return sign?I8:U8;
    if (width<=16) return sign?I16:U16;
    if (width<=32) return sign?I32:U32;
    return sign?I64:U64;
}
std::uint32_t floating_rank(std::uint32_t type) {
    type=component(type);return type==LD?4:type==F64?3:type==F32?2:type==F16?1:0;
}
std::uint32_t float_rank_type(unsigned rank) {return rank>=4?LD:rank==3?F64:rank==2?F32:F16;}
std::uint32_t common_dtype(std::uint32_t a,std::uint32_t b) {
    if (a==b) return a;
    const bool complex=complex_type(a)||complex_type(b);
    auto fa=floating_rank(a),fb=floating_rank(b);
    if (fa || fb) {
        auto rank=std::max(fa,fb);
        const auto integer=fa?b:a;
        if (integer_type(integer) && integer!=B) {
            const auto width=bits(integer);
            if (width>=32) rank=std::max(rank,3u);
            else if (width>=16) rank=std::max(rank,2u);
        }
        auto out=float_rank_type(rank);
        return complex?complex_dtype(out):out;
    }
    if (a==B) return b;
    if (b==B) return a;
    const auto wa=bits(a),wb=bits(b);
    if (signed_type(a)==signed_type(b)) return integer_dtype(std::max(wa,wb),signed_type(a));
    const auto sw=signed_type(a)?wa:wb,uw=signed_type(a)?wb:wa;
    if (sw>uw) return integer_dtype(sw,true);
    return uw==64?F64:integer_dtype(uw*2,true);
}
std::uint32_t result_origin(const Number& a,const Number& b,std::uint32_t type) {
    if (a.origin==NA || b.origin==NA) return NA;
    if (strong(a)||strong(b)) return NS;
    return complex_type(type)?PC:integer_type(type)?PI:PF;
}
std::uint32_t promoted(const Number& a,const Number& b) {
    if (!strong(a) && !strong(b) && integer_type(a.dtype) && integer_type(b.dtype)) return I64;
    if (strong(a)!=strong(b)) {
        const auto& s=strong(a)?a:b;
        const auto& w=strong(a)?b:a;
        if (w.origin==PI || w.origin==PB) return s.dtype==B && w.origin==PI?I64:s.dtype;
        if (w.origin==PF) return integer_type(s.dtype)?F64:s.dtype;
        if (w.origin==PC) return complex_type(s.dtype)?s.dtype:complex_dtype(integer_type(s.dtype)?F64:component(s.dtype));
    }
    return common_dtype(a.dtype,b.dtype);
}
std::uint32_t fp_flags() {
    const int value=std::fetestexcept(FE_ALL_EXCEPT);
    return ((value&FE_DIVBYZERO)?1u:0u)|((value&FE_OVERFLOW)?2u:0u)
        |((value&FE_UNDERFLOW)?4u:0u)|((value&FE_INVALID)?8u:0u);
}
void event(Diagnostics& d,std::uint32_t operation,bool scalar,bool enabled=true,std::uint32_t extra=0) {
    const auto flags=fp_flags()|extra;
    if (enabled && flags) append_event(d,flags,operation,scalar);
}
Number converted(const Number& n,std::uint32_t type,std::uint32_t origin) {
    if (integer_type(type)) {
        if (n.origin==PI && strong(Number{type,origin})) {
            const auto value=n.signed_value;
            const auto width=bits(type);
            const auto maximum=width==64?std::numeric_limits<std::int64_t>::max():(std::int64_t{1}<<(width-1))-1;
            const auto minimum=width==64?std::numeric_limits<std::int64_t>::min():-(std::int64_t{1}<<(width-1));
            if ((signed_type(type) && (value<minimum || value>maximum))
                || (!signed_type(type) && (value<0 || (width<64 && static_cast<std::uint64_t>(value)>mask(type)))))
                throw NumericError(TPMSHX_RESULT_OVERFLOW,"Python integer "+std::to_string(value)+" out of bounds for "
                    +(signed_type(type)?"int":"uint")+std::to_string(width));
        }
        auto value=integer_type(n.dtype)?raw_integer(n):static_cast<std::uint64_t>(real_value(n));
        if (type==B) value=zero(n)?0u:1u;
        return signed_type(type)?signed_bits(value,type,origin):unsigned_bits(value,type,origin);
    }
    long double real=real_value(n);
    if (integer_type(n.dtype) && component(type)==F32)
        real=signed_type(n.dtype)?static_cast<float>(n.signed_value):static_cast<float>(n.unsigned_value);
    else if (integer_type(n.dtype) && component(type)==F64)
        real=signed_type(n.dtype)?static_cast<double>(n.signed_value):static_cast<double>(n.unsigned_value);
    if (complex_type(type)) return complex_number(real,n.imaginary,type,origin);
    return floating(real,type,origin);
}
std::uint32_t half_flags(long double exact,const Number& n) {
    if (n.dtype!=F16 || !std::isfinite(exact)) return 0;
    if (std::isinf(n.real)) return 2;
    return exact!=n.real && std::abs(n.real)<0x1p-14L?4u:0u;
}
template<class Real> Real real_binary(Real a,Real b,std::uint32_t op) {
    switch (op) {
    case TPMSHX_RESULT_ADD:return a+b;
    case TPMSHX_RESULT_SUBTRACT:return a-b;
    case TPMSHX_RESULT_MULTIPLY:return a*b;
    default:return a/b;
    }
}
template<class Real> std::complex<Real> complex_binary(std::complex<Real> a,std::complex<Real> b,std::uint32_t op) {
    switch (op) {
    case TPMSHX_RESULT_ADD:return a+b;
    case TPMSHX_RESULT_SUBTRACT:return a-b;
    case TPMSHX_RESULT_MULTIPLY:return a*b;
    default:return tpmshx::detail::numpy_complex_divide(a,b);
    }
}
#if defined(__APPLE__) && defined(__aarch64__)
template<class Real> Number neon_square(const Number& value) {
    const Real real=static_cast<Real>(value.real),imaginary=static_cast<Real>(value.imaginary);
    const Real imaginary_square=imaginary*imaginary,imaginary_real=imaginary*real;
    return complex_number(std::fma(real,real,-imaginary_square),
                          std::fma(real,imaginary,imaginary_real),value.dtype,value.origin);
}
#endif
Number array_square(const Number& value,Diagnostics& d) {
#if defined(__APPLE__) && defined(__aarch64__)
    // NumPy's NEON array loop rounds the imaginary product before fused addition.
    if (value.dtype==C64 || value.dtype==C128) {
        std::feclearexcept(FE_ALL_EXCEPT);
        const auto out=value.dtype==C64?neon_square<float>(value):neon_square<double>(value);
        event(d,TPMSHX_RESULT_SQUARE,false,true);return out;
    }
#endif
    return square(value,d);
}
bool scalar_integer_overflow(const Number& first,const Number& second,std::uint32_t op) {
    if (first.dtype==B) return false;
    if (!signed_type(first.dtype)) {
        const auto x=raw_integer(first),y=raw_integer(second),maximum=mask(first.dtype);
        return op==TPMSHX_RESULT_ADD?x>maximum-y:op==TPMSHX_RESULT_SUBTRACT?x<y:y && x>maximum/y;
    }
    const auto width=bits(first.dtype);
    const auto maximum=width==64?std::numeric_limits<std::int64_t>::max():(std::int64_t{1}<<(width-1))-1;
    const auto minimum=width==64?std::numeric_limits<std::int64_t>::min():-(std::int64_t{1}<<(width-1));
    const auto x=first.signed_value,y=second.signed_value;
    if (op==TPMSHX_RESULT_ADD) return y>0?x>maximum-y:y<0 && x<minimum-y;
    if (op==TPMSHX_RESULT_SUBTRACT) return y>0?x<minimum+y:y<0 && x>maximum+y;
    const auto magnitude=[](std::int64_t value) {const auto raw=static_cast<std::uint64_t>(value);return value<0?std::uint64_t{}-raw:raw;};
    const auto mx=magnitude(x),my=magnitude(y);
    const auto limit=(x<0)!=(y<0)?std::uint64_t{1}<<(width-1):static_cast<std::uint64_t>(maximum);
    return my && mx>limit/my;
}
Number binary(const Number& left,const Number& right,Diagnostics& d,std::uint32_t op) {
    auto type=promoted(left,right);
    const bool enabled=strong(left)||strong(right);
    auto origin=result_origin(left,right,type);
    if (op==TPMSHX_RESULT_DIVIDE && integer_type(type)) {type=F64;origin=result_origin(left,right,type);}
    if (op==TPMSHX_RESULT_SUBTRACT && type==B)
        throw NumericError(TPMSHX_RESULT_TYPE_ERROR,"numpy boolean subtract, the `-` operator, is not supported, use the bitwise_xor, the `^` operator, or the logical_xor function instead.");
    std::feclearexcept(FE_ALL_EXCEPT);
    const auto a=converted(left,type,origin),b=converted(right,type,origin);
    event(d,TPMSHX_RESULT_CAST,false,enabled,half_flags(real_value(left),a)|half_flags(real_value(right),b));
    std::feclearexcept(FE_ALL_EXCEPT);
    if (integer_type(type)) {
        const auto x=raw_integer(a),y=raw_integer(b);
        const auto value=op==TPMSHX_RESULT_ADD?x+y:op==TPMSHX_RESULT_SUBTRACT?x-y:x*y;
        Number out=type==B?unsigned_bits(op==TPMSHX_RESULT_ADD?(x||y):(x&&y),B,origin)
            :signed_type(type)?signed_bits(value,type,origin):unsigned_bits(value,type,origin);
        if (origin==NS && scalar_integer_overflow(a,b,op)) append_event(d,2u,op,true);
        return out;
    }
    if (!enabled && op==TPMSHX_RESULT_DIVIDE && zero(b))
        throw NumericError(TPMSHX_RESULT_ZERO_DIVISION,complex_type(type)?"complex division by zero":
            integer_type(left.dtype)&&integer_type(right.dtype)?"division by zero":"float division by zero");
    Number out;
    long double exact=0;
    if (complex_type(type)) {
        if (type==C64) {
            const auto value=complex_binary(std::complex<float>{static_cast<float>(a.real),static_cast<float>(a.imaginary)},
                std::complex<float>{static_cast<float>(b.real),static_cast<float>(b.imaginary)},op);
            out=complex_number(value.real(),value.imag(),type,origin);
        } else if (type==C128) {
            const auto value=complex_binary(std::complex<double>{static_cast<double>(a.real),static_cast<double>(a.imaginary)},
                std::complex<double>{static_cast<double>(b.real),static_cast<double>(b.imaginary)},op);
            out=complex_number(value.real(),value.imag(),type,origin);
        } else {
            const auto value=complex_binary(std::complex<long double>{a.real,a.imaginary},std::complex<long double>{b.real,b.imaginary},op);
            out=complex_number(value.real(),value.imag(),type,origin);
        }
    } else {
        if (type==F16 || type==F32) exact=real_binary(static_cast<float>(a.real),static_cast<float>(b.real),op);
        else if (type==F64) exact=real_binary(static_cast<double>(a.real),static_cast<double>(b.real),op);
        else exact=real_binary(a.real,b.real,op);
        out=floating(exact,type,origin);
    }
    event(d,op,origin!=NA,enabled,half_flags(exact,out));
    return out;
}
std::vector<std::size_t> shape_of(const Array& a) {if (!a.raw().rank) return {};return {a.raw().shape,a.raw().shape+a.raw().rank};}
std::vector<std::size_t> fast_axes(const Array& a) {
    std::vector<std::size_t> axes(a.raw().rank);
    std::iota(axes.rbegin(),axes.rend(),0);
    std::stable_sort(axes.begin(),axes.end(),[&](auto x,auto y) {
        const auto magnitude=[](std::ptrdiff_t value) {return value<0?std::size_t(-(value+1))+1:std::size_t(value);};
        const auto sx=magnitude(a.raw().strides[x]),sy=magnitude(a.raw().strides[y]);
        if (!sx || !sy) return sx>sy;
        return sx<sy;
    });
    return axes;
}
void layout(Tensor& t,const std::vector<std::size_t>& axes) {
    std::size_t stride=item_size(t.dtype);
    for (auto axis:axes) {t.strides[axis]=static_cast<std::ptrdiff_t>(stride);stride*=t.shape[axis];}
}
std::size_t c_index(const Array& a,std::size_t index,const std::vector<std::size_t>& axes) {
    std::vector<std::size_t> coordinate(a.raw().rank);
    for (auto axis:axes) {
        const auto n=a.raw().shape[axis];coordinate[axis]=n?index%n:0;index=n?index/n:0;
    }
    std::size_t flat=0;
    for (std::size_t axis=0;axis<coordinate.size();++axis) flat=flat*a.raw().shape[axis]+coordinate[axis];
    return flat;
}
std::vector<std::size_t> broadcast(const Array& a,const Array& b) {
    const auto rank=std::max(a.raw().rank,b.raw().rank);
    std::vector<std::size_t> out(rank,1);
    for (std::size_t i=0;i<rank;++i) {
        const auto x=i<rank-a.raw().rank?1:a.raw().shape[i-(rank-a.raw().rank)];
        const auto y=i<rank-b.raw().rank?1:b.raw().shape[i-(rank-b.raw().rank)];
        if (x!=y && x!=1 && y!=1) {
            const auto text=[](const Array& value) {std::string out="(";for (std::size_t j=0;j<value.raw().rank;++j) {if (j) out+=",";out+=std::to_string(value.raw().shape[j]);}if (value.raw().rank==1) out+=",";return out+")";};
            throw NumericError(TPMSHX_RESULT_VALUE_ERROR,"operands could not be broadcast together with shapes "+text(a)+" "+text(b)+" ");
        }
        out[i]=x==1?y:x;
    }
    return out;
}
std::size_t operand_index(const Array& a,std::size_t index,const std::vector<std::size_t>& shape) {
    std::size_t flat=0,multiplier=1;
    for (std::size_t k=0;k<shape.size();++k) {
        const auto axis=shape.size()-1-k,coordinate=shape[axis]?index%shape[axis]:0;
        index=shape[axis]?index/shape[axis]:0;
        if (k<a.raw().rank) {
            const auto n=a.raw().shape[a.raw().rank-1-k];
            flat+=(n==1?0:coordinate)*multiplier;multiplier*=n;
        }
    }
    return flat;
}
using Binary=Number(*)(const Number&,const Number&,Diagnostics&);
using Unary=Number(*)(const Number&,Diagnostics&);
struct Stage {
    Diagnostics& target;std::uint32_t op;bool scalar;std::uint32_t flags{};
    ~Stage() {if (flags) append_event(target,flags,op,scalar);}
    void take(const Diagnostics& source) {for (std::size_t i=0;i<source.event_count;++i) flags|=source.events[i].flags;}
};
Tensor apply(const Array& a,const Array& b,Diagnostics& d,Binary operation,std::uint32_t op) {
    auto shape=broadcast(a,b);
    Number za{};za.dtype=a.raw().dtype;za.origin=a.raw().origin;
    Number zb{};zb.dtype=b.raw().dtype;zb.origin=b.raw().origin;
    Diagnostics scratch{};
    const auto kind=operation(za,op==TPMSHX_RESULT_DIVIDE?converted(python_float(1),zb.dtype,zb.origin):zb,scratch);
    const bool weak_a=!strong(za) && a.raw().rank==0 && strong(zb);
    const bool weak_b=!strong(zb) && b.raw().rank==0 && strong(za);
    const auto prepare=[&](const Array& value) {
        const auto input=value.at(0);std::feclearexcept(FE_ALL_EXCEPT);
        auto out=converted(input,kind.dtype,kind.origin);out.origin=input.origin;
        event(d,TPMSHX_RESULT_CAST,false,true,half_flags(real_value(input),out));return out;
    };
    const auto scalar_a=weak_a?prepare(a):Number{};
    const auto scalar_b=weak_b?prepare(b):Number{};
    Tensor out(shape,kind.dtype,kind.origin);
    if (a.raw().rank==shape.size()) layout(out,fast_axes(a));
    else if (b.raw().rank==shape.size()) layout(out,fast_axes(b));
    Stage stage{d,op,kind.origin!=NA};
    for (std::size_t i=0;i<out.size();++i) {
        scratch={};
        try {out.put(i,operation(weak_a?scalar_a:a.at(operand_index(a,i,shape)),
                                weak_b?scalar_b:b.at(operand_index(b,i,shape)),scratch));}
        catch (...) {stage.take(scratch);throw;}
        stage.take(scratch);
    }
    return out;
}
Tensor apply(const Array& a,Diagnostics& d,Unary operation,std::uint32_t op) {
    Number z{};z.dtype=a.raw().dtype;z.origin=a.raw().origin;Diagnostics scratch{};
    const auto kind=operation(z,scratch);
    Tensor out(shape_of(a),kind.dtype,kind.origin);layout(out,fast_axes(a));
    Stage stage{d,op,kind.origin!=NA};
    for (std::size_t i=0;i<a.size();++i) {
        scratch={};
        try {out.put(i,operation(a.at(i),scratch));} catch (...) {stage.take(scratch);throw;}
        stage.take(scratch);
    }
    return out;
}
template<class Real,class Getter> Real pairwise(Getter get,std::size_t offset,std::size_t count) {
    if (count<8) {Real out=-Real(0);for (std::size_t i=0;i<count;++i) out+=get(offset+i);return out;}
    if (count>128) {const auto middle=(count/2)/8*8;return pairwise<Real>(get,offset,middle)+pairwise<Real>(get,offset+middle,count-middle);}
    std::array<Real,8> partial;for (std::size_t j=0;j<8;++j) partial[j]=get(offset+j);
    std::size_t i=8;
    for (;i+8<=count;i+=8) for (std::size_t j=0;j<8;++j) partial[j]+=get(offset+i+j);
    auto out=((partial[0]+partial[1])+(partial[2]+partial[3]))+((partial[4]+partial[5])+(partial[6]+partial[7]));
    for (;i<count;++i) out+=get(offset+i);return out;
}
// NumPy 2.5.4 loops_utils.h.src uses four interleaved complex lanes.
template<class Real,class Getter> std::complex<Real> complex_pairwise(Getter get,std::size_t offset,std::size_t count) {
    if (count<4) {
        std::complex<Real> out{-Real(0),-Real(0)};
        for (std::size_t i=0;i<count;++i) out+=get(offset+i);
        return out;
    }
    if (count>64) {
        const auto middle=(count/2)/4*4;
        return complex_pairwise<Real>(get,offset,middle)+complex_pairwise<Real>(get,offset+middle,count-middle);
    }
    std::array<std::complex<Real>,4> partial;
    for (std::size_t j=0;j<4;++j) partial[j]=get(offset+j);
    std::size_t i=4;
    for (;i+4<=count;i+=4) for (std::size_t j=0;j<4;++j) partial[j]+=get(offset+i+j);
    auto out=(partial[0]+partial[1])+(partial[2]+partial[3]);
    for (;i<count;++i) out+=get(offset+i);
    return out;
}
Number reduce_sum(const Array& a,std::uint32_t dtype,Diagnostics& d) {
    const auto axes=fast_axes(a);
    auto get=[&](std::size_t i) {return converted(a.at(c_index(a,i,axes)),dtype,NS);};
    if (integer_type(dtype)) {
        std::uint64_t result=0;for (std::size_t i=0;i<a.size();++i) result+=raw_integer(get(i));
        return signed_type(dtype)?signed_bits(result,dtype,NS):unsigned_bits(result,dtype,NS);
    }
    std::feclearexcept(FE_ALL_EXCEPT);Number out;long double exact=0;
    if (complex_type(dtype)) {
        if (dtype==C64) {
            auto value=std::complex<float>{0,0}+complex_pairwise<float>([&](auto i) {const auto n=get(i);return std::complex<float>{static_cast<float>(n.real),static_cast<float>(n.imaginary)};},0,a.size());
            out=complex_number(value.real(),value.imag(),dtype,NS);
        } else if (dtype==C128) {
            auto value=std::complex<double>{0,0}+complex_pairwise<double>([&](auto i) {const auto n=get(i);return std::complex<double>{static_cast<double>(n.real),static_cast<double>(n.imaginary)};},0,a.size());
            out=complex_number(value.real(),value.imag(),dtype,NS);
        } else {
            auto value=std::complex<long double>{0,0}+complex_pairwise<long double>([&](auto i) {const auto n=get(i);return std::complex<long double>{n.real,n.imaginary};},0,a.size());
            out=complex_number(value.real(),value.imag(),dtype,NS);
        }
    } else {
        if (dtype==F16 || dtype==F32) exact=0.f+pairwise<float>([&](auto i) {return static_cast<float>(real_value(get(i)));},0,a.size());
        else if (dtype==F64) exact=0.+pairwise<double>([&](auto i) {return static_cast<double>(real_value(get(i)));},0,a.size());
        else exact=0.L+pairwise<long double>([&](auto i) {return real_value(get(i));},0,a.size());
        out=floating(exact,dtype,NS);
    }
    event(d,TPMSHX_RESULT_REDUCE,false,true,half_flags(exact,out));return out;
}
bool compare(const Number& a,const Number& b,Diagnostics& d,bool inclusive) {
    if (!strong(a) && !strong(b) && integer_type(a.dtype) && integer_type(b.dtype)) {
        const bool an=signed_type(a.dtype)&&a.signed_value<0,bn=signed_type(b.dtype)&&b.signed_value<0;
        if (an!=bn) return an;
        if (an) return inclusive?a.signed_value<=b.signed_value:a.signed_value<b.signed_value;
        const auto x=raw_integer(a),y=raw_integer(b);return inclusive?x<=y:x<y;
    }
    if (!strong(a) && !strong(b) && integer_type(a.dtype)!=integer_type(b.dtype)
        && !complex_type(a.dtype) && !complex_type(b.dtype)) {
        const bool float_left=!integer_type(a.dtype);const auto& integer=float_left?b:a;
        const auto f=real_value(float_left?a:b);
        if (std::isnan(f)) return false;
        int order=0;
        if (signed_type(integer.dtype)) {
            if (f< -0x1p63L) order=-1;
            else if (f>=0x1p63L) order=1;
            else {const auto whole=static_cast<std::int64_t>(f);
                if (whole<integer.signed_value) order=-1;else if (whole>integer.signed_value) order=1;
                else {const auto fraction=f-static_cast<long double>(whole);order=fraction<0?-1:fraction>0?1:0;}}
        } else {
            if (f<0.) order=-1;
            else if (f>=0x1p64L) order=1;
            else {const auto whole=static_cast<std::uint64_t>(f);
                if (whole<integer.unsigned_value) order=-1;else if (whole>integer.unsigned_value) order=1;
                else {const auto fraction=f-static_cast<long double>(whole);order=fraction<0?-1:fraction>0?1:0;}}
        }
        if (!float_left) order=-order;return inclusive?order<=0:order<0;
    }
    const auto dtype=promoted(a,b);const auto origin=result_origin(a,b,dtype);
    std::feclearexcept(FE_ALL_EXCEPT);
    const auto x=converted(a,dtype,origin),y=converted(b,dtype,origin);
    event(d,TPMSHX_RESULT_CAST,false,strong(a)||strong(b),half_flags(real_value(a),x)|half_flags(real_value(b),y));
    if (complex_type(dtype)) {
        if (!strong(a) && !strong(b)) throw NumericError(TPMSHX_RESULT_TYPE_ERROR,"complex numbers do not support ordering");
        if (std::isnan(x.real)||std::isnan(y.real)||std::isnan(x.imaginary)||std::isnan(y.imaginary)) return false;
        return x.real<y.real || (x.real==y.real && (inclusive?x.imaginary<=y.imaginary:x.imaginary<y.imaginary));
    }
    if (integer_type(dtype)) return signed_type(dtype)?(inclusive?x.signed_value<=y.signed_value:x.signed_value<y.signed_value)
        :(inclusive?x.unsigned_value<=y.unsigned_value:x.unsigned_value<y.unsigned_value);
    return inclusive?x.real<=y.real:x.real<y.real;
}
}  // namespace

Tensor::Tensor(std::vector<std::size_t> sizes,std::uint32_t type,std::uint32_t source,bool fortran)
    :dtype(type),origin(source),shape(std::move(sizes)),strides(shape.size()) {
    std::size_t count=1;
    for (auto n:shape) {if (n && count>std::numeric_limits<std::size_t>::max()/n) throw std::invalid_argument("result array size overflow");count*=n;}
    if (count>std::numeric_limits<std::size_t>::max()/item_size(dtype)) throw std::invalid_argument("result array bytes overflow");
    bytes.resize(count*item_size(dtype));
    std::vector<std::size_t> axes(shape.size());
    if (fortran) std::iota(axes.begin(),axes.end(),0);else std::iota(axes.rbegin(),axes.rend(),0);
    layout(*this,axes);
}
RawArray Tensor::raw() const {return {bytes.data(),bytes.size(),0,dtype,origin,TPMSHX_RESULT_NATIVE_ENDIAN,0,shape.size(),shape.data(),strides.data()};}
std::size_t Tensor::size() const {return bytes.size()/item_size(dtype);}
void Tensor::put(std::size_t i,const Number& n) {store_number(const_cast<unsigned char*>(array().address(i)),n);}
Number python_float(double x) {return floating(x,F64,PF);}
Number python_int(std::int64_t x) {return signed_bits(static_cast<std::uint64_t>(x),I64,PI);}
Number scalar_result(Number value) {if (value.origin==NA) value.origin=NS;return value;}
std::uint32_t promote_dtype(std::uint32_t first,std::uint32_t second) {return common_dtype(first,second);}
Number cast(const Number& x,std::uint32_t type,std::uint32_t origin,Diagnostics& d) {
    std::feclearexcept(FE_ALL_EXCEPT);const auto out=converted(x,type,origin);
    event(d,TPMSHX_RESULT_CAST,false,strong(x),half_flags(real_value(x),out));return out;
}
Tensor cast(const Array& a,std::uint32_t type,Diagnostics& d) {
    Tensor out(shape_of(a),type,a.raw().origin);layout(out,fast_axes(a));
    Stage stage{d,TPMSHX_RESULT_CAST,false};
    for (std::size_t i=0;i<a.size();++i) {Diagnostics scratch{};out.put(i,cast(a.at(i),type,a.raw().origin,scratch));stage.take(scratch);}
    return out;
}
double to_float(const Number& x) {
    if (complex_type(x.dtype)) throw NumericError(TPMSHX_RESULT_TYPE_ERROR,"float() argument must be a real number, not 'complex'");
    return static_cast<double>(real_value(x));
}
Tensor scalar(const Number& n) {Tensor out({},n.dtype,n.origin);out.put(0,n);return out;}
Tensor copy(const Array& a,bool force_c) {Tensor out(shape_of(a),a.raw().dtype,a.raw().origin);if (!force_c) layout(out,fast_axes(a));for (std::size_t i=0;i<a.size();++i) out.put(i,a.at(i));return out;}
Number add(const Number& a,const Number& b,Diagnostics& d) {return binary(a,b,d,TPMSHX_RESULT_ADD);}
Number subtract(const Number& a,const Number& b,Diagnostics& d) {return binary(a,b,d,TPMSHX_RESULT_SUBTRACT);}
Number multiply(const Number& a,const Number& b,Diagnostics& d) {return binary(a,b,d,TPMSHX_RESULT_MULTIPLY);}
Number divide(const Number& a,const Number& b,Diagnostics& d) {return binary(a,b,d,TPMSHX_RESULT_DIVIDE);}
Number negative(const Number& a,Diagnostics&) {
    if (a.dtype==B) {
        if (!strong(a)) return python_int(zero(a)?0:-1);
        throw NumericError(TPMSHX_RESULT_TYPE_ERROR,"The numpy boolean negative, the `-` operator, is not supported, use the `~` operator or the logical_not function instead.");
    }
    if (integer_type(a.dtype)) return signed_type(a.dtype)?signed_bits(-raw_integer(a),a.dtype,a.origin):unsigned_bits(-raw_integer(a),a.dtype,a.origin);
    return complex_type(a.dtype)?complex_number(-a.real,-a.imaginary,a.dtype,a.origin):floating(-a.real,a.dtype,a.origin);
}
Number absolute(const Number& a,Diagnostics& d) {
    if (a.dtype==B && !strong(a)) return python_int(zero(a)?0:1);
    if (integer_type(a.dtype)) return signed_type(a.dtype) && a.signed_value<0?negative(a,d):a;
    if (complex_type(a.dtype)) {
        std::feclearexcept(FE_ALL_EXCEPT);auto out=floating(std::hypot(a.real,a.imaginary),component(a.dtype),a.origin);event(d,TPMSHX_RESULT_ABSOLUTE,a.origin!=NA,strong(a));return out;
    }
    return floating(std::abs(a.real),a.dtype,a.origin);
}
Number square(const Number& a,Diagnostics& d) {
    Diagnostics scratch{};const auto n=a.dtype==B?converted(a,I8,a.origin):a;
    const auto out=multiply(n,n,scratch);std::uint32_t flags=0;
    for (std::size_t i=0;i<scratch.event_count;++i) flags|=scratch.events[i].flags;
    if (flags) append_event(d,flags,TPMSHX_RESULT_SQUARE,false);return out;
}
Number power_two(const Number& a,Diagnostics& d) {
    Diagnostics scratch{};const auto out=square(a,scratch);std::uint32_t flags=0;
    for (std::size_t i=0;i<scratch.event_count;++i) flags|=scratch.events[i].flags;
    if (flags) append_event(d,flags,TPMSHX_RESULT_POWER,a.origin==NS);return out;
}
Number square_root(const Number& a,Diagnostics& d) {
    const auto type=integer_type(a.dtype)?(bits(a.dtype)<=8?F16:bits(a.dtype)<=16?F32:F64):a.dtype;
    const auto n=converted(a,type,a.origin);std::feclearexcept(FE_ALL_EXCEPT);Number out;long double exact=0;
    if (complex_type(type)) {
#if defined(__APPLE__)
        if (type==C64) {
            float parts[2];tpmshx_result_complex_sqrt_f32(static_cast<float>(n.real),static_cast<float>(n.imaginary),parts);
            out=complex_number(parts[0],parts[1],type,a.origin);
        } else if (type==C128) {
            double parts[2];tpmshx_result_complex_sqrt_f64(static_cast<double>(n.real),static_cast<double>(n.imaginary),parts);
            out=complex_number(parts[0],parts[1],type,a.origin);
        } else {
            long double parts[2];tpmshx_result_complex_sqrt_long_double(n.real,n.imaginary,parts);
            out=complex_number(parts[0],parts[1],type,a.origin);
        }
#else
        if (type==C64) {
            const auto value=std::sqrt(std::complex<float>{static_cast<float>(n.real),static_cast<float>(n.imaginary)});
            out=complex_number(value.real(),value.imag(),type,a.origin);
        } else if (type==C128) {
            const auto value=std::sqrt(std::complex<double>{static_cast<double>(n.real),static_cast<double>(n.imaginary)});
            out=complex_number(value.real(),value.imag(),type,a.origin);
        } else {
            const auto value=std::sqrt(std::complex<long double>{n.real,n.imaginary});out=complex_number(value.real(),value.imag(),type,a.origin);
        }
#endif
    } else {
        exact=type==F16 || type==F32?std::sqrt(static_cast<float>(n.real)):type==F64?std::sqrt(static_cast<double>(n.real)):std::sqrt(n.real);
        out=floating(exact,type,a.origin);
    }
    event(d,TPMSHX_RESULT_SQRT,a.origin!=NA,strong(a),half_flags(exact,out));return out;
}
bool less(const Number& a,const Number& b,Diagnostics& d) {return compare(a,b,d,false);}
bool less_equal(const Number& a,const Number& b,Diagnostics& d) {return compare(a,b,d,true);}
bool equal(const Number& a,const Number& b,Diagnostics& d) {return less_equal(a,b,d)&&less_equal(b,a,d);}
Number maximum(const Number& a,const Number& b,Diagnostics& d) {auto type=promoted(a,b),origin=result_origin(a,b,type);auto x=converted(a,type,origin),y=converted(b,type,origin);if (!finite(x) && !integer_type(type) && (std::isnan(x.real)||std::isnan(x.imaginary))) return x;return less(y,x,d)?x:y;}
Number minimum(const Number& a,const Number& b,Diagnostics& d) {auto type=promoted(a,b),origin=result_origin(a,b,type);auto x=converted(a,type,origin),y=converted(b,type,origin);if (!finite(x) && !integer_type(type) && (std::isnan(x.real)||std::isnan(x.imaginary))) return x;return less(x,y,d)?x:y;}
#define RESULT_BINARY_ARRAY(name,op) Tensor name(const Array& a,const Array& b,Diagnostics& d) {return apply(a,b,d,static_cast<Binary>(&name),op);}
RESULT_BINARY_ARRAY(add,TPMSHX_RESULT_ADD)
RESULT_BINARY_ARRAY(subtract,TPMSHX_RESULT_SUBTRACT)
RESULT_BINARY_ARRAY(multiply,TPMSHX_RESULT_MULTIPLY)
RESULT_BINARY_ARRAY(divide,TPMSHX_RESULT_DIVIDE)
RESULT_BINARY_ARRAY(maximum,TPMSHX_RESULT_MAXIMUM)
RESULT_BINARY_ARRAY(minimum,TPMSHX_RESULT_MINIMUM)
#undef RESULT_BINARY_ARRAY
#define RESULT_UNARY_ARRAY(name,op) Tensor name(const Array& a,Diagnostics& d) {return apply(a,d,static_cast<Unary>(&name),op);}
RESULT_UNARY_ARRAY(negative,TPMSHX_RESULT_MULTIPLY)
RESULT_UNARY_ARRAY(absolute,TPMSHX_RESULT_ABSOLUTE)
Tensor square(const Array& a,Diagnostics& d) {return apply(a,d,&array_square,TPMSHX_RESULT_SQUARE);}
Tensor power_two(const Array& a,Diagnostics& d) {
    const bool scalar=a.raw().origin==NS;
    return apply(a,d,scalar?static_cast<Unary>(&power_two):&array_square,
                 scalar?TPMSHX_RESULT_POWER:TPMSHX_RESULT_SQUARE);
}
RESULT_UNARY_ARRAY(square_root,TPMSHX_RESULT_SQRT)
#undef RESULT_UNARY_ARRAY
Tensor difference(const Array& a,std::size_t axis,Diagnostics& d) {
    if (axis>=a.raw().rank) throw NumericError(TPMSHX_RESULT_INDEX_ERROR,"axis is out of bounds");
    auto shape=shape_of(a);if (shape[axis]) --shape[axis];Tensor out(shape,a.raw().dtype,NA);
    std::size_t trailing=1;for (std::size_t j=axis+1;j<shape.size();++j) trailing*=shape[j];
    Stage stage{d,TPMSHX_RESULT_SUBTRACT,false};
    for (std::size_t i=0;i<out.size();++i) {
        const auto inner=i%trailing,position=(i/trailing)%shape[axis],outer=i/(trailing*shape[axis]);
        const auto first=(outer*a.raw().shape[axis]+position)*trailing+inner;Diagnostics scratch{};
        const auto value=a.raw().dtype==B?unsigned_bits(!equal(a.at(first+trailing),a.at(first),scratch),B,NA):subtract(a.at(first+trailing),a.at(first),scratch);
        out.put(i,value);stage.take(scratch);
    }
    return out;
}
Number sum(const Array& a,Diagnostics& d) {auto type=a.raw().dtype;if (type==B || (integer_type(type)&&signed_type(type))) type=I64;else if (integer_type(type)) type=U64;return reduce_sum(a,type,d);}
double sum_as_float(const Array& a,Diagnostics& d) {return to_float(sum(a,d));}
Number mean(const Array& a,Diagnostics& d) {
    auto type=integer_type(a.raw().dtype)?F64:a.raw().dtype==F16?F32:a.raw().dtype;
    auto total=reduce_sum(a,type,d);auto count=signed_bits(a.size(),I64,NS);
    auto out=divide(total,count,d);out=cast(out,type,NS,d);
    return a.raw().dtype==F16?cast(out,F16,NS,d):out;
}
Number variance(const Array& a,Diagnostics& d) {
    const auto type=integer_type(a.raw().dtype)?F64:a.raw().dtype;
    auto total=reduce_sum(a,type,d);total.origin=NA;
    auto center=cast(divide(total,signed_bits(a.size(),I64,NS),d),type,NA,d);
    auto center_array=scalar(center);auto differences=subtract(a,center_array.array(),d);
    Tensor squared({0},component(type),NA);
    if (complex_type(type)) {
        auto dimensions=differences.shape;dimensions.push_back(2);
        Tensor components(dimensions,component(type),NA);
        auto axes=fast_axes(differences.array());axes.insert(axes.begin(),differences.shape.size());layout(components,axes);
        for (std::size_t i=0;i<differences.size();++i) {
            const auto n=differences.array().at(i);
            components.put(i*2,floating(n.real,component(type),NA));
            components.put(i*2+1,floating(n.imaginary,component(type),NA));
        }
        auto powers=square(components.array(),d);
        auto real=powers.raw();--real.rank;
        auto imaginary=real;imaginary.offset=item_size(component(type));
        squared=add(Array(real),Array(imaginary),d);
    } else squared=square(differences.array(),d);
    auto out=sum(squared.array(),d);return cast(divide(out,signed_bits(a.size(),I64,NS),d),out.dtype,NS,d);
}
Number standard_deviation(const Array& a,Diagnostics& d) {return square_root(variance(a,d),d);}
Number maximum(const Array& a,Diagnostics& d) {if (!a.size()) throw NumericError(TPMSHX_RESULT_VALUE_ERROR,"zero-size array to reduction operation maximum which has no identity");auto out=a.at(0);for (std::size_t i=1;i<a.size();++i) out=maximum(out,a.at(i),d);out.origin=NS;return out;}
Number minimum(const Array& a,Diagnostics& d) {if (!a.size()) throw NumericError(TPMSHX_RESULT_VALUE_ERROR,"zero-size array to reduction operation minimum which has no identity");auto out=a.at(0);for (std::size_t i=1;i<a.size();++i) out=minimum(out,a.at(i),d);out.origin=NS;return out;}

// Copyright (c) 2001-2024 Python Software Foundation; All Rights Reserved.
// Adapted from CPython 3.13.2 bltinmodule.c; the retained Python license applies.
double python_float_sum(const std::vector<double>& values) {
    if (values.empty()) return 0.;double total=0.+values[0],correction=0.;
    for (std::size_t i=1;i<values.size();++i) {const auto x=values[i],next=total+x;
        if (std::fabs(total)>=std::fabs(x)) correction+=(total-next)+x;else correction+=(x-next)+total;total=next;}
    if (correction!=0. && std::isfinite(correction)) total+=correction;return total;
}

}  // namespace tpmshx::result::arithmetic
