"""Founder rulings shipped in the qualified source inventory."""
# Scope of the existing host restaging grant; runtime rules do not branch on it.
CASES = {'case-20261024T043353Z-e15450': 10, 'case-20261024T085209Z-873d7f': 9}
CALL_CAP = 5000
AUTHORITY = 'founder-2026-10-26'
D4_RELEASE_PIN = 'ab7f67f9367fa28cc325f3c202e1c093a963ddd26aa5e41f6d25d3843bd79eaf'


def rehearsal_waiver(decisions, source_pin, rehearsal_sha256):
    """D4 authorizes only this release's real-case restaging, never a gate PASS."""
    import hashlib
    import json
    waiver = decisions.get('D4', {})
    record = waiver.get('record', {})
    digest = hashlib.sha256(json.dumps(record, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if (waiver.get('record_sha256') != digest or record.get('decision') != 'D4' or
            record.get('authority') != 'founder-2026-10-29' or
            record.get('scope') != 'restage_real_cases' or record.get('waive_rehearsal_pass') is not True or
            source_pin != D4_RELEASE_PIN or record.get('source_manifest_sha256') != D4_RELEASE_PIN or
            record.get('rehearsal_sha256') != rehearsal_sha256 or
            record.get('cases') != CASES or not record.get('reason')):
        raise ValueError('D4 rehearsal waiver requires the exact founder-authorized release PIN and evidence')
    return record


def record(c):
    c.card['freshness_archive_ruling'] = dict(authority='founder-2026-10-28',
        decision='G2 archive check', unreachable='clear only after confirmed dead live URL and no Wayback snapshot',
        archived='review same bug and pinned version as live', unresolved='fail closed; resumable review')
    from model_runtime import factory_job
    if factory_job(c): return
    if not 0 < c.args.max_total_calls <= CALL_CAP:
        raise ValueError('D1 caps --max-total-calls at 5000 before any model/calibration attempt')
    c.card['call_cap_ruling'] = dict(authority=AUTHORITY, decision='D1',
        max_total_calls=c.args.max_total_calls,
        reason='Whole-case call cap; money caps and round limits are independent')
