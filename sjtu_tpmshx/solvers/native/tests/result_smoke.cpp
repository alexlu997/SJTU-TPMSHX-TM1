#include "tpmshx/result_arithmetic.hpp"

#include <array>
#include <cstdint>
#include <iostream>

int main() {
    using namespace tpmshx::result;
    std::array<std::uint64_t,2> integers{UINT64_C(9007199254740993),UINT64_MAX};
    const std::array<std::size_t,1> shape{2};
    const std::array<std::ptrdiff_t,1> strides{8};
    RawArray raw{integers.data(),sizeof(integers),0,TPMSHX_RESULT_U64,TPMSHX_RESULT_NUMPY_ARRAY,
        TPMSHX_RESULT_NATIVE_ENDIAN,0,1,shape.data(),strides.data()};
    Array values(raw);
    if (values.at(0).unsigned_value!=integers[0] || values.at(1).unsigned_value!=integers[1]) return 1;
    if (arithmetic::python_float_sum({1e16,1.,-1e16})!=1.) return 2;
    const auto scalar=pack_scalar(values.at(1));
    if (read_scalar(scalar).unsigned_value!=UINT64_MAX) return 3;
    struct Format {std::uint32_t dtype;std::size_t component_bytes;std::size_t components;};
    const Format formats[]{
        {TPMSHX_RESULT_BOOL,1,1},{TPMSHX_RESULT_I8,1,1},{TPMSHX_RESULT_U8,1,1},
        {TPMSHX_RESULT_I16,2,1},{TPMSHX_RESULT_U16,2,1},{TPMSHX_RESULT_F16,2,1},
        {TPMSHX_RESULT_I32,4,1},{TPMSHX_RESULT_U32,4,1},{TPMSHX_RESULT_F32,4,1},
        {TPMSHX_RESULT_I64,8,1},{TPMSHX_RESULT_U64,8,1},{TPMSHX_RESULT_F64,8,1},
        {TPMSHX_RESULT_LONG_DOUBLE,sizeof(long double),1},
        {TPMSHX_RESULT_C64,4,2},{TPMSHX_RESULT_C128,8,2},
        {TPMSHX_RESULT_COMPLEX_LONG_DOUBLE,sizeof(long double),2}};
    const std::uint32_t orders[]{TPMSHX_RESULT_NATIVE_ENDIAN,TPMSHX_RESULT_LITTLE_ENDIAN,TPMSHX_RESULT_BIG_ENDIAN};
    const std::uint16_t one=1;
    const bool native_little=*reinterpret_cast<const unsigned char*>(&one)==1;
    const std::array<unsigned char,32> payload{
        0,0,0,0,0,0,0,0x80,0x42,0,0,0,0,0,0xf8,0x7f,
        0,0,0,0x80,0x42,0,0xc0,0x7f,0,0x80,0x42,0x7e,0xa5,0x5a,0xfe,0xff};
    for (unsigned pattern=0;pattern<3;++pattern) {
        std::array<unsigned char,96> original{};
        for (std::size_t i=0;i<original.size();++i) original[i]=static_cast<unsigned char>(i+1);
        if (pattern) for (std::size_t i=0;i<payload.size();++i)
            original[32+i]=pattern==1?0xff:payload[i];
        for (const auto& format:formats) for (auto source_order:orders) for (auto destination_order:orders)
            for (std::size_t destination:{0u,31u,32u,33u,64u}) {
                const bool source_little=source_order==TPMSHX_RESULT_NATIVE_ENDIAN?native_little:source_order==TPMSHX_RESULT_LITTLE_ENDIAN;
                const bool destination_little=destination_order==TPMSHX_RESULT_NATIVE_ENDIAN?native_little:destination_order==TPMSHX_RESULT_LITTLE_ENDIAN;
                auto expected=original;
                for (std::size_t part=0;part<format.components;++part)
                    for (std::size_t byte=0;byte<format.component_bytes;++byte) {
                        const auto offset=part*format.component_bytes;
                        const auto input=source_little==destination_little?byte:format.component_bytes-1-byte;
                        expected[destination+offset+byte]=original[32+offset+input];
                    }
                auto actual=original;
                copy_number(actual.data()+32,source_order,actual.data()+destination,destination_order,format.dtype);
                if (actual!=expected) {
                    std::cerr<<"Byte copy differs: dtype="<<format.dtype<<", source order="<<source_order
                             <<", destination order="<<destination_order<<", offset="<<destination<<", pattern="<<pattern<<'\n';
                    return 4;
                }
            }
    }
    auto unchanged=payload;
    try {copy_number(payload.data(),3,unchanged.data(),TPMSHX_RESULT_NATIVE_ENDIAN,TPMSHX_RESULT_F64);return 5;}
    catch (const std::invalid_argument&) {if (unchanged!=payload) return 6;}
    std::cout<<"PASS: exact byte copies across 16 formats, three byte orders and five storage offsets\n";
    std::cout<<"PASS: independent result C++ caller and exact integer transport\n";
    return 0;
}
