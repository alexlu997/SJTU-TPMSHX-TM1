"""Read captured parameter limits without property or solver calls."""
from sjtu_tpmshx.domain.range_policy import assess_range


def evaluate_applicability(result):
    """Keep range limits separate from numerical and physical qualification."""
    evidence = result.metadata.get('applicability_evidence')
    if evidence is None:
        return dict(definition='applicability_v1', status='unavailable', within_limits=None,
                    reason='original-bound and final-state evidence was not recorded')
    if evidence['version'] != 'applicability_evidence_v1':
        raise ValueError('unsupported applicability evidence version')
    checks = {group: [assess_range(row) for row in evidence[group]] for group in ('inlet', 'final')}
    missing = []
    for required in evidence['required']:
        if not any(row['captured'] and row['side'] == required['side']
                   and tuple(row['source']) == tuple(required['source'])
                   for row in checks[required['group']]):
            missing.append(dict(required))
    if not evidence['inlet_recorded']:
        missing.append(dict(group='inlet', reason='prepared source evidence was not recorded'))
    values = [row['within_limit'] for rows in checks.values() for row in rows]
    verdict = False if False in values else None if missing or not values or None in values else True
    return dict(definition='applicability_v1',
                status='outside_limits' if verdict is False else 'unverified' if verdict is None else 'within_limits',
                within_limits=verdict, checks=checks, missing=missing,
                policy='positive original [L,U] permits [0.9L,1.1U]; hard bounds remain fixed',
                scope_notes=evidence['scope_notes'])
