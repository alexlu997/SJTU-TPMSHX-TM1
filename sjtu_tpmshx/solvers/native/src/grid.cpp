#include "tpmshx/grid.hpp"
#include "tpmshx/ports.hpp"
#include "tpmshx/scalar_precision.hpp"
#include "tpmshx/finite_volume.hpp"
#include "contiguous_sum.hpp"
#include <algorithm>
#include <cmath>
#include <limits>
#include <sstream>
#include <string>
#include <stdexcept>
#include <utility>

namespace tpmshx::grid {
namespace {
namespace precision=tpmshx::geometry::detail;
Scalar result(double value,Scalar a,Scalar b) {
    return {value,result_precision(a,b),a.strong || b.strong?1u:0u};
}
double numpy_sum(const Values& values) {
    return 0.+tpmshx::detail::contiguous_sum({values.data(),values.size()});
}
Values cumulative(const Values& values) {
    Values edges(values.size()+1,0.);
    for (std::size_t i=0;i<values.size();++i) edges[i+1]=edges[i]+values[i];
    return edges;
}
std::int64_t round_even(double value) {
    const double magnitude=std::abs(value);
    if (!std::isfinite(value)) throw std::invalid_argument("cannot round a nonfinite grid allocation");
    if (magnitude>=static_cast<double>(std::numeric_limits<std::int64_t>::max()))
        throw std::overflow_error("grid allocation is outside int64");
    double integral=std::floor(magnitude),fraction=magnitude-integral;
    if (fraction>.5 || (fraction==.5 && std::fmod(integral,2.)!=0.)) ++integral;
    return static_cast<std::int64_t>(std::copysign(integral,value));
}
std::pair<Scalar,Scalar> window(const End& end,bool second,Scalar length,const char* label) {
    const auto center=second?end.center2:end.center;
    const auto width=second?end.width2:end.width;
    if (!center && !width) return {divide(length,weak(2.)),length};
    if (!center || !width) throw std::invalid_argument(std::string(label)+" centre and width must be set together");
    return {*center,*width};
}
std::pair<Scalar,Scalar> edges(Scalar center,Scalar width) {
    const auto half=divide(width,weak(2.));
    return {subtract(center,half),add(center,half)};
}
std::pair<Scalar,Scalar> first_edges(const End& end) {
    if (!end.center || !end.width) throw std::invalid_argument("first-cross-axis centre and width are required");
    return edges(*end.center,*end.width);
}
bool any(const Values& values) {
    return std::any_of(values.begin(),values.end(),[](double value){return value!=0.;});
}
}  // namespace

std::uint32_t result_precision(Scalar a,Scalar b) {
    return a.strong && b.strong?std::max(a.precision,b.precision):(a.strong?a.precision:(b.strong?b.precision:64));
}

Scalar checked(Scalar value) {
    precision::require_precision(value.precision);
    if (value.strong>1 || (!value.strong && value.precision!=64))
        throw std::invalid_argument("grid scalar kind is invalid");
    value.value=precision::round_scalar(value.value,value.precision);
    return value;
}
Scalar weak(double value) {return {value,64,0};}
Scalar add(Scalar a,Scalar b) {
    const auto bits=result_precision(a,b);
    const double left=precision::round_scalar(a.value,bits),right=precision::round_scalar(b.value,bits);
    const double value=bits==64?left+right:precision::round_scalar(static_cast<float>(left)+static_cast<float>(right),bits);
    return result(value,a,b);
}
Scalar subtract(Scalar a,Scalar b) {
    const auto bits=result_precision(a,b);
    const double left=precision::round_scalar(a.value,bits),right=precision::round_scalar(b.value,bits);
    const double value=bits==64?left-right:precision::round_scalar(static_cast<float>(left)-static_cast<float>(right),bits);
    return result(value,a,b);
}
Scalar multiply(Scalar a,Scalar b) {return result(precision::multiply(a.value,b.value,result_precision(a,b)),a,b);}
Scalar divide(Scalar a,Scalar b) {
    if (!a.strong && !b.strong && b.value==0.) throw std::domain_error("float division by zero");
    return result(precision::divide(a.value,b.value,result_precision(a,b)),a,b);
}
Scalar power(Scalar base,std::size_t exponent) {
    if (!base.strong || base.precision==64)
        return {std::pow(base.value,static_cast<double>(exponent)),64,base.strong};
    const float a=static_cast<float>(base.value);
    const float b=static_cast<float>(precision::round_scalar(static_cast<double>(exponent),base.precision));
    return {precision::round_scalar(std::pow(a,b),base.precision),base.precision,1};
}
bool less(Scalar a,Scalar b) {
    const auto bits=result_precision(a,b);
    return precision::round_scalar(a.value,bits)<precision::round_scalar(b.value,bits);
}

Scalars segment_lengths(const Scalars& bounds) {
    Scalars values;
    for (std::size_t i=0;i+1<bounds.size();++i) values.push_back(subtract(bounds[i+1],bounds[i]));
    return values;
}
Scalar python_sum(const Scalars& values) {
    double sum=0.,correction=0.;std::size_t i=0;
    for (;i<values.size() && !values[i].strong;++i) {
        const double x=values[i].value,next=sum+x;
        correction+=std::abs(sum)>=std::abs(x)?(sum-next)+x:(x-next)+sum;
        sum=next;
    }
    if (correction!=0. && std::isfinite(correction)) sum+=correction;
    Scalar total=weak(sum);
    for (;i<values.size();++i) total=add(total,values[i]);
    return total;
}
std::vector<std::uint8_t> aligned_filter(Scalar length,const Scalars& points) {
    const auto epsilon=multiply(length,weak(.001)),upper=subtract(length,epsilon);
    std::vector<std::uint8_t> result;
    for (auto point:points) result.push_back(less(epsilon,point) && less(point,upper));
    return result;
}
Values uniform(std::size_t count,Scalar length) {
    return Values(count,divide(length,weak(static_cast<double>(count))).value);
}
Aligned aligned(std::size_t count,const Scalars& bounds) {
    if (bounds.size()<2) throw std::invalid_argument("aligned grid input needs both domain endpoints");
    Aligned output;output.total=weak(0.);
    if (bounds.size()==2) {output.widths=uniform(count,bounds.back());return output;}
    const auto segments=bounds.size()-1;
    if (count<2*segments)
        throw std::invalid_argument("Increase N to at least "+std::to_string(2*segments)+" to align all segments");
    output.lengths=segment_lengths(bounds);output.total=python_sum(output.lengths);
    std::int64_t used=0;
    for (auto length:output.lengths) {
        const auto scaled=divide(multiply(weak(static_cast<double>(count)),length),output.total);
        output.counts.push_back(std::max<std::int64_t>(2,round_even(scaled.value)));used+=output.counts.back();
    }
    output.counts.back()+=static_cast<std::int64_t>(count)-used;
    if (output.counts.back()<2) {
        auto deficit=2-output.counts.back();output.counts.back()=2;
        while (deficit) {
            const auto largest=std::max_element(output.counts.begin(),output.counts.end()-1);
            const auto borrowed=std::min(deficit,*largest-2);
            if (!borrowed) throw std::logic_error("grid allocation cannot borrow a cell");
            *largest-=borrowed;deficit-=borrowed;
        }
    }
    Scalar position=weak(0.);output.widths.reserve(count);
    for (std::size_t i=0;i<segments;++i) {
        const auto dx=divide(subtract(bounds[i+1],bounds[i]),weak(static_cast<double>(output.counts[i])));
        for (std::int64_t j=0;j<output.counts[i]-1;++j) {output.widths.push_back(dx.value);position=add(position,dx);}
        const auto last=subtract(bounds[i+1],position);
        output.widths.push_back(last.value);position=add(position,last);
    }
    return output;
}

Values wall(Scalar width,std::size_t bulk,std::size_t layers,double first,double growth) {
    return wall(width,bulk,layers,weak(first),weak(growth));
}
Values wall(Scalar width,std::size_t bulk,std::size_t layers,Scalar first,Scalar growth) {
    Values refined;refined.reserve(layers);
    for (std::size_t i=0;i<layers;++i) refined.push_back(multiply(first,power(growth,i)).value);
    const Scalar total{2.*numpy_sum(refined),64,1};
    const auto bulk_width=subtract(width,total);
    if (bulk_width.value<=0.) {
        std::ostringstream message;message.setf(std::ios::fixed);message.precision(3);
        message<<"build_wall_refined_1d: refinement "<<multiply(total,weak(1000.)).value
               <<"mm exceeds domain width "<<multiply(width,weak(1000.)).value
               <<"mm. Reduce n_refine or first_cell.";
        throw std::invalid_argument(message.str());
    }
    Values result=refined;
    result.insert(result.end(),bulk,divide(bulk_width,weak(static_cast<double>(bulk))).value);
    result.insert(result.end(),refined.rbegin(),refined.rend());return result;
}

WallSpec wall_spec(std::size_t dimensions,std::size_t knots) {
    if (dimensions!=2 && dimensions!=3) throw std::invalid_argument("port-wall dimensions are invalid");
    const std::size_t layers=knots?4:(dimensions==2?8:4);
    return {layers,2*(layers+1)*(knots+1),knots?.2e-3:(dimensions==2?.02e-3:.02e-3*(1.+1.8)),
            knots || dimensions==2?1.8:std::pow(1.8,2.)};
}
Values cumulative_widths(ArrayView<const double> widths,std::uint32_t bits) {
    precision::require_precision(bits);
    Values edges(widths.size+1,0.);
    if (!widths.size) return edges;
    edges[1]=precision::round_scalar(widths[0],bits);
    for (std::size_t i=1;i<widths.size;++i)
        edges[i+1]=add({edges[i],bits,1},{widths[i],bits,1}).value;
    return edges;
}

Scalars port_edges(const Scalars& lengths,const std::vector<Port>& ports,std::size_t axis) {
    if (axis>=lengths.size()) throw std::invalid_argument("port axis is outside the domain");
    Scalars output;
    for (const auto& port:ports) if (port.active && static_cast<int>(axis)!=port.direction/2) {
        std::size_t cross=0;
        for (std::size_t i=0;i<axis;++i) cross+=static_cast<int>(i)!=port.direction/2;
        for (std::size_t end=0;end<2;++end) {
            const std::string label=std::string(end?"out":"in")+(cross?"_z":"");
            const auto center_width=window(port.ends[end],cross!=0,lengths[axis],label.c_str());
            const auto range=edges(center_width.first,center_width.second);
            for (auto edge:{range.first,range.second})
                if (less(multiply(lengths[axis],weak(.001)),edge) && less(edge,multiply(lengths[axis],weak(.999))))
                    output.push_back(edge);
        }
    }
    return output;
}
Values port_wall_axis(std::size_t dimensions,std::size_t count,const Scalars& bounds,
                      const Scalars& bulk_bounds,std::size_t& minimum,std::size_t axis) {
    if (bounds.size()<2 || (dimensions!=2 && dimensions!=3)) throw std::invalid_argument("port-wall dimensions are invalid");
    const auto segments=bounds.size()-1;
    const auto spec=wall_spec(dimensions,bounds.size()-2);
    const auto layers=spec.layers;minimum=spec.minimum;
    if (count<minimum) {
        const char name=static_cast<char>('x'+axis);std::ostringstream knots;
        for (std::size_t i=1;i+1<bounds.size();++i) {
            if (i>1) knots<<", ";knots<<multiply(bounds[i],weak(1000.)).value;
        }
        throw std::invalid_argument("Port/wall grid needs at least "+std::to_string(minimum)+" cells on "+name+
            " axis; got "+std::to_string(count)+". Interior port edges: "+(bounds.size()>2?knots.str():"none")+
            " mm ("+std::to_string(segments)+" segments). Increase N"+name+" to at least "+std::to_string(minimum)+
            " or check the inlet/outlet position and width on this axis.");
    }
    const auto bulk=aligned(count-2*layers*segments,bulk_bounds).widths;
    const auto cumulative_edges=cumulative(bulk);Scalar position=weak(0.);Values output;
    for (std::size_t i=0;i<segments;++i) {
        const auto lo=subtract(bounds[i],weak(1e-12)),hi=subtract(bounds[i+1],weak(1e-12));
        std::size_t n=0;
        for (std::size_t j=0;j<bulk.size();++j) n+=cumulative_edges[j]>=lo.value && cumulative_edges[j]<hi.value;
        const auto local=wall(subtract(bounds[i+1],bounds[i]),n,layers,spec.first,spec.growth);
        for (std::size_t j=0;j+1<local.size();++j) {
            output.push_back(local[j]);position=add(position,{local[j],64,1});
        }
        const auto last=subtract(bounds[i+1],position);output.push_back(last.value);position=add(position,last);
    }
    return output;
}

Scalars breaks_2d(const Scalars& lengths,const std::vector<Port>& ports,std::size_t axis) {
    if (lengths.size()!=2 || axis>1) throw std::invalid_argument("2D grid needs two domain lengths");
    Scalars result;
    for (const auto& port:ports) if (port.active && (port.direction==0 || port.direction==1?1u:0u)==axis)
        for (const auto& end:port.ends) {
            const auto pair=first_edges(end);
            if (less(multiply(lengths[axis],weak(.001)),pair.first)) result.push_back(pair.first);
            if (less(pair.second,multiply(lengths[axis],weak(.999)))) result.push_back(pair.second);
        }
    return result;
}
std::array<std::size_t,3> suggest_grid(const Scalars& lengths,Scalar diameter,std::size_t budget,
                                     std::array<std::size_t,3> minimum) {
    if (lengths.size()!=3) throw std::invalid_argument("grid suggestion needs three domain lengths");
    const auto product=[](const auto& values) {
        std::size_t result=1;
        for (auto value:values) {
            if (value && result>std::numeric_limits<std::size_t>::max()/value)
                throw std::overflow_error("grid count product is outside size_t");
            result*=value;
        }
        return result;
    };
    if (budget<product(minimum)) throw std::invalid_argument("grid budget is below the required minimum");
    std::array<std::size_t,3> counts{};
    for (std::size_t axis=0;axis<3;++axis) {
        const auto spacing=multiply(weak(axis? .5:1.),diameter);
        counts[axis]=std::max(minimum[axis],static_cast<std::size_t>(std::max<std::int64_t>(0,round_even(divide(lengths[axis],spacing).value))));
    }
    while (product(counts)>budget) {
        std::size_t axis=0;
        for (std::size_t i=1;i<3;++i)
            if (static_cast<double>(counts[i])/minimum[i]>static_cast<double>(counts[axis])/minimum[axis]) axis=i;
        counts[axis]=std::max(minimum[axis],static_cast<std::size_t>(static_cast<double>(counts[axis])*.8));
    }
    return counts;
}
std::array<std::int32_t,7> axis_map(std::int32_t direction) {
    if (direction==0 || direction==1) return {1,0,2,1,0,2,direction==1?1:0};
    if (direction==2 || direction==3) return {0,1,2,0,1,2,direction==3?1:0};
    return {0,2,1,0,2,1,direction==5?1:0};
}

Scalars rectangles(const Port& port,Scalar cross2_length) {
    Scalars output;
    for (std::size_t end=0;end<2;++end) {
        const auto first=first_edges(port.ends[end]);
        const auto second=window(port.ends[end],true,cross2_length,end?"out second-cross-axis":"in second-cross-axis");
        const auto range=edges(second.first,second.second);
        output.insert(output.end(),{first.first,first.second,range.first,range.second});
    }
    return output;
}
Values port_overlap(const Values& widths,Scalar lower,Scalar upper,bool staggered,std::uint32_t bits) {
    return tpmshx::port_overlap_1d_typed({widths.data(),widths.size()},bits,lower,upper,staggered);
}
std::array<Values,2> port_fractions(const Values& widths,Scalar lower,Scalar upper,bool uniform_profile,std::uint32_t bits) {
    auto result=tpmshx::port_fractions_1d_typed({widths.data(),widths.size()},bits,lower,upper,uniform_profile);
    return {std::move(result.first),std::move(result.second)};
}
std::array<Values,2> partial_masks(const Port& port,const Values& cross1,const Values* cross2,std::size_t n_cross2,
                                 std::uint32_t precision1,std::uint32_t precision2) {
    std::array<Values,2> first,second,output;
    for (std::size_t i=0;i<2;++i) {
        const auto range=first_edges(port.ends[i]);first[i]=port_overlap(cross1,range.first,range.second,false,precision1);
    }
    if (!any(first[0]) || !any(first[1])) throw std::invalid_argument("Inlet / outlet range (cross1) resolves to zero cells.");
    for (std::size_t i=0;i<2;++i) {
        const auto& end=port.ends[i];
        if (end.center2.has_value()!=end.width2.has_value())
            throw std::invalid_argument(std::string(i?"out":"in")+" second-cross-axis centre and width must be set together");
        if (!end.center2 || !cross2) second[i]=Values(n_cross2,1.);
        else {
            const auto range=edges(*end.center2,*end.width2);second[i]=port_overlap(*cross2,range.first,range.second,false,precision2);
            if (!any(second[i])) throw std::invalid_argument("Inlet / outlet range (cross2) resolves to zero cells.");
        }
        for (double a:first[i]) for (double b:second[i]) output[i].push_back(a*b);
    }
    return output;
}

Values continuous_centres(std::size_t count,Scalar length,const Values* widths) {
    if (!count) throw std::invalid_argument("grid counts must be positive integers");
    Values output(count);
    if (!widths) {
        const auto step=divide(length,weak(static_cast<double>(count)));
        for (std::size_t i=0;i<count;++i) output[i]=(static_cast<double>(i)+.5)*step.value;
    } else {
        if (widths->size()!=count || std::any_of(widths->begin(),widths->end(),[](double x){return !std::isfinite(x) || x<=0.;}))
            throw std::invalid_argument("cell widths must be finite, positive and cover the field domain");
        // The original np.isclose coverage gate stays in Python configuration validation.
        const auto cumulative_edges=cumulative(*widths);
        for (std::size_t i=0;i<count;++i) output[i]=.5*(cumulative_edges[i]+cumulative_edges[i+1]);
    }
    return output;
}
Values sigmoid_centres(std::size_t count,Scalar length,const Values* widths,std::uint32_t bits,std::uint32_t* output_precision) {
    if (output_precision) *output_precision=widths?result_precision({0.,bits,1},length):64;
    Values output(widths?widths->size():count);
    if (!widths) {
        if (!count) throw std::domain_error("float division by zero");
        const double start=.5/static_cast<double>(count),stop=1.-.5/static_cast<double>(count);
        if (count==1) {output[0]=start;return output;}
        const double step=(stop-start)/static_cast<double>(count-1);
        for (std::size_t i=0;i<count;++i) output[i]=static_cast<double>(i)*step+start;
        output.back()=stop;
    } else {
        const auto cumulative_edges=cumulative_widths({widths->data(),widths->size()},bits);
        for (std::size_t i=0;i<widths->size();++i)
            output[i]=divide(subtract({cumulative_edges[i+1],bits,1},divide({(*widths)[i],bits,1},weak(2.))),length).value;
    }
    return output;
}
std::array<double,2> adaptive_grid(const Scalars& lengths,Scalar diameter,Scalar alpha) {
    if (lengths.size()!=2) throw std::invalid_argument("adaptive grid needs two domain lengths");
    const auto spacing=multiply(alpha,diameter);
    std::array<double,2> result;
    for (std::size_t i=0;i<2;++i) {
        const double value=divide(lengths[i],spacing).value;
        if (!std::isfinite(value)) {result[i]=value;continue;}
        const double magnitude=std::abs(value);
        double rounded=std::floor(magnitude);
        const double fraction=magnitude-rounded;
        if (fraction>.5 || (fraction==.5 && std::fmod(rounded,2.)!=0.)) ++rounded;
        result[i]=std::max(i==0?20.:10.,std::copysign(rounded,value));
    }
    return result;
}
}  // namespace tpmshx::grid
