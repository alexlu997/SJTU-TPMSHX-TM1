#include "tpmshx/recorded_report.hpp"
#include <cmath>
#include <iomanip>
#include <limits>
#include <locale>
#include <sstream>
#include <type_traits>

namespace tpmshx::result::stage {
namespace {
void json_string(std::ostream& out, const std::string& value) {
    out << '"';
    const char* hex = "0123456789abcdef";
    for (const auto c : value) {
        const auto byte = static_cast<unsigned char>(c);
        if (c == '"' || c == '\\') out << '\\' << c;
        else if (byte < 32) out << "\\u00" << hex[byte >> 4] << hex[byte & 15];
        else out << c;
    }
    out << '"';
}
void json_value(std::ostream& out, const Report& value) {
    std::visit([&out](const auto& item) {
        using T = std::decay_t<decltype(item)>;
        if constexpr (std::is_same_v<T, std::nullptr_t>) out << "null";
        else if constexpr (std::is_same_v<T, bool>) out << (item ? "true" : "false");
        else if constexpr (std::is_same_v<T, std::string>) json_string(out, item);
        else if constexpr (std::is_same_v<T, Report::List>) {
            out << '[';
            for (std::size_t i = 0; i < item.size(); ++i) {if (i) out << ','; json_value(out, item[i]);}
            out << ']';
        } else if constexpr (std::is_same_v<T, Report::Object>) {
            out << '{'; bool first = true;
            for (const auto& row : item) {if (!first) out << ','; first = false; json_string(out, row.first); out << ':'; json_value(out, row.second);}
            out << '}';
        } else if constexpr (std::is_same_v<T, double>) {
            if (std::isnan(item)) out << "NaN";
            else if (std::isinf(item)) out << (item > 0 ? "Infinity" : "-Infinity");
            else out << std::setprecision(std::numeric_limits<double>::max_digits10) << std::showpoint << item << std::noshowpoint;
        } else out << item;
    }, value.value);
}
}  // namespace
std::string json(const Report& value) {
    std::ostringstream out;
    out.imbue(std::locale::classic());
    json_value(out, value);
    return out.str();
}
}  // namespace tpmshx::result::stage
