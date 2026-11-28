#include "tpmshx/result_metrics.hpp"

#include <algorithm>
#include <cmath>

namespace tpmshx::result::metrics {
namespace a=arithmetic;
namespace {
Tensor scalar_array(const Number& value) {return a::scalar(value);}
Tensor product(const Array& field,const Number& value,Diagnostics& d) {auto s=scalar_array(value);return a::multiply(field,s.array(),d);}
Tensor oriented(const Array& field,bool low,bool binary_sign,Diagnostics& d) {
    if (binary_sign) return product(field,a::python_float(low?-1.:1.),d);
    return low?a::negative(field):a::copy(field);
}
Tensor selected(const Array& values,const std::vector<std::size_t>& indices) {
    Tensor out({indices.size()});
    for (std::size_t i=0;i<indices.size();++i) out.values[i]=values.at(indices[i]);
    return out;
}
double python_divide(double first,double second) {
    if (second==0.) throw NumericError(TPMSHX_RESULT_ZERO_DIVISION,"float division by zero");
    return first/second;
}
double maximum3(double first,double second,double third) {if (second>first) first=second;if (third>first) first=third;return first;}
Tensor capacity_weights(const std::array<Array,5>& input,Diagnostics& d) {
    auto magnitude=a::absolute(input[2]);
    auto weights=a::multiply(input[0],input[1],d);
    weights=a::multiply(weights.array(),magnitude.array(),d);
    weights=a::multiply(weights.array(),input[3],d);
    return a::multiply(weights.array(),input[4],d);
}
Tensor broadcast_width(const Array& width,std::vector<std::size_t> shape,std::size_t axis) {
    Tensor out(std::move(shape));
    std::size_t stride=1;for (std::size_t k=axis+1;k<out.shape.size();++k) stride*=out.shape[k];
    for (std::size_t i=0;i<out.size();++i) out.values[i]=width.at((i/stride)%out.shape[axis]);
    return out;
}
Tensor expanded_width(const Array& width,std::size_t axis) {
    if (!width.rank()) throw NumericError(TPMSHX_RESULT_INDEX_ERROR,
        "too many indices for array: array is 0-dimensional, but 1 were indexed");
    auto out=a::copy(width);
    out.shape.insert(out.shape.begin()+static_cast<std::ptrdiff_t>(axis),1);
    out.kind=Kind::numpy_array;
    return out;
}
template<std::size_t N> std::array<double,2> mass(const std::array<Array,N>& faces,bool binary,Diagnostics& d) {
    std::vector<Tensor> outward;outward.reserve(N);
    for (std::size_t i=0;i<N;++i) outward.push_back(oriented(faces[i],i%2==0,binary,d));
    std::vector<double> inward_sums,outward_sums;
    for (int sign:{-1,1}) {
        auto& sums=sign<0?inward_sums:outward_sums;
        for (const auto& face:outward) {
            auto signed_face=binary?product(face.array(),a::python_float(sign),d)
                :sign<0?a::negative(face.array()):a::copy(face.array());
            auto zero=scalar_array(a::python_float(0.));
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
Tensor capacity_split_field(const Array& split,Diagnostics& d) {auto one=scalar_array(a::python_float(1.));return a::subtract(one.array(),split,d);}
Number capacity_split(const Number& split,bool cold,Diagnostics& d) {return cold?a::numpy_scalar(a::subtract(a::python_float(1.),split,d)):split;}
bool port_width_valid(const Array& values) {for (std::size_t i=0;i<values.size();++i) if (!std::isfinite(values.at(i)) || !(values.at(i)>0.)) return false;return true;}
bool port_opening_valid(const Array& values) {for (std::size_t i=0;i<values.size();++i) if (!std::isfinite(values.at(i)) || !(values.at(i)>=0.)) return false;return true;}
double weighted_mean(const Array& values,const Array& weights,Diagnostics& d) {
    const auto total=a::sum_as_float(weights,d);
    if (total<=1e-30) throw NumericError(TPMSHX_RESULT_VALUE_ERROR,"no flowing outlet evidence");
    auto products=a::multiply(values,weights,d);return a::divide(a::sum(products.array(),d),a::python_float(total),d).value;
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
    else tout=a::mean(outlet_temperature,d).value;
    return capacity*(tin-tout);
}
double outlet_temperature_2d(const Array& temperature,const Array& mass_field,const Array& opening,bool reverse,Diagnostics& d) {
    auto outward=reverse?a::negative(mass_field):a::copy(mass_field);
    if (opening.size()!=mass_field.size()) throw NumericError(TPMSHX_RESULT_INDEX_ERROR,"boolean index did not match indexed array along axis 0");
    std::vector<std::size_t> opened;
    for (std::size_t i=0;i<opening.size();++i) if (0.<opening.at(i)) opened.push_back(i);
    auto raw_weights=selected(outward.array(),opened),zero=scalar_array(a::python_float(0.));
    auto weights=a::maximum(raw_weights.array(),zero.array(),d);const auto total=a::sum_as_float(weights.array(),d);
    if (!std::isfinite(total)||total<=0.) throw NumericError(TPMSHX_RESULT_VALUE_ERROR,"2D outlet temperature requires finite positive outward mass flow");
    std::vector<std::size_t> flowing;
    for (std::size_t i=0;i<weights.size();++i) if (0.<weights.values[i]) flowing.push_back(i);
    auto temperatures=selected(temperature,opened);auto w=selected(weights.array(),flowing),t=selected(temperatures.array(),flowing);
    auto products=a::multiply(w.array(),t.array(),d);
    const auto value=a::divide(a::sum(products.array(),d),a::python_float(total),d).value;
    if (!std::isfinite(value)) throw NumericError(TPMSHX_RESULT_VALUE_ERROR,"2D outlet temperature is non-finite");
    return value;
}
double outlet_temperature_3d(const Array& temperature,const Array& mass_field,bool reverse,Diagnostics& d) {
    auto outward=product(mass_field,a::python_float(reverse?-1.:1.),d);
    for (std::size_t i=0;i<outward.size();++i) if (!std::isfinite(outward.values[i]))
        throw NumericError(TPMSHX_RESULT_VALUE_ERROR,"outlet temperature requires finite native mass flux");
    auto zero=scalar_array(a::python_float(0.));auto weights=a::maximum(outward.array(),zero.array(),d);
    std::vector<std::size_t> flowing;
    for (std::size_t i=0;i<weights.size();++i) if (0.<weights.values[i]) flowing.push_back(i);
    auto w=selected(weights.array(),flowing),t=selected(temperature,flowing);return weighted_mean(t.array(),w.array(),d);
}
double boundary_enthalpy_duty(const std::array<Array,6>& adjacent,const std::array<Array,6>& mass_field,const Number& inlet_h,Diagnostics& d) {
    double net=0.;
    for (std::size_t face=0;face<6;++face) {
        auto outward=oriented(mass_field[face],face%2==0,false,d);
        auto out=a::multiply(outward.array(),adjacent[face],d),in=product(outward.array(),inlet_h,d);
        Tensor powers(out.shape);
        for (std::size_t i=0;i<powers.size();++i) powers.values[i]=0.<outward.values[i]?out.values[i]:in.values[i];
        net+=a::sum_as_float(powers.array(),d);
    }
    return -net;
}
double plane_duty(const std::vector<Array>& faces,Diagnostics& d) {std::vector<double> sums;for (const auto& face:faces) sums.push_back(a::sum_as_float(face,d));return -a::python_float_sum(sums);}
double staggered_power_duty_2d(const std::array<Array,4>& faces,Diagnostics& d) {std::vector<double> sums;for (std::size_t i=0;i<4;++i) {auto field=oriented(faces[i],i%2==0,false,d);sums.push_back(a::sum_as_float(field.array(),d));}return -a::python_float_sum(sums);}
std::array<double,2> boundary_mass_2d(const std::array<Array,4>& faces,Diagnostics& d) {return mass(faces,false,d);}
std::array<double,2> boundary_mass_3d(const std::array<Array,6>& faces,Diagnostics& d) {return mass(faces,true,d);}
double solid_mass_2d(const Array& epsilon,const Array& density,const Array& dx,const Array& dy,Diagnostics& d) {
    auto one=scalar_array(a::python_float(1.));auto solid=a::subtract(one.array(),epsilon,d);
    if (solid.shape.empty()) solid.kind=Kind::numpy_scalar;
    solid=a::multiply(solid.array(),density,d);
    if (solid.shape.empty()) solid.kind=Kind::numpy_scalar;
    auto x=expanded_width(dx,1);solid=a::multiply(solid.array(),x.array(),d);
    auto y=expanded_width(dy,0);solid=a::multiply(solid.array(),y.array(),d);
    return a::sum_as_float(solid.array(),d);
}
double solid_mass_3d(const Array& epsilon,const Array& density,const Array& dx,const Array& dy,const Array& dz,Diagnostics& d) {
    const std::vector<std::size_t> shape{dx.size(),dy.size(),dz.size()};
    auto x=broadcast_width(dx,shape,0),y=broadcast_width(dy,shape,1),z=broadcast_width(dz,shape,2);
    auto volume=a::multiply(x.array(),y.array(),d);volume=a::multiply(volume.array(),z.array(),d);
    auto one=scalar_array(a::python_float(1.));auto solid=a::subtract(one.array(),epsilon,d);
    solid=a::multiply(density,solid.array(),d);solid=a::multiply(solid.array(),volume.array(),d);return a::sum_as_float(solid.array(),d);
}
double outlet_mean(const Array& plane,Diagnostics& d) {return a::mean(plane,d).value;}
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
double richardson_duty(double fine,double coarse) {return (4.*std::abs(fine)-std::abs(coarse))/3.;}
Number pressure_difference(const Number& inlet,const Number& outlet,Diagnostics& d) {return a::numpy_scalar(a::subtract(inlet,outlet,d));}
Number absolute_outlet_pressure(const Number& outlet,const Number& reference,Diagnostics& d) {return a::numpy_scalar(a::add(outlet,reference,d));}
Tensor pressure_difference_field(const Array& inlet,const Array& outlet,Diagnostics& d) {return a::subtract(inlet,outlet,d);}
double quick_duty(double inlet,double outlet,double mass_value,double cp,bool cold,Diagnostics& d) {
    const auto delta=a::subtract(a::python_float(inlet),a::python_float(outlet),d);
    const auto capacity=a::multiply(a::python_float(mass_value),a::python_float(cp),d);
    return a::multiply(a::multiply(capacity,delta,d),a::python_float(cold?-1.:1.),d).value;
}
double quick_reynolds(double rho,double velocity,double diameter,double mu,Diagnostics& d) {
    const auto flow=a::multiply(a::python_float(rho),a::absolute(a::python_float(velocity)),d);
    return a::divide(a::multiply(flow,a::python_float(diameter),d),a::python_float(mu),d).value;
}
double quick_energy_imbalance(double first,double second,Diagnostics& d) {
    const auto x=a::python_float(first),y=a::python_float(second);
    const auto numerator=a::absolute(a::subtract(x,y,d));
    auto denominator=a::absolute(x);const auto other=a::absolute(y),floor=a::python_float(1e-30);
    // Python max replaces the current value only when the next value is greater.
    if (a::less(denominator,other)) denominator=other;
    if (a::less(denominator,floor)) denominator=floor;
    return a::divide(numerator,denominator,d).value;
}
}  // namespace tpmshx::result::metrics
