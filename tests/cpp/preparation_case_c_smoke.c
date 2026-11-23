#include "tpmshx/preparation_case_c_api.h"
#include <math.h>
#include <stdio.h>
#include <string.h>

#define CHECK(test) do { if (!(test)) { fprintf(stderr, "line %d: %s\n", __LINE__, #test); return 1; } } while (0)

static tpmshx_preparation_case_input_2d_v1 input(void) {
    tpmshx_preparation_case_input_2d_v1 value = {0};
    size_t side;
    value.abi_version = TPMSHX_PREPARATION_CASE_ABI_VERSION;
    value.struct_size = sizeof(value);
    value.length_m = .182; value.height_m = .042;
    value.requested_nx = 20; value.requested_ny = 40;
    value.topology = 1; value.cell_length_mm = 7.; value.wall_thickness_mm = .6;
    value.solid_conductivity_W_mK = 16.;
    for (side = 0; side < 2; ++side) {
        value.sides[side].velocity_m_s = 5.;
        value.sides[side].temperature_K = side ? 300. : 400.;
        value.sides[side].pressure_Pa = 101325.;
        value.sides[side].port.direction = (int32_t)side;
    }
    return value;
}
static tpmshx_preparation_2d_uniform_input_v1 flow_input(tpmshx_preparation_case_input_2d_v1 values) {
    tpmshx_preparation_2d_uniform_input_v1 source = {1, sizeof(source)};
    source.input = values;
    return source;
}
static int TPMSHX_PREPARATION_CALL cancel_event(void* context, const tpmshx_preparation_event_v1* event) {
    size_t* calls = (size_t*)context;
    if (event && event->message.size) ++*calls;
    return 1;
}

typedef struct {
    uint32_t stage[8], side[8];
    size_t count, cancel_at;
} host_checks;
static int TPMSHX_PREPARATION_CALL check_host_input(void* context, uint32_t stage, uint32_t side) {
    host_checks* checks = (host_checks*)context;
    if (checks->count < 8) {
        checks->stage[checks->count] = stage; checks->side[checks->count] = side;
    }
    ++checks->count;
    return checks->count == checks->cancel_at;
}
static int TPMSHX_PREPARATION_CALL dummy_geometry_at(void* context, uint32_t action,
    const tpmshx_preparation_geometry_key_v9* key, tpmshx_preparation_geometry_cache_v3* value, uint32_t* hit) {
    (void)context; (void)action; (void)key; (void)value; *hit = 0; return 0;
}
static int TPMSHX_PREPARATION_CALL dummy_lut(void* context, uint32_t action, uint32_t topology,
    size_t resolution, tpmshx_preparation_sigmoid_lut_view_v6* value, uint32_t* hit) {
    (void)context; (void)action; (void)topology; (void)resolution; (void)value; *hit = 0; return 0;
}

static int check_uniform(void) {
    tpmshx_preparation_2d_uniform_input_v1 source = flow_input(input()), original = source;
    tpmshx_preparation_2d_uniform_case_v1 result = {1, sizeof(result)}, before;
    tpmshx_preparation_case_failure_v2 failure = {2, sizeof(failure)};
    tpmshx_preparation_case_options_v1 options = {1, sizeof(options), 0, 0, 0.};
    tpmshx_preparation_callbacks_v1 callbacks = {1, sizeof(callbacks), NULL, 0, cancel_event};
    const tpmshx_preparation_case_2d_v1* prepared = &result.prepared;
    size_t calls = 0;
    char error[2048];
    double first_width;
    CHECK(tpmshx_preparation_abi_version_v1() == TPMSHX_PREPARATION_ABI_VERSION);
    CHECK(!tpmshx_preparation_2d_uniform_prepare_case_v1(&source, NULL, NULL, &result, &failure, error, sizeof(error)));
    CHECK(!error[0] && result.owner && prepared->nx == 36 && prepared->ny == 56);
    CHECK(!memcmp(&source, &original, sizeof(source)));
    CHECK(prepared->dx.size == prepared->nx && prepared->dy.size == prepared->ny);
    CHECK(prepared->cell_length.size == prepared->nx * prepared->ny && prepared->range_count);
    CHECK(prepared->sides[0].row_permeability.size == prepared->nx && prepared->sides[1].inlet_geometry.size == prepared->ny);
    CHECK(prepared->input.sides[0].port.inlet_width_m == 0. && prepared->sides[0].inlet.port.inlet_width_m == source.input.height_m);
    CHECK(prepared->sides[0].inlet.velocity_m_s == 5. && !result.thermal.have_side_geometry);
    CHECK(prepared->models[0].name.size == 5 && !memcmp(prepared->models[0].name.data, "fluid", 5));
    CHECK(prepared->models[2].version.size && prepared->sides[0].properties.rho > 0.);
    first_width = prepared->dx.data[0];
    source.input.length_m = 2.;
    CHECK(prepared->input.length_m == original.input.length_m && prepared->dx.data[0] == first_width);
    before = result;
    CHECK(tpmshx_preparation_2d_uniform_prepare_case_v1(&original, NULL, NULL, &result, &failure,
        (char*)prepared->models[0].name.data, 1) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(prepared->models[0].name.data, "fluid", 5));
    CHECK(!memcmp(&before, &result, sizeof(result)));
    CHECK(tpmshx_preparation_2d_uniform_prepare_case_v1(&original, NULL, NULL, &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&before, &result, sizeof(result)) && error[0]);
    tpmshx_preparation_2d_uniform_case_release_v1(&result);
    CHECK(!result.owner && !prepared->dx.data && !result.struct_size);
    tpmshx_preparation_2d_uniform_case_release_v1(&result);
    tpmshx_preparation_2d_uniform_case_release_v1(NULL);
    result.abi_version = 1; result.struct_size = sizeof(result); before = result;
    source = original; source.input.abi_version = 99;
    CHECK(tpmshx_preparation_2d_uniform_prepare_case_v1(&source, NULL, NULL, &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&before, &result, sizeof(result)));
    source = original; source.input.sides[0].port.uniform_inlet = 2;
    CHECK(tpmshx_preparation_2d_uniform_prepare_case_v1(&source, NULL, NULL, &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&before, &result, sizeof(result)));
    source = original; source.input.sides[0].port.inlet_width_m = .01;
    CHECK(tpmshx_preparation_2d_uniform_prepare_case_v1(&source, NULL, NULL, &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(strstr(error, "both be positive") && !memcmp(&before, &result, sizeof(result)));
    options.allow_extrapolation = 2;
    CHECK(tpmshx_preparation_2d_uniform_prepare_case_v1(&original, &options, NULL, &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&before, &result, sizeof(result)));
    callbacks.context = &calls;
    CHECK(tpmshx_preparation_2d_uniform_prepare_case_v1(&original, NULL, &callbacks, &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_RUNTIME);
    CHECK(calls == 1 && strstr(error, "callback failed") && !memcmp(&before, &result, sizeof(result)));
    /* Flat callback validation: validate_grid_stage requires validate_host_input, uniform rejects keyed hooks. */
    {
        tpmshx_preparation_callbacks_v1 bad = {1, sizeof(bad), NULL, 1};
        CHECK(tpmshx_preparation_2d_uniform_prepare_case_v1(&original, NULL, &bad, &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
        CHECK(!memcmp(&before, &result, sizeof(result)));
        bad.validate_grid_stage = 0; bad.geometry_cache_at = dummy_geometry_at;
        CHECK(tpmshx_preparation_2d_uniform_prepare_case_v1(&original, NULL, &bad, &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
        CHECK(!memcmp(&before, &result, sizeof(result)));
        bad.geometry_cache_at = NULL; bad.sigmoid_lut_cache = dummy_lut;
        CHECK(tpmshx_preparation_2d_uniform_prepare_case_v1(&original, NULL, &bad, &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
        CHECK(!memcmp(&before, &result, sizeof(result)));
    }
    CHECK(tpmshx_preparation_2d_uniform_prepare_case_v1(&original, NULL, NULL, &result, &failure, NULL, 0) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&before, &result, sizeof(result)));
    CHECK(tpmshx_preparation_2d_uniform_prepare_case_v1(&original, NULL, NULL, &result, &failure, (char*)&result, sizeof(result)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&before, &result, sizeof(result)));
    return 0;
}

static int check_fluids(void) {
    tpmshx_preparation_2d_uniform_input_v1 source = flow_input(input()), original;
    tpmshx_preparation_2d_uniform_case_v1 result = {1, sizeof(result)}, before;
    tpmshx_preparation_case_failure_v2 failure = {2, sizeof(failure)};
    tpmshx_preparation_case_options_v1 options = {1, sizeof(options), 0, 1, 0.};
    tpmshx_preparation_callbacks_v1 callbacks = {1, sizeof(callbacks), NULL, 0, cancel_event};
    const tpmshx_preparation_case_2d_v1* prepared = &result.prepared;
    char version[] = "saved-version", provenance[] = "saved-source", scope[] = "saved-scope";
    char error[4096];
    size_t calls = 0;
    tpmshx_preparation_case_input_2d_v1* values = &source.input;
    values->sides[0].fluid = 2; values->sides[0].pressure_Pa = 8e6;
    values->sides[0].velocity_m_s = .15;
    values->sides[1].fluid = 1; values->sides[1].velocity_m_s = .02;
    values->sco2_nu.mode = 1;
    values->sco2_nu.have_alpha[0] = values->sco2_nu.have_alpha[1] = 1;
    values->sco2_nu.alpha[0] = 1.13; values->sco2_nu.alpha[1] = 2.27;
    values->sco2_nu.parameter_version.data = version; values->sco2_nu.parameter_version.size = strlen(version);
    values->sco2_nu.source.data = provenance; values->sco2_nu.source.size = strlen(provenance);
    values->sco2_nu.applicability.data = scope; values->sco2_nu.applicability.size = strlen(scope);
    original = source;
    CHECK(!tpmshx_preparation_2d_uniform_prepare_case_v1(&source, &options, NULL, &result, &failure, error, sizeof(error)));
    CHECK(result.owner && !failure.kind && !error[0]);
    CHECK(!memcmp(&source, &original, sizeof(source)));
    CHECK(prepared->sides[0].inlet.fluid == 2 && prepared->sco2_nu.alpha[1] == 2.27);
    CHECK(prepared->sides[1].properties.rho > 900. && prepared->notice_count == 1);
    CHECK(prepared->sco2_nu.source.data != provenance);
    provenance[0] = 'X';
    CHECK(!memcmp(prepared->sco2_nu.source.data, "saved-source", strlen("saved-source")));
    before = result;
    CHECK(tpmshx_preparation_2d_uniform_prepare_case_v1(&source, &options, NULL, &result, &failure,
        (char*)prepared->sco2_nu.source.data, 1) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(prepared->sco2_nu.source.data, "saved-source", strlen("saved-source")));
    CHECK(!memcmp(&before, &result, sizeof(result)) && !failure.kind);
    CHECK(tpmshx_preparation_2d_uniform_prepare_case_v1(&source, &options, NULL, &result, &failure, error, sizeof(error)) == 1);
    CHECK(!memcmp(&before, &result, sizeof(result)) && failure.kind == 1);
    tpmshx_preparation_2d_uniform_case_release_v1(&result);
    CHECK(!result.owner && !result.struct_size && !prepared->sco2_nu.source.data);
    tpmshx_preparation_2d_uniform_case_release_v1(&result);
    result.abi_version = 1; result.struct_size = sizeof(result); before = result;
    callbacks.context = &calls;
    CHECK(tpmshx_preparation_2d_uniform_prepare_case_v1(&source, &options, &callbacks, &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_RUNTIME);
    CHECK(calls == 1 && !memcmp(&before, &result, sizeof(result)) && failure.kind == 3);
    values->sides[1].temperature_K = 450.;
    CHECK(tpmshx_preparation_2d_uniform_prepare_case_v1(&source, &options, NULL, &result, &failure, error, sizeof(error)) != 0);
    CHECK(!memcmp(&before, &result, sizeof(result)) && failure.kind == 2 && failure.side == 1 && failure.have_property);
    source = original; values->cell_length_mm = NAN;
    CHECK(tpmshx_preparation_2d_uniform_prepare_case_v1(&source, &options, NULL, &result, &failure, error, sizeof(error)) == 1);
    CHECK(!memcmp(&before, &result, sizeof(result)) && failure.kind == 1);
    source = original; values->sco2_nu.source.data = NULL;
    CHECK(tpmshx_preparation_2d_uniform_prepare_case_v1(&source, &options, NULL, &result, &failure, error, sizeof(error)) == 1);
    CHECK(!memcmp(&before, &result, sizeof(result)));
    source = original;
    CHECK(tpmshx_preparation_2d_uniform_prepare_case_v1(&source, &options, NULL, &result, &failure, (char*)&result, sizeof(result)) == 1);
    CHECK(!memcmp(&before, &result, sizeof(result)));
    CHECK(tpmshx_preparation_2d_uniform_prepare_case_v1(&source, &options, NULL, &result, NULL, error, sizeof(error)) == 1);
    CHECK(!memcmp(&before, &result, sizeof(result)));
    return 0;
}

typedef struct {
    tpmshx_preparation_inlet_cache_v3 value;
    tpmshx_preparation_range_v1 ranges[64];
    tpmshx_preparation_text_v1 sources[64][8], warnings[64];
    size_t shapes[64][2], used;
    uint32_t bounds[64];
    char text[32768];
    int valid;
} saved_cache;
typedef struct {
    tpmshx_preparation_geometry_cache_v3 geometry;
    saved_cache sides[2];
    size_t geometry_reads, geometry_writes, inlet_reads, inlet_writes;
    size_t live_ranges, cached_ranges, notices;
    int cancel_observation, invalid_observation;
    int geometry_valid, mode, cancel, publish_only;
    void* alias;
    tpmshx_preparation_range_v1 range;
    tpmshx_preparation_text_v1 source, warning;
    tpmshx_preparation_event_v1 event;
    size_t shape;
    uint32_t bounds;
} cache_checks;
static int copy_cache_text(saved_cache* target, tpmshx_preparation_text_v1* output, tpmshx_preparation_text_v1 input) {
    if (input.size > sizeof(target->text) - target->used) return 1;
    output->data = target->text + target->used; output->size = input.size;
    if (input.size) memcpy(target->text + target->used, input.data, input.size);
    target->used += input.size; return 0;
}
static int save_cache(saved_cache* target, const tpmshx_preparation_inlet_cache_v3* input) {
    size_t i, j;
    target->used = 0; target->value = *input;
    if (input->evidence.range_count > 64 || input->evidence.warning_count > 64 || input->evidence.event_count) return 1;
    target->value.evidence.ranges = target->ranges; target->value.evidence.range_bounds_list = target->bounds;
    target->value.evidence.warnings = target->warnings;
    for (i = 0; i < input->evidence.range_count; ++i) {
        const tpmshx_preparation_range_v1* from = &input->evidence.ranges[i];
        tpmshx_preparation_range_v1* to = &target->ranges[i];
        if (from->source_count > 8 || from->rank > 2) return 1;
        *to = *from; to->source = target->sources[i]; to->shape = target->shapes[i];
        target->bounds[i] = input->evidence.range_bounds_list[i];
        for (j = 0; j < from->rank; ++j) target->shapes[i][j] = from->shape[j];
        for (j = 0; j < from->source_count; ++j)
            if (copy_cache_text(target, &target->sources[i][j], from->source[j])) return 1;
        if (copy_cache_text(target, &to->side, from->side) || copy_cache_text(target, &to->stage, from->stage)
            || copy_cache_text(target, &to->layout, from->layout) || copy_cache_text(target, &to->label, from->label)
            || copy_cache_text(target, &to->quantity, from->quantity) || copy_cache_text(target, &to->unit, from->unit)) return 1;
    }
    for (i = 0; i < input->evidence.warning_count; ++i)
        if (copy_cache_text(target, &target->warnings[i], input->evidence.warnings[i])) return 1;
    target->valid = 1; return 0;
}
static int TPMSHX_PREPARATION_CALL cache_geometry(void* context, uint32_t action,
    tpmshx_preparation_geometry_cache_v3* value, uint32_t* hit) {
    cache_checks* checks = (cache_checks*)context;
    if (action) { ++checks->geometry_writes; checks->geometry = *value; checks->geometry_valid = 1; }
    else { ++checks->geometry_reads; *hit = (uint32_t)checks->geometry_valid; if (*hit) *value = checks->geometry; }
    return 0;
}
static int TPMSHX_PREPARATION_CALL cache_inlet(void* context, uint32_t action, uint32_t side,
    const tpmshx_preparation_inlet_2d_v1* inlet,
    tpmshx_preparation_inlet_cache_v3* value, uint32_t* hit) {
    cache_checks* checks = (cache_checks*)context;
    (void)inlet;
    if (checks->mode && (!checks->publish_only || action)) {
        tpmshx_preparation_flow_evidence_v3* evidence = &value->evidence;
        const tpmshx_preparation_text_v1 text = {"cache", 5};
        *value = checks->sides[side].value;
        memset(evidence, 0, sizeof(*evidence)); memset(&checks->range, 0, sizeof(checks->range));
        checks->source = checks->warning = text; checks->shape = 1; checks->bounds = 0;
        checks->range.source = &checks->source; checks->range.source_count = 1;
        checks->range.shape = &checks->shape; checks->range.rank = 1;
        checks->range.side = checks->range.stage = checks->range.layout = text;
        checks->range.label = checks->range.quantity = checks->range.unit = text;
        evidence->ranges = &checks->range; evidence->range_count = 1; evidence->range_bounds_list = &checks->bounds;
        evidence->warnings = &checks->warning; evidence->warning_count = 1;
        checks->event.kind = 1; checks->event.logger = checks->event.message = text;
        *hit = 0;
        switch (checks->mode) {
        case 1: evidence->ranges = (const tpmshx_preparation_range_v1*)checks->alias; break;
        case 2: evidence->range_bounds_list = (const uint32_t*)checks->alias; break;
        case 3: evidence->warnings = (const tpmshx_preparation_text_v1*)checks->alias; break;
        case 4: checks->range.source = (const tpmshx_preparation_text_v1*)checks->alias; break;
        case 5: checks->source.data = (const char*)checks->alias; checks->source.size = 1; break;
        case 6: checks->range.shape = (const size_t*)checks->alias; break;
        case 7: checks->range.side.data = (const char*)checks->alias; checks->range.side.size = 1; break;
        case 8: checks->range.stage.data = (const char*)checks->alias; checks->range.stage.size = 1; break;
        case 9: checks->range.layout.data = (const char*)checks->alias; checks->range.layout.size = 1; break;
        case 10: checks->range.label.data = (const char*)checks->alias; checks->range.label.size = 1; break;
        case 11: checks->range.quantity.data = (const char*)checks->alias; checks->range.quantity.size = 1; break;
        case 12: checks->range.unit.data = (const char*)checks->alias; checks->range.unit.size = 1; break;
        case 13: checks->warning.data = (const char*)checks->alias; checks->warning.size = 1; break;
        case 14: evidence->events = (const tpmshx_preparation_event_v1*)checks->alias; evidence->event_count = 1; break;
        case 15: evidence->events = &checks->event; evidence->event_count = 1; checks->event.logger.data = (const char*)checks->alias; checks->event.logger.size = 1; break;
        case 16: evidence->events = &checks->event; evidence->event_count = 1; checks->event.message.data = (const char*)checks->alias; checks->event.message.size = 1; break;
        case 17: evidence->ranges = NULL; break;
        case 18: evidence->range_count = (size_t)-1; break;
        case 19: checks->range.source = NULL; break;
        case 20: checks->source.data = NULL; break;
        case 21: checks->range.shape = NULL; break;
        case 22: evidence->ranges = (const tpmshx_preparation_range_v1*)((char*)&checks->range + 1); break;
        case 23: *hit = 2; break;
        case 24: *hit = 1; checks->range.sample.have_finite = 3; break;
        case 25: *hit = 1; checks->range.sample.have_finite = 2; break;
        case 26: *hit = 1; checks->range.sample.have_finite = 1; break;
        case 27: *hit = 1; evidence->events = &checks->event; evidence->event_count = 1; break;
        }
        return checks->cancel;
    }
    if (action) { ++checks->inlet_writes; return save_cache(&checks->sides[side], value); }
    ++checks->inlet_reads; *hit = checks->publish_only ? 0u : (uint32_t)checks->sides[side].valid;
    if (*hit) *value = checks->sides[side].value;
    return 0;
}
static int TPMSHX_PREPARATION_CALL observe_range(void* context, uint32_t cached,
    const tpmshx_preparation_range_v1* value, uint32_t bounds_list, uint32_t have_scalar, double scalar) {
    cache_checks* checks = (cache_checks*)context;
    if (!value || !value->source_count || !value->label.size || cached > 1 || bounds_list > 1
        || have_scalar > 1 || (have_scalar && !isfinite(scalar))) checks->invalid_observation = 1;
    if (cached) ++checks->cached_ranges; else ++checks->live_ranges;
    return checks->cancel_observation == 1;
}
static int TPMSHX_PREPARATION_CALL observe_notice(void* context, uint32_t kind, uint32_t side,
    double value, tpmshx_preparation_text_v1 message) {
    cache_checks* checks = (cache_checks*)context;
    if (kind > 1 || side > 1 || !isfinite(value) || (kind == 1 && !message.size)) checks->invalid_observation = 1;
    ++checks->notices;
    return checks->cancel_observation == 2;
}
static int check_cache(const tpmshx_preparation_2d_uniform_input_v1* source) {
    cache_checks checks = {0};
    tpmshx_preparation_callbacks_v1 callbacks = {1, sizeof(callbacks), &checks, 0, NULL, NULL,
        cache_geometry, cache_inlet, observe_range, observe_notice, NULL, NULL, NULL}, callbacks_before;
    tpmshx_preparation_2d_uniform_case_v1 result = {1, sizeof(result)}, before;
    tpmshx_preparation_case_failure_v2 failure = {2, sizeof(failure)}, failure_before;
    tpmshx_preparation_case_options_v1 options = {1, sizeof(options), 0, 1, 0.};
    union { double align; char data[4096]; } error, saved_error;
    double rho[2], kss; size_t counts[4], side, target; int mode, cancel, publish, status;
    CHECK(!tpmshx_preparation_2d_uniform_prepare_case_v1(source, &options, &callbacks, &result, &failure, error.data, sizeof(error.data)));
    CHECK(checks.geometry_writes == 1 && checks.inlet_writes == 2 && result.owner);
    CHECK(checks.live_ranges && checks.notices && !checks.invalid_observation);
    for (side = 0; side < 2; ++side) rho[side] = result.prepared.sides[side].properties.rho;
    kss = result.prepared.uniform_solid_conductivity;
    counts[0] = checks.geometry_reads; counts[1] = checks.geometry_writes;
    counts[2] = checks.inlet_reads; counts[3] = checks.inlet_writes;
    before = result; failure_before = failure;
    memcpy(saved_error.data, result.prepared.cell_length.data, sizeof(double));
    CHECK(tpmshx_preparation_2d_uniform_prepare_case_v1(source, &options, &callbacks, &result, &failure,
        (char*)result.prepared.cell_length.data, sizeof(double)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&result, &before, sizeof(result)) && !memcmp(&failure, &failure_before, sizeof(failure)));
    CHECK(!memcmp(saved_error.data, result.prepared.cell_length.data, sizeof(double)));
    CHECK(checks.geometry_reads == counts[0] && checks.geometry_writes == counts[1]);
    CHECK(checks.inlet_reads == counts[2] && checks.inlet_writes == counts[3]);
    tpmshx_preparation_2d_uniform_case_release_v1(&result); result.abi_version = 1; result.struct_size = sizeof(result);
    CHECK(!tpmshx_preparation_2d_uniform_prepare_case_v1(source, &options, &callbacks, &result, &failure, error.data, sizeof(error.data)));
    CHECK(checks.geometry_reads > counts[0] && checks.geometry_writes == counts[1]);
    CHECK(checks.inlet_reads == counts[2] + 2 && checks.inlet_writes == counts[3]);
    CHECK(checks.cached_ranges && !checks.invalid_observation);
    for (side = 0; side < 2; ++side) CHECK(result.prepared.sides[side].properties.rho == rho[side]);
    CHECK(result.prepared.uniform_solid_conductivity == kss);
    tpmshx_preparation_2d_uniform_case_release_v1(&result); result.abi_version = 1; result.struct_size = sizeof(result); before = result;
    for (mode = 1; mode <= 22; ++mode) for (target = 0; target < 3; ++target)
        for (cancel = 0; cancel < 2; ++cancel) for (publish = 0; publish < 2; ++publish) {
            checks.mode = mode; checks.cancel = cancel; checks.publish_only = publish;
            checks.alias = target == 0 ? (void*)&result : target == 1 ? (void*)&failure : (void*)error.data;
            memset(error.data, 'Q', sizeof(error.data)); saved_error = error; failure_before = failure;
            status = tpmshx_preparation_2d_uniform_prepare_case_v1(source, &options, &callbacks, &result, &failure, error.data, sizeof(error.data));
            CHECK(status == TPMSHX_PREPARATION_INVALID);
            CHECK(!memcmp(&result, &before, sizeof(result)) && !memcmp(&failure, &failure_before, sizeof(failure)));
            CHECK(!memcmp(&error, &saved_error, sizeof(error)));
        }
    checks.publish_only = 0; checks.cancel = 0;
    for (mode = 23; mode <= 27; ++mode) {
        checks.mode = mode;
        CHECK(tpmshx_preparation_2d_uniform_prepare_case_v1(source, &options, &callbacks, &result, &failure, error.data, sizeof(error.data)) == TPMSHX_PREPARATION_INVALID);
        CHECK(failure.kind == 1 && error.data[0] && !memcmp(&result, &before, sizeof(result)));
    }
    checks.mode = 28; checks.cancel = 1;
    CHECK(tpmshx_preparation_2d_uniform_prepare_case_v1(source, &options, &callbacks, &result, &failure, error.data, sizeof(error.data)) == TPMSHX_PREPARATION_RUNTIME);
    CHECK(failure.kind == 3 && error.data[0] && !memcmp(&result, &before, sizeof(result)));
    /* Mixing untyped and keyed cache hooks is rejected. */
    callbacks.geometry_cache_at = dummy_geometry_at;
    CHECK(tpmshx_preparation_2d_uniform_prepare_case_v1(source, &options, &callbacks, &result, &failure, error.data, sizeof(error.data)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&result, &before, sizeof(result)));
    callbacks.geometry_cache_at = NULL;
    callbacks_before = callbacks; failure_before = failure;
    CHECK(tpmshx_preparation_2d_uniform_prepare_case_v1(source, &options, &callbacks, &result, &failure,
        (char*)&callbacks.observe_notice, sizeof(callbacks.observe_notice)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&callbacks, &callbacks_before, sizeof(callbacks)) && !memcmp(&failure, &failure_before, sizeof(failure)));
    memset(error.data, 'Q', sizeof(error.data)); saved_error = error;
    CHECK(tpmshx_preparation_2d_uniform_prepare_case_v1(source, &options,
        (const tpmshx_preparation_callbacks_v1*)((const char*)&callbacks + 1), &result, &failure, error.data, sizeof(error.data)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&error, &saved_error, sizeof(error)) && !memcmp(&failure, &failure_before, sizeof(failure)));
    callbacks.geometry_cache = NULL; callbacks.inlet_cache = NULL;
    for (mode = 1; mode <= 2; ++mode) {
        size_t ranges = checks.live_ranges, notices = checks.notices;
        checks.cancel_observation = mode;
        CHECK(tpmshx_preparation_2d_uniform_prepare_case_v1(source, &options, &callbacks,
            &result, &failure, error.data, sizeof(error.data)) == TPMSHX_PREPARATION_RUNTIME);
        CHECK(failure.kind == 3 && error.data[0] && !memcmp(&result, &before, sizeof(result)));
        CHECK(mode == 1 ? checks.live_ranges == ranges + 1 : checks.notices == notices + 1);
    }
    return 0;
}

static int check_flow(void) {
    tpmshx_preparation_2d_uniform_input_v1 source = {0}, original;
    tpmshx_preparation_2d_uniform_flow_v1 query = {0}, query_before;
    tpmshx_preparation_2d_uniform_case_v1 result = {0}, before;
    tpmshx_preparation_case_failure_v2 failure = {2, sizeof(failure)}, failure_before;
    tpmshx_preparation_case_options_v1 options = {1, sizeof(options), 0, 1, 0.};
    tpmshx_preparation_callbacks_v1 callbacks = {1, sizeof(callbacks), NULL, 0, cancel_event};
    char provenance[] = "mass-source", error[4096], preserved[sizeof(provenance)];
    size_t i, calls = 0;
    double expected_speeds[2], saved_target;
    source.abi_version = query.abi_version = result.abi_version = 1;
    source.struct_size = sizeof(source); query.struct_size = sizeof(query); result.struct_size = sizeof(result);
    source.input = input();
    source.input.have_physical_depth = 1; source.input.physical_depth_m = .042;
    source.input.sides[0].velocity_m_s = -99.; source.input.sides[1].velocity_m_s = -88.;
    source.input.sides[1].fluid = 1; source.input.sides[1].pressure_Pa = 200000.;
    source.input.sco2_nu.source.data = provenance; source.input.sco2_nu.source.size = strlen(provenance);
    original = source;
    CHECK(!tpmshx_preparation_2d_uniform_capacities_v1(&source, NULL, NULL, &query, &failure, error, sizeof(error)));
    CHECK(query.owner && query.flow.have_capacities && query.flow.capacities[0] > 0. && query.flow.capacities[1] > 0.);
    CHECK(!memcmp(&source, &original, sizeof(source)));
    CHECK(query.flow.input.sco2_nu.source.data != provenance);
    source.have_explicit_targets = 1;
    source.explicit_targets_kg_s[0] = query.flow.capacities[0] * 5.;
    source.explicit_targets_kg_s[1] = query.flow.capacities[1] * .02;
    for (i = 0; i < 2; ++i) expected_speeds[i] = source.explicit_targets_kg_s[i] / query.flow.capacities[i];
    provenance[0] = 'X';
    CHECK(!memcmp(query.flow.input.sco2_nu.source.data, "mass-source", strlen("mass-source")));
    query_before = query;
    CHECK(tpmshx_preparation_2d_uniform_resolve_flow_v1(&source, NULL, NULL, &query, &failure, error, sizeof(error)) != 0);
    CHECK(!memcmp(&query_before, &query, sizeof(query)));
    tpmshx_preparation_2d_uniform_flow_release_v1(&query);
    query.abi_version = 1; query.struct_size = sizeof(query);
    CHECK(!tpmshx_preparation_2d_uniform_resolve_flow_v1(&source, NULL, NULL, &query, &failure, error, sizeof(error)));
    CHECK(query.flow.speeds[0] == expected_speeds[0] && query.flow.speeds[1] == expected_speeds[1]);
    CHECK(!query.flow.input.sides[0].have_mass_flow && !query.flow.input.sides[1].have_mass_flow);
    tpmshx_preparation_2d_uniform_flow_release_v1(&query);
    CHECK(!query.owner && !query.struct_size && !query.flow.input.sco2_nu.source.data);
    tpmshx_preparation_2d_uniform_flow_release_v1(&query); tpmshx_preparation_2d_uniform_flow_release_v1(NULL);
    CHECK(!tpmshx_preparation_2d_uniform_prepare_case_v1(&source, &options, NULL, &result, &failure, error, sizeof(error)));
    CHECK(result.owner);
    CHECK(result.prepared.sides[0].inlet.velocity_m_s == expected_speeds[0]);
    CHECK(result.prepared.sides[1].inlet.velocity_m_s == expected_speeds[1]);
    CHECK(result.flow.evidence.event_count == 1);
    before = result;
    CHECK(tpmshx_preparation_2d_uniform_prepare_case_v1(&source, &options, NULL, &result, &failure, error, sizeof(error)) != 0);
    CHECK(!memcmp(&before, &result, sizeof(result)));
    tpmshx_preparation_2d_uniform_case_release_v1(&result);
    CHECK(!result.owner && !result.prepared.dx.data);
    tpmshx_preparation_2d_uniform_case_release_v1(&result); tpmshx_preparation_2d_uniform_case_release_v1(NULL);
    result.abi_version = 1; result.struct_size = sizeof(result); before = result;
    saved_target = source.explicit_targets_kg_s[0]; source.explicit_targets_kg_s[0] = NAN;
    CHECK(tpmshx_preparation_2d_uniform_prepare_case_v1(&source, &options, NULL, &result, &failure, error, sizeof(error)) == 1);
    CHECK(failure.kind == 1 && !memcmp(&before, &result, sizeof(result)));
    source.explicit_targets_kg_s[0] = saved_target;
    {
        host_checks checks = {0};
        tpmshx_preparation_callbacks_v1 host = {1, sizeof(host), &checks, 0, NULL, check_host_input};
        tpmshx_preparation_callbacks_v1 host_before;
        CHECK(!tpmshx_preparation_2d_uniform_prepare_case_v1(&source, &options, &host, &result, &failure, error, sizeof(error)));
        CHECK(checks.count == 5 && checks.stage[0] == 1 && checks.stage[1] == 0 && checks.stage[2] == 1);
        CHECK(checks.stage[3] == 2 && checks.side[3] == 0 && checks.stage[4] == 2 && checks.side[4] == 1);
        tpmshx_preparation_2d_uniform_case_release_v1(&result);
        result.abi_version = 1; result.struct_size = sizeof(result); before = result;
        checks.count = 0; checks.cancel_at = 4;
        CHECK(tpmshx_preparation_2d_uniform_prepare_case_v1(&source, &options, &host, &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_RUNTIME);
        CHECK(checks.count == 4 && failure.kind == 3 && !memcmp(&before, &result, sizeof(result)));
        checks.count = 0; checks.cancel_at = 0; host_before = host; failure_before = failure;
        CHECK(tpmshx_preparation_2d_uniform_prepare_case_v1(&source, &options, &host, &result, &failure,
            (char*)&host.validate_host_input, sizeof(host.validate_host_input)) == TPMSHX_PREPARATION_INVALID);
        CHECK(!checks.count && !memcmp(&host, &host_before, sizeof(host)) && !memcmp(&failure, &failure_before, sizeof(failure)));
        --host.struct_size;
        CHECK(tpmshx_preparation_2d_uniform_prepare_case_v1(&source, &options, &host, &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
        CHECK(!checks.count && !memcmp(&before, &result, sizeof(result)));
        host.struct_size = sizeof(host);
        source.have_explicit_targets = 0;
        query.abi_version = 1; query.struct_size = sizeof(query);
        CHECK(!tpmshx_preparation_2d_uniform_resolve_flow_v1(&source, &options, &host, &query, &failure, error, sizeof(error)));
        CHECK(!checks.count && !query.flow.have_capacities);
        tpmshx_preparation_2d_uniform_flow_release_v1(&query);
        query.abi_version = 1; query.struct_size = sizeof(query);
        CHECK(!tpmshx_preparation_2d_uniform_capacities_v1(&source, &options, &host, &query, &failure, error, sizeof(error)));
        CHECK(checks.count == 1 && checks.stage[0] == 1 && checks.side[0] == 2);
        tpmshx_preparation_2d_uniform_flow_release_v1(&query);
        /* Verify validate_grid_stage == 1 emits (stage=3, side=2). */
        checks.count = 0; host.validate_grid_stage = 1;
        source.input.sides[0].velocity_m_s = 5.; source.input.sides[1].velocity_m_s = .02;
        CHECK(!tpmshx_preparation_2d_uniform_prepare_case_v1(&source, &options, &host, &result, &failure, error, sizeof(error)));
        CHECK(checks.count == 5 && checks.stage[2] == 3 && checks.side[2] == 2);
        tpmshx_preparation_2d_uniform_case_release_v1(&result);
        result.abi_version = 1; result.struct_size = sizeof(result); before = result;
        source.input.sides[0].velocity_m_s = -99.; source.input.sides[1].velocity_m_s = -88.;
        source.have_explicit_targets = 1;
    }
    CHECK(!check_cache(&source));
    callbacks.context = &calls;
    CHECK(tpmshx_preparation_2d_uniform_prepare_case_v1(&source, &options, &callbacks, &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_RUNTIME);
    CHECK(calls == 1 && failure.kind == 3 && !memcmp(&before, &result, sizeof(result)));
    CHECK(tpmshx_preparation_2d_uniform_prepare_case_v1(&source, &options, NULL, &result, &failure, (char*)&result, sizeof(result)) != 0);
    CHECK(!memcmp(&before, &result, sizeof(result)));
    memcpy(preserved, provenance, sizeof(provenance)); failure_before = failure;
    source.input.sco2_nu.parameter_version.data = NULL; source.input.sco2_nu.parameter_version.size = 1;
    CHECK(tpmshx_preparation_2d_uniform_prepare_case_v1(&source, &options, NULL, &result, &failure, provenance, sizeof(provenance)) != 0);
    CHECK(!memcmp(preserved, provenance, sizeof(provenance)) && !memcmp(&failure_before, &failure, sizeof(failure)));
    CHECK(!memcmp(&before, &result, sizeof(result)));
    return 0;
}

static int check_continuous(void) {
    tpmshx_preparation_2d_continuous_input_v1 source = {0};
    tpmshx_preparation_2d_continuous_flow_v1 capacity = {0}, resolved = {0};
    tpmshx_preparation_2d_continuous_case_v1 result = {0}, before;
    tpmshx_preparation_case_failure_v2 failure = {0}, failure_before;
    tpmshx_preparation_case_options_v1 options = {1, sizeof(options), 0, 1, 0.};
    tpmshx_preparation_callbacks_v1 callbacks = {1, sizeof(callbacks), NULL, 0, cancel_event};
    double decisions[] = {4.5, 6., 7.5, 5.4, .31, .42, .59, .36}, saved[8];
    char error[4096];
    size_t i, calls = 0;
    source.abi_version = 1; source.struct_size = sizeof(source);
    source.input = input(); source.input.geometry_mode = 1;
    source.input.have_physical_depth = 1; source.input.physical_depth_m = .042;
    for (i = 0; i < 2; ++i) source.input.sides[i].velocity_m_s = -99.;
    source.controls.n_ctrl_x = source.controls.n_ctrl_y = 2; source.controls.spline_order = 1;
    source.controls.L_bounds_mm[0] = 4.; source.controls.L_bounds_mm[1] = 8.;
    source.controls.t_bounds_mm[0] = .3; source.controls.t_bounds_mm[1] = .6;
    source.controls.decision_mm.data = decisions; source.controls.decision_mm.size = 8;
    capacity.abi_version = resolved.abi_version = result.abi_version = 1;
    capacity.struct_size = sizeof(capacity); resolved.struct_size = sizeof(resolved); result.struct_size = sizeof(result);
    failure.abi_version = 2; failure.struct_size = sizeof(failure);
    CHECK(!tpmshx_preparation_2d_continuous_capacities_v1(&source, &options, NULL, &capacity, &failure, error, sizeof(error)));
    CHECK(capacity.owner && capacity.flow.have_capacities);
    CHECK(capacity.controls.decision_mm.data != decisions && capacity.controls.decision_mm.size == 8);
    source.have_explicit_targets = 1;
    for (i = 0; i < 2; ++i) source.explicit_targets_kg_s[i] = capacity.flow.capacities[i] * 6.;
    CHECK(!tpmshx_preparation_2d_continuous_resolve_flow_v1(&source, &options, NULL, &resolved, &failure, error, sizeof(error)));
    {
        host_checks checks = {0};
        tpmshx_preparation_callbacks_v1 host = {1, sizeof(host), &checks, 0, NULL, check_host_input};
        CHECK(!tpmshx_preparation_2d_continuous_prepare_case_v1(&source, &options, &host, &result, &failure, error, sizeof(error)));
        CHECK(checks.count == 5 && checks.stage[0] == 1 && checks.stage[1] == 0 && checks.stage[2] == 1);
        CHECK(checks.stage[3] == 2 && checks.side[3] == 0 && checks.stage[4] == 2 && checks.side[4] == 1);
    }
    CHECK(result.owner);
    CHECK(result.design_pore_porosity.size == result.prepared.nx * result.prepared.ny);
    CHECK(result.area_density_per_m.size == result.prepared.nx * result.prepared.ny);
    CHECK(result.hydraulic_diameter_m.size == result.area_density_per_m.size);
    for (i = 0; i < 2; ++i) {
        CHECK(result.fluid_conductivity[i].size == result.area_density_per_m.size);
        CHECK(result.prepared.sides[i].permeability.size == result.area_density_per_m.size);
        CHECK(result.prepared.sides[i].inlet.velocity_m_s == resolved.flow.speeds[i]);
    }
    CHECK(result.controls.decision_mm.size == 8);
    memcpy(saved, result.controls.decision_mm.data, sizeof(saved));
    failure_before = failure; before = result;
    CHECK(tpmshx_preparation_2d_continuous_prepare_case_v1(&source, &options, NULL, &result, &failure,
        (char*)result.controls.decision_mm.data, sizeof(double)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(saved, result.controls.decision_mm.data, sizeof(saved)));
    CHECK(!memcmp(&before, &result, sizeof(result)) && !memcmp(&failure_before, &failure, sizeof(failure)));
    decisions[0] = -1.;
    CHECK(capacity.controls.decision_mm.data[0] == 4.5 && result.controls.decision_mm.data[0] == 4.5);
    tpmshx_preparation_2d_continuous_flow_release_v1(&capacity);
    tpmshx_preparation_2d_continuous_flow_release_v1(&resolved);
    tpmshx_preparation_2d_continuous_case_release_v1(&result);
    CHECK(!result.owner && !result.prepared.cell_length.data);
    tpmshx_preparation_2d_continuous_case_release_v1(&result);
    tpmshx_preparation_2d_continuous_case_release_v1(NULL);
    result.abi_version = 1; result.struct_size = sizeof(result); before = result;
    CHECK(tpmshx_preparation_2d_continuous_prepare_case_v1(&source, &options, NULL, &result, &failure, error, sizeof(error)) == 1);
    CHECK(failure.kind == 1 && !memcmp(&before, &result, sizeof(result)));
    decisions[0] = 4.5; memcpy(saved, decisions, sizeof(saved)); failure_before = failure;
    CHECK(tpmshx_preparation_2d_continuous_prepare_case_v1(&source, &options, NULL, &result, &failure, (char*)decisions, sizeof(decisions)) != 0);
    CHECK(!memcmp(saved, decisions, sizeof(saved)) && !memcmp(&before, &result, sizeof(result)));
    CHECK(!memcmp(&failure_before, &failure, sizeof(failure)));
    source.controls.decision_mm.data = (const double*)&result;
    source.controls.decision_mm.size = 1;
    CHECK(tpmshx_preparation_2d_continuous_prepare_case_v1(&source, &options, NULL, &result, &failure, error, sizeof(error)) != 0);
    CHECK(!memcmp(&before, &result, sizeof(result)) && !memcmp(&failure_before, &failure, sizeof(failure)));
    source.controls.decision_mm.data = NULL;
    CHECK(tpmshx_preparation_2d_continuous_prepare_case_v1(&source, &options, NULL, &result, &failure, error, sizeof(error)) != 0);
    CHECK(!memcmp(&before, &result, sizeof(result)));
    source.controls.decision_mm.data = decisions; source.controls.decision_mm.size = 8;
    callbacks.context = &calls;
    CHECK(tpmshx_preparation_2d_continuous_prepare_case_v1(&source, &options, &callbacks, &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_RUNTIME);
    CHECK(calls == 1 && failure.kind == 3 && !memcmp(&before, &result, sizeof(result)));
    source.controls.symmetric_y = 2;
    CHECK(tpmshx_preparation_2d_continuous_prepare_case_v1(&source, &options, NULL, &result, &failure, error, sizeof(error)) == 1);
    CHECK(!memcmp(&before, &result, sizeof(result)));
    return 0;
}

static tpmshx_preparation_2d_zoned_input_v1 zoned_input(tpmshx_preparation_zone_region_v5* regions, char* first, char* second) {
    tpmshx_preparation_2d_zoned_input_v1 source = {1, sizeof(source)};
    size_t side;
    source.input = input(); source.input.geometry_mode = 2;
    source.input.requested_nx = 8; source.input.requested_ny = 6;
    source.model.solid_conductivity_W_mK = 16.;
    for (side = 0; side < 2; ++side) {
        regions[side].cell_length_mm = side ? 6. : 7.; regions[side].wall_thickness_mm = side ? .5 : .4;
    }
    regions[0].name.data = first; regions[0].name.size = strlen(first);
    regions[1].name.data = second; regions[1].name.size = strlen(second);
    regions[0].bounds[0] = 0.; regions[0].bounds[1] = .4;
    regions[1].bounds[0] = .4; regions[1].bounds[1] = 1.;
    source.regions = regions; source.region_count = 2; source.axis = 1;
    return source;
}

static int check_zoned(void) {
    tpmshx_preparation_zone_region_v5 regions[2] = {{0}}, saved_regions[2];
    char first[] = "first", second[] = "second", error[4096];
    tpmshx_preparation_2d_zoned_input_v1 source = zoned_input(regions, first, second), original = source;
    tpmshx_preparation_2d_zoned_case_v1 result = {1, sizeof(result)}, before;
    tpmshx_preparation_2d_stripe_case_v1 stripe = {1, sizeof(stripe)};
    tpmshx_preparation_2d_zoned_flow_v1 flow = {1, sizeof(flow)};
    tpmshx_preparation_case_failure_v2 failure = {2, sizeof(failure)}, failure_before;
    tpmshx_preparation_case_options_v1 options = {1, sizeof(options), 0, 1, 0.};
    tpmshx_preparation_callbacks_v1 callbacks = {1, sizeof(callbacks), NULL, 0, cancel_event};
    tpmshx_preparation_zone_region_v5* source_regions = regions;
    size_t i, calls = 0;
    memcpy(saved_regions, regions, sizeof(regions));
    CHECK(!tpmshx_preparation_2d_zoned_prepare_case_v1(&source, &options, NULL, &result, &failure, error, sizeof(error)));
    CHECK(result.owner && !failure.kind && !error[0]);
    CHECK(!memcmp(&source, &original, sizeof(source)) && !memcmp(regions, saved_regions, sizeof(regions)));
    CHECK(result.region_count == 2 && result.cell_count == 48);
    CHECK(result.prepared.nx == 8 && result.prepared.ny == 6);
    CHECK(result.zone_id[0] == 0 && result.zone_id[5] == 1);
    CHECK(result.thermal_porosity.size == 48 && result.volumetric_transfer[1].size == 48);
    CHECK(result.design_pore_porosity.size == 48 && !result.thermal.have_side_geometry);
    CHECK(result.prepared.sides[0].row_permeability.size == 8 && !result.prepared.sides[0].permeability.size);
    first[0] = 'X'; regions[0].cell_length_mm = -1.;
    CHECK(result.regions[0].region.name.data[0] == 'f' && result.regions[0].region.cell_length_mm == 7.);
    before = result;
    CHECK(tpmshx_preparation_2d_zoned_prepare_case_v1(&source, &options, NULL, &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&before, &result, sizeof(result)));
    tpmshx_preparation_2d_zoned_case_release_v1(&result);
    CHECK(!result.owner && !result.regions && !result.zone_id && !result.struct_size);
    tpmshx_preparation_2d_zoned_case_release_v1(&result); tpmshx_preparation_2d_zoned_case_release_v1(NULL);
    first[0] = 'f'; memcpy(regions, saved_regions, sizeof(regions));
    memset(&result, 0, sizeof(result)); result.abi_version = 1; result.struct_size = sizeof(result); before = result;
    callbacks.context = &calls;
    CHECK(tpmshx_preparation_2d_zoned_prepare_case_v1(&source, &options, &callbacks, &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_RUNTIME);
    CHECK(calls == 1 && failure.kind == 3 && strstr(error, "callback failed") && !memcmp(&before, &result, sizeof(result)));
    CHECK(tpmshx_preparation_2d_zoned_prepare_case_v1(&source, &options, NULL, &result, &failure, (char*)&result, sizeof(result)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&before, &result, sizeof(result)));
    failure_before = failure;
    source.regions = (const tpmshx_preparation_zone_region_v5*)&result; source.region_count = 1;
    CHECK(tpmshx_preparation_2d_zoned_prepare_case_v1(&source, &options, NULL, &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&before, &result, sizeof(result)) && !memcmp(&failure_before, &failure, sizeof(failure)));
    source = original; source_regions[0].name.data = (const char*)&failure; source_regions[0].name.size = sizeof(failure);
    CHECK(tpmshx_preparation_2d_zoned_prepare_case_v1(&source, &options, NULL, &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&before, &result, sizeof(result)) && !memcmp(&failure_before, &failure, sizeof(failure)));
    source_regions[0].name.data = error; source_regions[0].name.size = sizeof(error); memset(error, 'R', sizeof(error));
    CHECK(tpmshx_preparation_2d_zoned_prepare_case_v1(&source, &options, NULL, &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(error[0] == 'R' && error[sizeof(error)-1] == 'R' && !memcmp(&failure_before, &failure, sizeof(failure)));
    source_regions[0].name.data = NULL; source_regions[0].name.size = 1;
    CHECK(tpmshx_preparation_2d_zoned_prepare_case_v1(&source, &options, NULL, &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&before, &result, sizeof(result)) && !memcmp(&failure_before, &failure, sizeof(failure)));
    memcpy(regions, saved_regions, sizeof(regions)); source = original;
    /* Spatial 2D rejects untyped cache hooks and invalid callback abi_version. */
    callbacks.abi_version = 2;
    CHECK(tpmshx_preparation_2d_zoned_prepare_case_v1(&source, &options, &callbacks, &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&before, &result, sizeof(result)));
    callbacks.abi_version = 1; callbacks.event = NULL; callbacks.geometry_cache = cache_geometry;
    CHECK(tpmshx_preparation_2d_zoned_prepare_case_v1(&source, &options, &callbacks, &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&before, &result, sizeof(result)));
    /* Capacity, explicit-target resolution and the stripe result use the same zoned input. */
    source.input.have_physical_depth = 1;
    source.input.physical_depth_m = .042;
    CHECK(!tpmshx_preparation_2d_zoned_capacities_v1(&source, &options, NULL, &flow, &failure, error, sizeof(error)));
    CHECK(flow.owner && flow.flow.have_capacities && flow.region_count == 2);
    source.have_explicit_targets = 1;
    for (i = 0; i < 2; ++i) source.explicit_targets_kg_s[i] = flow.flow.capacities[i] * 5.;
    tpmshx_preparation_2d_zoned_flow_release_v1(&flow); CHECK(!flow.owner && !flow.struct_size);
    flow.abi_version = 1; flow.struct_size = sizeof(flow);
    CHECK(!tpmshx_preparation_2d_zoned_resolve_flow_v1(&source, &options, NULL, &flow, &failure, error, sizeof(error)));
    CHECK(!tpmshx_preparation_2d_stripe_prepare_case_v1(&source, &options, NULL, &stripe, &failure, error, sizeof(error)));
    CHECK(stripe.owner && stripe.region_hydraulic_radii_m.size == 2);
    for (i = 0; i < 2; ++i) {
        CHECK(stripe.prepared.sides[i].inlet.velocity_m_s == flow.flow.speeds[i]);
        CHECK(isfinite(stripe.region_hydraulic_radii_m.data[i]) && stripe.region_hydraulic_radii_m.data[i] > 0.);
    }
    tpmshx_preparation_2d_stripe_case_release_v1(&stripe);
    CHECK(!stripe.owner && !stripe.struct_size);
    tpmshx_preparation_2d_stripe_case_release_v1(&stripe); tpmshx_preparation_2d_stripe_case_release_v1(NULL);
    tpmshx_preparation_2d_zoned_flow_release_v1(&flow); tpmshx_preparation_2d_zoned_flow_release_v1(NULL);
    stripe.abi_version = 1; stripe.struct_size = sizeof(stripe);
    source.kind = 1;
    CHECK(tpmshx_preparation_2d_stripe_prepare_case_v1(&source, &options, NULL, &stripe, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(strstr(error, "stripe regions") && !stripe.owner);
    return 0;
}

static int check_sigmoid(void) {
    tpmshx_preparation_sigmoid_lut_v7 lut = {0}, lut_before;
    tpmshx_preparation_2d_sigmoid_input_v1 source = {1, sizeof(source)};
    tpmshx_preparation_2d_sigmoid_case_v1 result = {1, sizeof(result)}, before;
    tpmshx_preparation_zone_region_v5 region = {0};
    tpmshx_preparation_case_failure_v2 failure = {2, sizeof(failure)}, failure_before;
    tpmshx_preparation_case_options_v1 options = {1, sizeof(options), 0, 1, 0.};
    double decisions[36]; char error[4096]; size_t i;
    lut.abi_version = 1; lut.struct_size = sizeof(lut);
    source.input = input(); source.input.geometry_mode = 2;
    source.input.requested_nx = 8; source.input.requested_ny = 6;
    source.model.solid_conductivity_W_mK = 16.;
    for (i = 0; i < 4; ++i) region.bounds[i] = i % 2 ? 1. : 0.;
    region.cell_length_mm = 7.; region.wall_thickness_mm = .4;
    source.kind = source.axis = 1; source.regions = &region; source.region_count = 1;
    for (i = 0; i < 18; ++i) {decisions[2*i] = 7.; decisions[2*i+1] = .4;}
    source.controls.decision_mm.data = decisions; source.controls.decision_mm.size = 36;
    source.controls.inlet_transition = source.controls.outlet_transition = .2;
    CHECK(!tpmshx_preparation_sigmoid_lut_create_v7(1, 2, 2, 16, &lut, error, sizeof(error)));
    CHECK(lut.owner && lut.porosity.size == 4 && lut.porosity_fast == 1);
    lut_before = lut;
    {
        const double cell = lut.cell_mm.data[0];
        const unsigned char* bytes = (const unsigned char*)lut.cell_mm.data;
        size_t offset = 0;
        while (offset < sizeof(cell) && !bytes[offset]) ++offset;
        CHECK(offset < sizeof(cell));
        CHECK(tpmshx_preparation_sigmoid_lut_create_v7(1, 2, 2, 16, &lut,
            (char*)lut.cell_mm.data + offset, 1) == TPMSHX_PREPARATION_INVALID);
        CHECK(!memcmp(&cell, lut.cell_mm.data, sizeof(cell)));
        CHECK(!memcmp(&lut, &lut_before, sizeof(lut)));
    }
    CHECK(tpmshx_preparation_sigmoid_lut_create_v7(1, 2, 2, 16, &lut, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&lut, &lut_before, sizeof(lut)));
    source.lut.cell_mm = lut.cell_mm; source.lut.wall_mm = lut.wall_mm;
    source.lut.porosity = lut.porosity; source.lut.area_density_per_m = lut.area_density_per_m;
    source.lut.porosity_fast = lut.porosity_fast; source.lut.area_fast = lut.area_fast;
    CHECK(!tpmshx_preparation_2d_sigmoid_prepare_case_v1(&source, &options, NULL, &result, &failure, error, sizeof(error)));
    CHECK(result.owner);
    CHECK(result.kind == 2 && !result.region_count && result.cell_count == 48);
    CHECK(result.controls.decision_mm.size == 36 && result.thermal_porosity.size == 48);
    CHECK(result.design_pore_porosity.size == 48);
    tpmshx_preparation_sigmoid_lut_release_v7(&lut);
    CHECK(!lut.owner && !lut.porosity.data);
    decisions[0] = -1.; CHECK(result.controls.decision_mm.data[0] == 7.);
    CHECK(isfinite(result.volumetric_transfer[0].data[0]));
    tpmshx_preparation_2d_sigmoid_case_release_v1(&result);
    CHECK(!result.owner && !result.zone_id && !result.controls.decision_mm.data);
    tpmshx_preparation_2d_sigmoid_case_release_v1(&result); tpmshx_preparation_2d_sigmoid_case_release_v1(NULL);
    tpmshx_preparation_sigmoid_lut_release_v7(&lut); tpmshx_preparation_sigmoid_lut_release_v7(NULL);
    result.abi_version = 1; result.struct_size = sizeof(result); before = result; failure_before = failure;
    source.lut.cell_mm.data = (const double*)&result; source.lut.cell_mm.size = 1;
    CHECK(tpmshx_preparation_2d_sigmoid_prepare_case_v1(&source, &options, NULL, &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&before, &result, sizeof(result)) && !memcmp(&failure_before, &failure, sizeof(failure)));
    CHECK(tpmshx_preparation_sigmoid_lut_create_v7(1, 2, 2, 16, &lut, (char*)&lut, sizeof(lut)) == TPMSHX_PREPARATION_INVALID);
    return 0;
}

static int check_offset(void) {
    tpmshx_preparation_2d_uniform_input_v1 source = {0}, original;
    tpmshx_preparation_2d_uniform_case_v1 result = {1, sizeof(result)}, before;
    tpmshx_preparation_2d_zoned_input_v1 zoned = {99, sizeof(zoned)};
    tpmshx_preparation_2d_sigmoid_input_v1 sigmoid = {99, sizeof(sigmoid)};
    tpmshx_preparation_2d_zoned_case_v1 zoned_case = {1, sizeof(zoned_case)}, zoned_before;
    tpmshx_preparation_2d_sigmoid_case_v1 sigmoid_case = {1, sizeof(sigmoid_case)}, sigmoid_before;
    tpmshx_preparation_2d_zoned_flow_v1 zoned_flow = {1, sizeof(zoned_flow)}, zoned_flow_before;
    tpmshx_preparation_2d_sigmoid_flow_v1 sigmoid_flow = {1, sizeof(sigmoid_flow)}, sigmoid_flow_before;
    tpmshx_preparation_case_failure_v2 failure = {2, sizeof(failure)};
    tpmshx_preparation_case_options_v1 options = {1, sizeof(options), 0, 1, 0.};
    char error[4096]; size_t side, column;
    source.abi_version = 1; source.struct_size = sizeof(source);
    source.input = input(); source.input.delta_levelset = .1;
    source.input.requested_nx = 8; source.input.requested_ny = 6;
    original = source;
    CHECK(!tpmshx_preparation_2d_uniform_prepare_case_v1(&source, &options, NULL, &result, &failure, error, sizeof(error)));
    CHECK(result.owner);
    CHECK(result.thermal.have_side_geometry && result.prepared.input.delta_levelset == .1);
    CHECK(result.prepared.split_a > 0. && result.prepared.split_a < 1.);
    CHECK(!memcmp(&source, &original, sizeof(source)));
    for (side = 0; side < 2; ++side)
        for (column = 0; column < 4; ++column)
            CHECK(isfinite(result.thermal.side_geometry[side][column]) && result.thermal.side_geometry[side][column] > 0.);
    before = result;
    CHECK(tpmshx_preparation_2d_uniform_prepare_case_v1(&source, &options, NULL, &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&result, &before, sizeof(result)));
    tpmshx_preparation_2d_uniform_case_release_v1(&result);
    CHECK(!result.owner && !result.struct_size && !result.prepared.dx.data && !result.thermal.have_side_geometry);
    tpmshx_preparation_2d_uniform_case_release_v1(&result);
    tpmshx_preparation_2d_uniform_case_release_v1(NULL);

    zoned_before = zoned_case; sigmoid_before = sigmoid_case;
    CHECK(tpmshx_preparation_2d_zoned_prepare_case_v1(&zoned, NULL, NULL, &zoned_case, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&zoned_case, &zoned_before, sizeof(zoned_case)));
    CHECK(tpmshx_preparation_2d_sigmoid_prepare_case_v1(&sigmoid, NULL, NULL, &sigmoid_case, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&sigmoid_case, &sigmoid_before, sizeof(sigmoid_case)));
    zoned_flow_before = zoned_flow; sigmoid_flow_before = sigmoid_flow;
    CHECK(tpmshx_preparation_2d_zoned_capacities_v1(&zoned, NULL, NULL, &zoned_flow, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(strstr(error, "ABI version"));
    CHECK(tpmshx_preparation_2d_zoned_resolve_flow_v1(&zoned, NULL, NULL, &zoned_flow, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&zoned_flow, &zoned_flow_before, sizeof(zoned_flow)));
    CHECK(tpmshx_preparation_2d_sigmoid_capacities_v1(&sigmoid, NULL, NULL, &sigmoid_flow, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(tpmshx_preparation_2d_sigmoid_resolve_flow_v1(&sigmoid, NULL, NULL, &sigmoid_flow, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&sigmoid_flow, &sigmoid_flow_before, sizeof(sigmoid_flow)));
    tpmshx_preparation_2d_zoned_case_release_v1(&zoned_case);
    tpmshx_preparation_2d_sigmoid_case_release_v1(&sigmoid_case);
    CHECK(!zoned_case.struct_size && !sigmoid_case.struct_size);
    tpmshx_preparation_2d_zoned_case_release_v1(NULL);
    tpmshx_preparation_2d_sigmoid_case_release_v1(NULL);
    tpmshx_preparation_2d_zoned_flow_release_v1(&zoned_flow);
    tpmshx_preparation_2d_sigmoid_flow_release_v1(&sigmoid_flow);
    return 0;
}

static int check_inlet_query(void) {
    tpmshx_preparation_inlet_query_input_v1 source = {0}, original;
    tpmshx_preparation_inlet_query_result_v1 result = {1, sizeof(result)}, before;
    tpmshx_preparation_case_failure_v2 failure = {2, sizeof(failure)};
    tpmshx_preparation_callbacks_v1 callbacks = {0};
    host_checks checks = {0};
    char error[4096]; size_t i;
    source.abi_version = 1; source.struct_size = sizeof(source);
    source.inlet.geometry.topology = 1;
    source.inlet.geometry.cell_length_mm = 7.; source.inlet.geometry.wall_thickness_mm = .5;
    source.inlet.velocity_m_s = 6.; source.inlet.temperature_K = 380.; source.inlet.pressure_Pa = 160000.;
    source.hydraulic_diameter_m = .002; source.epsilon_a = .4;
    original = source;
    CHECK(!tpmshx_query_inlet_properties_v2(&source, NULL, &result, &failure, error, sizeof(error)));
    CHECK(!error[0] && !failure.kind && !memcmp(&source, &original, sizeof(source)));
    for (i = 0; i < 12; ++i)
        CHECK(isfinite(result.values[i]));
    CHECK(result.values[0] > 0. && result.values[7] > 0.);
    /* A negative base with a fractional exponent gives NaN with an FP event. */
    source.inlet.velocity_m_s = -.2;
    CHECK(!tpmshx_query_inlet_properties_v2(&source, NULL, &result, &failure, error, sizeof(error)));
    CHECK(isnan(result.values[6]) && isnan(result.values[10]));
    CHECK(!failure.kind && !failure.have_property && !error[0]);
    before = result; source = original; source.abi_version = 99;
    CHECK(tpmshx_query_inlet_properties_v2(&source, NULL, &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&result, &before, sizeof(result)));
    source = original; checks.cancel_at = 1;
    callbacks.abi_version = 1; callbacks.struct_size = sizeof(callbacks);
    callbacks.context = &checks; callbacks.validate_host_input = check_host_input;
    CHECK(tpmshx_query_inlet_properties_v2(&source, &callbacks, &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_RUNTIME);
    CHECK(checks.count == 1 && checks.stage[0] == 4 && checks.side[0] == 0);
    CHECK(!memcmp(&result, &before, sizeof(result)) && !memcmp(&source, &original, sizeof(source)));
    /* Inlet query rejects validate_grid_stage != 0 and any cache hook. */
    callbacks.validate_grid_stage = 1;
    CHECK(tpmshx_query_inlet_properties_v2(&source, &callbacks, &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&result, &before, sizeof(result)));
    callbacks.validate_grid_stage = 0; callbacks.geometry_cache_at = dummy_geometry_at;
    CHECK(tpmshx_query_inlet_properties_v2(&source, &callbacks, &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&result, &before, sizeof(result)));
    callbacks.geometry_cache_at = NULL; callbacks.geometry_cache = cache_geometry;
    CHECK(tpmshx_query_inlet_properties_v2(&source, &callbacks, &result, &failure, error, sizeof(error)) == TPMSHX_PREPARATION_INVALID);
    CHECK(!memcmp(&result, &before, sizeof(result)));
    return 0;
}

int main(void) {
    CHECK(!check_uniform());
    CHECK(!check_fluids());
    CHECK(!check_flow());
    CHECK(!check_continuous());
    CHECK(!check_zoned());
    CHECK(!check_sigmoid());
    CHECK(!check_offset());
    return check_inlet_query();
}
