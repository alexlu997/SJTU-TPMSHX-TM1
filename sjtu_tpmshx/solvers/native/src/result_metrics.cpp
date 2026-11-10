#include "tpmshx/result_metrics.hpp"

#include <algorithm>
#include <cmath>

namespace tpmshx::result::metrics {
namespace a=arithmetic;
namespace {
Tensor scalar_array(const Number& value) {return a::scalar(value);}
Tensor product(const Array& field,const Number& value,Diagnostics& d) {auto s=scalar_array(value);return a::multiply(field,s.array(),d);}
Tensor oriented(const Array& field,bool low,bool binary_sign,Diagnostics& d) {
    if (binary_sign) return product(field,a::python_int(low?-1:1),d);
    return low?a::negative(field,d):a::copy(field);
}
Tensor selected(const Array& values,const std::vector<std::size_t>& indices) {
    Tensor out({indices.size()},values.raw().dtype,TPMSHX_RESULT_NUMPY_ARRAY);
    for (std::size_t i=0;i<indices.size();++i) out.put(i,values.at(indices[i]));return out;
}
double python_divide(double first,double second) {
    if (second==0.) throw NumericError(TPMSHX_RESULT_ZERO_DIVISION,"float division by zero");return first/second;
}
double maximum3(double first,double second,double third) {if (second>first) first=second;if (third>first) first=third;return first;}
Number representative(const Array& value) {
    if (value.size()) return value.at(0);
    Number out{};out.dtype=value.raw().dtype;out.origin=value.raw().origin;return out;
}
bool quick_denominator_less(const Array& first,const Array& second,Diagnostics& d) {
    // The numerator has checked broadcasting before Python max tests this shape.
    const auto size=first.size() && second.size()?std::max(first.size(),second.size()):0;
    const bool comparison=a::less(representative(first),representative(second),d);
    if (!size) throw NumericError(TPMSHX_RESULT_VALUE_ERROR,
        "The truth value of an empty array is ambiguous. Use `array.size > 0` to check that an array is not empty.");
    if (size!=1) throw NumericError(TPMSHX_RESULT_VALUE_ERROR,
        "The truth value of an array with more than one element is ambiguous. Use a.any() or a.all()");
    return comparison;
}
Tensor capacity_weights(const std::array<Array,5>& input,Diagnostics& d) {
    auto magnitude=a::absolute(input[2],d);
    auto weights=a::multiply(input[0],input[1],d);
    weights=a::multiply(weights.array(),magnitude.array(),d);
    weights=a::multiply(weights.array(),input[3],d);
    return a::multiply(weights.array(),input[4],d);
}
Tensor broadcast_width(const Array& width,std::vector<std::size_t> shape,std::size_t axis) {
    Tensor out(std::move(shape),width.raw().dtype,TPMSHX_RESULT_NUMPY_ARRAY);
    std::size_t stride=1;for (std::size_t k=axis+1;k<out.shape.size();++k) stride*=out.shape[k];
    for (std::size_t i=0;i<out.size();++i) out.put(i,width.at((i/stride)%out.shape[axis]));return out;
}
template<std::size_t N> std::array<double,2> mass(const std::array<Array,N>& faces,bool binary,Diagnostics& d) {
    std::vector<Tensor> outward;outward.reserve(N);
    for (std::size_t i=0;i<N;++i) outward.push_back(oriented(faces[i],i%2==0,binary,d));
    std::vector<double> inward_sums,outward_sums;
    for (int sign:{-1,1}) {
        auto& sums=sign<0?inward_sums:outward_sums;
        for (const auto& face:outward) {
            auto signed_face=binary?product(face.array(),a::python_int(sign),d)
                :sign<0?a::negative(face.array(),d):a::copy(face.array());
            auto zero=scalar_array(binary?a::python_int(0):a::python_float(0.));
            auto positive=a::maximum(signed_face.array(),zero.array(),d);
            sums.push_back(a::sum_as_float(positive.array(),d));
        }
    }
    return {a::python_float_sum(inward_sums),a::python_float_sum(outward_sums)};
}
}  // namespace

Tensor pressure_ratio(const Array& first,const Array& second,Diagnostics& d) {
    auto denominator=a::add(first,second,d);return a::divide(first,denominator.array(),d);
}
Tensor pressure_face(const Array& first,const Array& second,const Array& ratio,Diagnostics& d) {
    auto one=scalar_array(a::python_float(1.));auto factor=a::add(one.array(),ratio,d);
    auto leading=a::multiply(factor.array(),first,d);auto adjacent=a::multiply(ratio,second,d);
    return a::subtract(leading.array(),adjacent.array(),d);
}
Tensor capacity_porosity(const Array& epsilon,const Array& split,Diagnostics& d) {return a::multiply(epsilon,split,d);}
Tensor capacity_split_field(const Array& split,Diagnostics& d) {auto one=scalar_array(a::python_int(1));return a::subtract(one.array(),split,d);}
Number capacity_split(const Number& split,bool cold,Diagnostics& d) {return cold?a::scalar_result(a::subtract(a::python_int(1),split,d)):split;}
bool port_width_valid(const Array& values) {for (std::size_t i=0;i<values.size();++i) if (!finite(values.at(i)) || !(real_value(values.at(i))>0.)) return false;return true;}
bool port_opening_valid(const Array& values) {for (std::size_t i=0;i<values.size();++i) if (!finite(values.at(i)) || !(real_value(values.at(i))>=0.)) return false;return true;}
double weighted_mean(const Array& values,const Array& weights,Diagnostics& d) {
    const auto total=a::sum_as_float(weights,d);
    if (total<=1e-30) throw NumericError(TPMSHX_RESULT_VALUE_ERROR,"no flowing outlet evidence");
    auto products=a::multiply(values,weights,d);return a::to_float(a::divide(a::sum(products.array(),d),a::python_float(total),d));
}
std::array<Tensor,2> port_weights(const Array& dx,const Array& dz,
    const Array& inlet_opening,const Array& outlet_opening,Diagnostics& d) {
    const std::vector<std::size_t> shape{dx.size(),dz.size()};
    auto x=broadcast_width(dx,shape,0),z=broadcast_width(dz,shape,1);
    auto area=a::multiply(x.array(),z.array(),d);
    auto wi=a::multiply(inlet_opening,area.array(),d),wo=a::multiply(outlet_opening,area.array(),d);
    return {std::move(wi),std::move(wo)};
}
double capacity_duty(const std::array<Array,5>& inlet,const std::array<Array,5>& outlet,
    const Array& inlet_temperature,const Array& outlet_temperature,Diagnostics& d) {
    auto wi=capacity_weights(inlet,d),wo=capacity_weights(outlet,d);
    const auto capacity=a::sum_as_float(wi.array(),d);if (capacity<1e-30) return 0.;
    auto incoming=a::multiply(wi.array(),inlet_temperature,d);
    const auto tin=python_divide(a::sum_as_float(incoming.array(),d),capacity);
    const auto total=a::sum_as_float(wo.array(),d);
    double tout;
    if (total>1e-30) {auto outgoing=a::multiply(wo.array(),outlet_temperature,d);tout=python_divide(a::sum_as_float(outgoing.array(),d),total);}
    else tout=a::to_float(a::mean(outlet_temperature,d));
    return capacity*(tin-tout);
}
double outlet_temperature_2d(const Array& temperature,const Array& mass_field,const Array& opening,bool reverse,Diagnostics& d) {
    auto outward=reverse?a::negative(mass_field,d):a::copy(mass_field);
    if (opening.size()!=mass_field.size()) throw NumericError(TPMSHX_RESULT_INDEX_ERROR,"boolean index did not match indexed array along axis 0");
    std::vector<std::size_t> opened;
    for (std::size_t i=0;i<opening.size();++i) if (a::less(a::python_float(0.),opening.at(i),d)) opened.push_back(i);
    auto raw_weights=selected(outward.array(),opened),zero=scalar_array(a::python_float(0.));
    auto weights=a::maximum(raw_weights.array(),zero.array(),d);const auto total=a::sum_as_float(weights.array(),d);
    if (!std::isfinite(total)||total<=0.) throw NumericError(TPMSHX_RESULT_VALUE_ERROR,"2D outlet temperature requires finite positive outward mass flow");
    std::vector<std::size_t> flowing;
    for (std::size_t i=0;i<weights.size();++i) if (a::less(a::python_float(0.),weights.array().at(i),d)) flowing.push_back(i);
    auto temperatures=selected(temperature,opened);auto w=selected(weights.array(),flowing),t=selected(temperatures.array(),flowing);
    auto products=a::multiply(w.array(),t.array(),d);
    const auto value=a::to_float(a::divide(a::sum(products.array(),d),a::python_float(total),d));
    if (!std::isfinite(value)) throw NumericError(TPMSHX_RESULT_VALUE_ERROR,"2D outlet temperature is non-finite");return value;
}
double outlet_temperature_3d(const Array& temperature,const Array& mass_field,bool reverse,Diagnostics& d) {
    auto outward=product(mass_field,a::python_int(reverse?-1:1),d);
    for (std::size_t i=0;i<outward.size();++i) if (!finite(outward.array().at(i)))
        throw NumericError(TPMSHX_RESULT_VALUE_ERROR,"outlet temperature requires finite native mass flux");
    auto zero=scalar_array(a::python_float(0.));auto weights=a::maximum(outward.array(),zero.array(),d);
    std::vector<std::size_t> flowing;
    for (std::size_t i=0;i<weights.size();++i) if (a::less(a::python_float(0.),weights.array().at(i),d)) flowing.push_back(i);
    auto w=selected(weights.array(),flowing),t=selected(temperature,flowing);return weighted_mean(t.array(),w.array(),d);
}
double boundary_enthalpy_duty(const std::array<Array,6>& adjacent,const std::array<Array,6>& mass_field,const Number& inlet_h,Diagnostics& d) {
    double net=0.;
    for (std::size_t face=0;face<6;++face) {
        auto outward=oriented(mass_field[face],face%2==0,false,d);
        auto outgoing=a::multiply(outward.array(),adjacent[face],d),incoming=product(outward.array(),inlet_h,d);
        const auto type=a::promote_dtype(outgoing.dtype,incoming.dtype);auto out=a::cast(outgoing.array(),type,d),in=a::cast(incoming.array(),type,d);
        Tensor powers(out.shape,type,TPMSHX_RESULT_NUMPY_ARRAY);
        for (std::size_t i=0;i<powers.size();++i) powers.put(i,a::less(a::python_float(0.),outward.array().at(i),d)?out.array().at(i):in.array().at(i));
        net+=a::sum_as_float(powers.array(),d);
    }
    return -net;
}
double plane_duty(const std::vector<Array>& faces,Diagnostics& d) {std::vector<double> sums;for (const auto& face:faces) sums.push_back(a::sum_as_float(face,d));return -a::python_float_sum(sums);}
double staggered_power_duty_2d(const std::array<Array,4>& faces,Diagnostics& d) {std::vector<double> sums;for (std::size_t i=0;i<4;++i) {auto field=oriented(faces[i],i%2==0,false,d);sums.push_back(a::sum_as_float(field.array(),d));}return -a::python_float_sum(sums);}
std::array<double,2> boundary_mass_2d(const std::array<Array,4>& faces,Diagnostics& d) {return mass(faces,false,d);}
std::array<double,2> boundary_mass_3d(const std::array<Array,6>& faces,Diagnostics& d) {return mass(faces,true,d);}
double solid_mass_2d(const Array& epsilon,const Array& density,const Array& dx,const Array& dy,Diagnostics& d) {
    auto one=scalar_array(a::python_int(1));auto solid=a::subtract(one.array(),epsilon,d);solid=a::multiply(solid.array(),density,d);
    const auto shape=solid.shape;auto x=broadcast_width(dx,shape,0),y=broadcast_width(dy,shape,1);
    solid=a::multiply(solid.array(),x.array(),d);solid=a::multiply(solid.array(),y.array(),d);return a::sum_as_float(solid.array(),d);
}
double solid_mass_3d(const Array& epsilon,const Array& density,const Array& dx,const Array& dy,const Array& dz,Diagnostics& d) {
    const std::vector<std::size_t> shape{dx.size(),dy.size(),dz.size()};
    auto x=broadcast_width(dx,shape,0),y=broadcast_width(dy,shape,1),z=broadcast_width(dz,shape,2);
    auto volume=a::multiply(x.array(),y.array(),d);volume=a::multiply(volume.array(),z.array(),d);
    auto one=scalar_array(a::python_int(1));auto solid=a::subtract(one.array(),epsilon,d);
    solid=a::multiply(density,solid.array(),d);solid=a::multiply(solid.array(),volume.array(),d);return a::sum_as_float(solid.array(),d);
}
double outlet_mean(const Array& plane,Diagnostics& d) {return a::to_float(a::mean(plane,d));}
Tensor capture_area_weights(const Array& dx,const Array& dy,Diagnostics& d) {
    const std::vector<std::size_t> shape{dx.size(),dy.size()};
    auto x=broadcast_width(dx,shape,0),y=broadcast_width(dy,shape,1);
    return a::multiply(x.array(),y.array(),d);
}
double capture_area(const Array& dx,const Array& dy,Diagnostics& d) {
    auto area=capture_area_weights(dx,dy,d);return a::sum_as_float(area.array(),d);
}
double duty_magnitude(double duty) {return std::abs(duty);}
double mass_imbalance(double inlet,double outlet) {return std::abs(outlet-inlet)/maximum3(inlet,outlet,1e-30);}
double full_energy_imbalance(double x,double y) {return std::abs(x+y)/maximum3(std::abs(x),std::abs(y),1e-30);}
Number quick_energy_imbalance(const Number& x,const Number& y,Diagnostics& d) {
    const auto numerator=a::scalar_result(a::absolute(a::scalar_result(a::subtract(x,y,d)),d));
    auto denominator=a::scalar_result(a::absolute(x,d));const auto other=a::scalar_result(a::absolute(y,d)),floor=a::python_float(1e-30);
    if (a::less(denominator,other,d)) denominator=other;
    if (a::less(denominator,floor,d)) denominator=floor;
    return a::scalar_result(a::divide(numerator,denominator,d));
}
double richardson_duty(double fine,double coarse) {return (4.*std::abs(fine)-std::abs(coarse))/3.;}
Number pressure_difference(const Number& inlet,const Number& outlet,Diagnostics& d) {return a::scalar_result(a::subtract(inlet,outlet,d));}
Number absolute_outlet_pressure(const Number& outlet,const Number& reference,Diagnostics& d) {return a::scalar_result(a::add(outlet,reference,d));}
Number quick_temperature_difference(const Number& inlet,double outlet,Diagnostics& d) {return a::scalar_result(a::subtract(inlet,a::python_float(outlet),d));}
Number quick_capacity_product(const Number& mass_value,const Number& cp,Diagnostics& d) {return a::scalar_result(a::multiply(mass_value,cp,d));}
Number quick_duty_from_capacity(const Number& capacity,const Number& delta,bool cold,Diagnostics& d) {return a::scalar_result(a::multiply(a::scalar_result(a::multiply(capacity,delta,d)),a::python_int(cold?-1:1),d));}
Number quick_reynolds_flow(const Number& rho,const Number& velocity,Diagnostics& d) {return a::scalar_result(a::multiply(rho,a::scalar_result(a::absolute(velocity,d)),d));}
Number quick_reynolds_length(const Number& flow,const Number& diameter,Diagnostics& d) {return a::scalar_result(a::multiply(flow,diameter,d));}
Number quick_reynolds_quotient(const Number& numerator,const Number& mu,Diagnostics& d) {return a::scalar_result(a::divide(numerator,mu,d));}
Tensor pressure_difference_field(const Array& inlet,const Array& outlet,Diagnostics& d) {return a::subtract(inlet,outlet,d);}
Tensor quick_temperature_difference_field(const Array& inlet,double outlet,Diagnostics& d) {
    auto mean=scalar_array(a::python_float(outlet));return a::subtract(inlet,mean.array(),d);
}
Tensor quick_capacity_product_field(const Array& mass_value,const Array& cp,Diagnostics& d) {return a::multiply(mass_value,cp,d);}
Tensor quick_duty_from_capacity_field(const Array& capacity,const Array& delta,bool cold,Diagnostics& d) {
    auto duty=a::multiply(capacity,delta,d);return product(duty.array(),a::python_int(cold?-1:1),d);
}
Tensor quick_reynolds_flow_field(const Array& rho,const Array& velocity,Diagnostics& d) {
    auto speed=a::absolute(velocity,d);return a::multiply(rho,speed.array(),d);
}
Tensor quick_reynolds_length_field(const Array& flow,const Array& diameter,Diagnostics& d) {return a::multiply(flow,diameter,d);}
Tensor quick_reynolds_quotient_field(const Array& numerator,const Array& mu,Diagnostics& d) {return a::divide(numerator,mu,d);}
Tensor quick_energy_imbalance_field(const Array& first,const Array& second,Diagnostics& d) {
    auto difference=a::subtract(first,second,d);auto numerator=a::absolute(difference.array(),d);
    auto denominator=a::absolute(first,d);auto other=a::absolute(second,d);
    if (quick_denominator_less(denominator.array(),other.array(),d)) denominator=std::move(other);
    auto floor=scalar_array(a::python_float(1e-30));
    if (quick_denominator_less(denominator.array(),floor.array(),d)) denominator=std::move(floor);
    return a::divide(numerator.array(),denominator.array(),d);
}
}  // namespace tpmshx::result::metrics
