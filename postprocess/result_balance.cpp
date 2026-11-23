#include "tpmshx/result_balance.hpp"
#include "tpmshx/result_metrics.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <stdexcept>
#include <vector>

namespace tpmshx::result::balance {
namespace {
namespace a = arithmetic;

void require_mass_faces(const RawArray* faces, std::size_t dimension) {
    if (dimension != 2 && dimension != 3)
        throw std::invalid_argument("mass balance requires two or three physical axes");
    std::vector<std::size_t> shape;
    for (std::size_t axis=0; axis<dimension; ++axis) {
        const Array face(faces[axis]);
        if (face.rank() != dimension)
            throw std::invalid_argument("mass faces disagree with physical dimension");
        if (!axis) {
            shape.assign(face.raw().shape,face.raw().shape+dimension);
            if (!shape[0]) throw std::invalid_argument("mass faces require positive cells");
            --shape[0];
            for (auto size:shape) if (!size)
                throw std::invalid_argument("mass faces require positive cells");
        }
        for (std::size_t i=0; i<dimension; ++i)
            if (face.raw().shape[i] != shape[i]+(i==axis?1u:0u))
                throw std::invalid_argument("mass faces do not share a consistent cell shape");
        for (std::size_t i=0; i<face.size(); ++i) if (!std::isfinite(face.at(i)))
            throw std::invalid_argument("physical balance requires finite mass faces");
    }
}

a::Tensor plane(const Array& field, std::size_t axis, bool high) {
    const auto& raw=field.raw();
    auto shape=field.shape();
    shape.erase(shape.begin()+static_cast<std::ptrdiff_t>(axis));
    a::Tensor output(shape);
    std::vector<std::size_t> coordinates(shape.size());
    for (std::size_t i=0; i<output.size(); ++i) {
        auto remainder=i;
        for (std::size_t j=shape.size(); j>0; --j) {
            coordinates[j-1]=remainder%shape[j-1]; remainder/=shape[j-1];
        }
        std::size_t index=0, selected=0;
        for (std::size_t j=0; j<raw.rank; ++j)
            index=index*raw.shape[j]+(j==axis?(high?raw.shape[j]-1:0):coordinates[selected++]);
        output.values[i]=field.at(index);
    }
    return output;
}

Number weighted_mean(const Array& values, const Array& weights, Diagnostics& diagnostics) {
    if (values.rank()!=1 || weights.rank()!=1 || values.size()!=weights.size())
        throw std::invalid_argument("zone weights must match the selected values");
    const auto denominator=a::sum(weights,diagnostics);
    if (denominator.value==0.)
        throw NumericError(TPMSHX_RESULT_ZERO_DIVISION,"Weights sum to zero, can't be normalized");
    auto product=a::multiply(values,weights,diagnostics);
    return a::divide(a::sum(product.array(),diagnostics),denominator,diagnostics);
}
}  // namespace

NormValues norms(const RawArray& residual, Diagnostics& diagnostics) {
    const Array values(residual);
    NormValues output{};
    output.signed_sum=a::sum_as_float(values,diagnostics);
    const auto magnitude=a::absolute(values);
    output.l1=a::sum_as_float(magnitude.array(),diagnostics);
    output.cell_max=a::maximum(magnitude.array()).value;
    output.cell_count=values.size();
    return output;
}

MassValues mass(const RawArray* faces, std::size_t dimension, Diagnostics& diagnostics) {
    require_mass_faces(faces,dimension);
    std::vector<a::Tensor> outward;
    outward.reserve(dimension*2);
    for (std::size_t axis=0; axis<dimension; ++axis) {
        const Array face(faces[axis]);
        for (bool high:{false,true}) {
            auto selected=plane(face,axis,high);
            const auto sign=a::scalar(a::python_float(high?1.:-1.));
            outward.push_back(a::multiply(sign.array(),selected.array(),diagnostics));
        }
    }
    MassValues output{};
    std::vector<double> totals;
    totals.reserve(outward.size());
    for (int sign_value:{-1,1}) {
        totals.clear();
        const auto sign=a::scalar(a::python_float(sign_value));
        const auto zero_value=a::scalar(a::python_float(0.));
        for (const auto& face:outward) {
            auto signed_face=a::multiply(sign.array(),face.array(),diagnostics);
            auto positive=a::maximum(signed_face.array(),zero_value.array(),diagnostics);
            totals.push_back(a::sum_as_float(positive.array(),diagnostics));
        }
        if (sign_value<0) output.inflow=a::python_float_sum(totals);
        else output.outflow=a::python_float_sum(totals);
    }
    auto residual=a::scalar(a::python_float(0.));
    for (std::size_t axis=0; axis<dimension; ++axis) {
        auto difference=a::difference(Array(faces[axis]),axis,diagnostics);
        residual=a::add(residual.array(),difference.array(),diagnostics);
    }
    output.residual=norms(residual.raw(),diagnostics);
    output.scale=std::max(output.inflow,output.outflow);
    output.has_scale=output.scale!=0.?1u:0u;
    if (output.has_scale) {
        output.relative_net=std::abs(output.residual.signed_sum)/output.scale;
        output.relative_l1=output.residual.l1/output.scale;
    }
    for (std::size_t i=0; i<outward.size(); ++i)
        output.boundary_out[i]=a::sum_as_float(outward[i].array(),diagnostics);
    output.telescoping_error=output.residual.signed_sum-(output.outflow-output.inflow);
    return output;
}

PlaneValues plane_sums(const RawArray* planes, std::size_t count, Diagnostics& diagnostics) {
    if (count!=6) throw std::invalid_argument("heat ledger requires all six boundary planes");
    PlaneValues output{};
    std::vector<double> totals;
    totals.reserve(count);
    for (std::size_t i=0; i<count; ++i) {
        output.values[i]=a::sum_as_float(Array(planes[i]),diagnostics);
        totals.push_back(output.values[i]);
    }
    output.total=a::python_float_sum(totals);
    return output;
}

EnergyValues energy(const EnergyPhase* phases, std::size_t count, double reservoir) {
    if (count>3) throw std::invalid_argument("heat ledger has more than three phases");
    EnergyValues output{};
    std::vector<double> boundary,sources,residuals;
    boundary.reserve(count); sources.reserve(count); residuals.reserve(count);
    for (std::size_t i=0; i<count; ++i) {
        boundary.push_back(phases[i].advective_out_sum+phases[i].diffusive_out_sum);
        sources.push_back(phases[i].source_integral);
        residuals.push_back(phases[i].residual.signed_sum);
    }
    output.boundary_out=a::python_float_sum(boundary);
    output.source_integral=a::python_float_sum(sources);
    output.residual_sum=a::python_float_sum(residuals);
    output.prescribed_b_power=reservoir;
    output.scale=std::max(1.,std::abs(reservoir));
    for (double value:boundary) output.scale=std::max(output.scale,std::abs(value));
    for (double value:sources) output.scale=std::max(output.scale,std::abs(value));
    for (std::size_t i=0; i<count; ++i) {
        output.l1_relative[i]=phases[i].residual.l1/output.scale;
        output.cell_max_relative[i]=phases[i].residual.cell_max
            *static_cast<double>(phases[i].residual.cell_count)/output.scale;
    }
    output.net_external_in=output.source_integral+reservoir-output.boundary_out;
    output.telescoping_error=output.residual_sum-output.net_external_in;
    output.relative_external_imbalance=std::abs(output.net_external_in)/output.scale;
    return output;
}

std::vector<tpmshx_result_zone_temperatures_v1> zone_temperatures_2d(
    const RawArray* widths, const RawLabels& labels, const RawArray* temperatures,
    std::size_t zone_count, Diagnostics& diagnostics) {
    const Array dx(widths[0]), dy(widths[1]);
    const Labels ids(labels);
    if (widths[0].rank!=1 || widths[1].rank!=1 || labels.rank!=2 ||
        labels.shape[0]!=dx.size() || labels.shape[1]!=dy.size())
        throw std::invalid_argument("zone labels and widths must match the physical grid");
    const std::array<Array,3> phases{Array(temperatures[0]),Array(temperatures[1]),Array(temperatures[2])};
    for (const auto& phase:phases) {
        const auto& field=phase.raw();
        if (field.rank!=2 || field.shape[0]!=dx.size() || field.shape[1]!=dy.size())
            throw std::invalid_argument("zone temperatures must match the physical grid");
    }
    const auto areas=metrics::capture_area_weights(dx,dy,diagnostics);
    const auto weights=areas.array();
    std::vector<std::vector<std::size_t>> members(zone_count);
    for (std::size_t cell=0;cell<ids.size();++cell) {
        const auto label = ids.at(cell);
        if (label >= 0 && static_cast<std::size_t>(label) < zone_count)
            members[static_cast<std::size_t>(label)].push_back(cell);
    }
    std::vector<tpmshx_result_zone_temperatures_v1> rows(zone_count);
    for (std::size_t zone=0;zone<zone_count;++zone) {
        const auto& cells=members[zone];
        auto& row=rows[zone];
        row.cells=cells.size();
        if (cells.empty()) continue;
        a::Tensor selected_weights({cells.size()});
        for (std::size_t i=0;i<cells.size();++i) selected_weights.values[i]=weights.at(cells[i]);
        const auto weight_view=selected_weights.array();
        a::Tensor selected({cells.size()});
        for (std::size_t phase=0;phase<phases.size();++phase) {
            for (std::size_t i=0;i<cells.size();++i) selected.values[i]=phases[phase].at(cells[i]);
            const auto view=selected.array();
            row.mean[phase]=zone_mean(view,&weight_view,diagnostics).value;
            row.deviation[phase]=zone_std(view,&weight_view,diagnostics).value;
            if (phase<2) {
                row.minimum[phase]=zone_minimum(view).value;
                row.maximum[phase]=zone_maximum(view).value;
            }
        }
    }
    return rows;
}

Number zone_mean(const Array& values, const Array* weights, Diagnostics& diagnostics) {
    return weights?weighted_mean(values,*weights,diagnostics):a::mean(values,diagnostics);
}

Number zone_std(const Array& values, const Array* weights, Diagnostics& diagnostics) {
    if (!weights) return a::standard_deviation(values,diagnostics);
    const auto mean=a::scalar(weighted_mean(values,*weights,diagnostics));
    auto centered=a::subtract(values,mean.array(),diagnostics);
    auto squared=a::power_two(centered.array(),diagnostics);
    return a::square_root(weighted_mean(squared.array(),*weights,diagnostics),diagnostics);
}

Number zone_minimum(const Array& values) {return a::minimum(values);}
Number zone_maximum(const Array& values) {return a::maximum(values);}
Number zone_spread(const Array& values, Diagnostics& diagnostics) {
    const auto high=a::maximum(values),low=a::minimum(values);
    return a::subtract(high,low,diagnostics);
}
arithmetic::Tensor zone_power_two(const Array& values, Diagnostics& diagnostics) {
    if (values.rank()!=1) throw std::invalid_argument("zone values require a selected one-dimensional extent");
    return a::power_two(values,diagnostics);
}
arithmetic::Tensor zone_speed_from_squared(const Array& u, const Array& v, Diagnostics& diagnostics) {
    if (u.rank()!=1 || v.rank()!=1 || u.size()!=v.size())
        throw std::invalid_argument("zone velocities must share the selected one-dimensional extent");
    auto total=a::add(u,v,diagnostics);
    return a::square_root(total.array(),diagnostics);
}
double zone_cv(double deviation, double mean) {
    return deviation/std::max(mean,1.e-10);
}

}  // namespace tpmshx::result::balance
