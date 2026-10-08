#pragma once

#include "tpmshx/finite_volume.hpp"

#include <algorithm>
#include <cmath>

namespace tpmshx::detail {

// Current SIMPLE physical-coordinate MINMOD/SOU and deferred-diagonal bound.
// Shared by the 2D and 3D momentum implementations; no new limiter policy.
inline double limited_increment(double pm, double pc, double pp, double dm, double dp, double offset) {
    const double gm = (pc-pm)/dm, gp = (pp-pc)/dp;
    if (gm*gp <= 0.) return 0.;
    double slope = std::min(std::abs(gm), std::abs(gp));
    if (gm < 0.) slope = -slope;
    return slope*offset;
}
inline double sou_axis(double pmm, double pm, double pc, double pp, double ppp,
    bool lo_pos, bool hi_pos, bool hi_neg, bool lo_neg, double flo, double fhi,
    ArrayView<const double> widths, int index, bool staggered) {
    const int n = static_cast<int>(widths.size);
    double dm2, dm, dp, dp2, lm, lp, hm, hp;
    if (staggered) {
        dm2 = widths[std::max(index-2, 0)]; dm = widths[std::max(index-1, 0)];
        dp = widths[std::min(index, n-1)]; dp2 = widths[std::min(index+1, n-1)];
        lm = lp = .5*dm; hm = hp = .5*dp;
    } else {
        const double wm2 = widths[std::max(index-2, 0)], wm = widths[std::max(index-1, 0)];
        const double wc = widths[index], wp = widths[std::min(index+1, n-1)], wp2 = widths[std::min(index+2, n-1)];
        dm2 = .5*(wm2+wm); dm = .5*(wm+wc); dp = .5*(wc+wp); dp2 = .5*(wp+wp2);
        lm = .5*wm; lp = hm = .5*wc; hp = .5*wp;
    }
    double lo = 0., hi = 0.;
    if (flo >= 0.) { if (lo_pos) lo = limited_increment(pmm, pm, pc, dm2, dm, lm); }
    else if (lo_neg) lo = limited_increment(pm, pc, pp, dm, dp, -lp);
    if (fhi >= 0.) { if (hi_pos) hi = limited_increment(pm, pc, pp, dm, dp, hm); }
    else if (hi_neg) hi = limited_increment(pc, pp, ppp, dp, dp2, -hp);
    return flo*lo-fhi*hi;
}
inline double sou_bound(double pm, double pc, double pp, bool lo_neg, bool hi_pos,
    double flo, double fhi, ArrayView<const double> widths, int index, bool staggered) {
    const int n = static_cast<int>(widths.size);
    const double wm = widths[std::max(index-1, 0)], wc = widths[std::min(index, n-1)], wp = widths[std::min(index+1, n-1)];
    const double dm = staggered ? wm : .5*(wm+wc), dp = staggered ? wc : .5*(wc+wp);
    const double lo_distance = .5*(staggered ? wm : wc), hi_distance = .5*wc;
    if ((pc-pm)*(pp-pc) <= 0.) return 0.;
    return (hi_pos ? std::max(fhi, 0.)*hi_distance/dm : 0.)
        + (lo_neg ? std::max(-flo, 0.)*lo_distance/dp : 0.);
}

}  // namespace tpmshx::detail
