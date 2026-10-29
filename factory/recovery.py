"""Public checkpoint recovery decisions, shared by transport adapters.

This module never authenticates archives or grants permission to resume a case.
The restart planner and key holder retain those independent checks. Policies that
intentionally differ by transport are named here instead of inferred by callers.
"""
import math
import re

# Shared with the existing Hetzner adopter. Budget caps and failed gates need a decision.
RETRY = re.compile(r"stalled|paused|timeout|zero_tokens|(claude|codex|opencode|process)_error|(provider_limit|runner_error|usage_monitor):.*|stress_review_unresolved:(interrupted_review|missing_or_malformed_report|case_changed_since_review|binding_changed)")


def crash_stop(card):
    """Public eligibility only; the worker must authenticate the restored crash record."""
    gate, detail = card.get("failed_gate"), card.get("failed_detail")
    if (not isinstance(gate, str) or not re.fullmatch(r"G(?:[1-9]|1[013-7])", gate) or
            not isinstance(detail, dict) or set(detail) != {"error"} or
            not isinstance(detail["error"], str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", detail["error"])):
        return None
    results = card.get("gate_results", {})
    if not isinstance(results, dict) or results.get(gate, detail) != detail:
        return None
    gates = card.get("gates")
    if not isinstance(gates, dict) or gates.get(gate) != "fail": return None
    return {"gate": gate, "error_type": detail["error"]}


BUDGET_STOPS = ('budget_exhausted', 'stress_review_unresolved:rounds_exhausted')
REREVIEW_STOP = 'stress_review_unresolved:missing_or_malformed_report'
REREVIEW_STOPS = (REREVIEW_STOP, 'stress_review_unresolved:interrupted_review',
                  'stress_review_unresolved:case_changed_since_review', 'stress_review_unresolved:binding_changed')


def rereview_stop(card):
    """Public eligibility only; the worker must verify the sealed attack binding/bound."""
    return (card.get('terminal_stop') in REREVIEW_STOPS and card.get('status') == 'stopped'
            and not card.get('failed_gate') and not card.get('checkpoint_error')
            and 'fail' not in (card.get('gates') or {}).values())


def legacy_freshness_coverage_gap(card):
    """The one founder-verified generation whose reviewer saw only 1 of 10 requests."""
    info = card.get('loop_freshness')
    # This immutable checkpoint predates requested-URL coverage: its approved
    # round-7 report requested ten URLs, but only one flagged row reached review.
    # Pin the generation AND its legacy receipt, never infer retry eligibility
    # merely from a verdict path or count. New reviewer-unresolved stops refuse.
    return (card.get('case') == 'case-20261024T043353Z-e15450'
                  and card.get('sha256') == '761f3e3433c8fbfae9395f5ffa0fe762c7d437eb1b0ee0259ebd0f7ee5cfa1cb'
                  and info == {'rows': 1, 'verdict_path': 'g2-confirm-1792868467249884207/verdict.json',
                               'outcome': 'unresolved'})


def pinned_version_freshness_gap(card):
    """Founder-identified canary whose SHA-valued request row discarded exclusions."""
    return (card.get('case') == 'case-20261024T085209Z-873d7f'
            and card.get('sha256') == 'cc975a034581edab8561072468512edec6437d3be8932e02882c2cb4b9cf97a8'
            and card.get('loop_freshness') == {
                'rows': 2, 'requested': 1, 'verdict_path': 'g2-confirm-1792916679897600904/verdict.json',
                'outcome': 'unresolved', 'reason': 'reviewer_unresolved'})


def expiry_freshness_stop(card):
    """Public eligibility; ensure_freshness authenticates unchanged statement and rows."""
    info, state = card.get('admission_freshness'), card.get('freshness_repair')
    if not isinstance(info, dict) or not isinstance(state, dict): return False
    reasons = info.get('invalid_evidence_reasons')
    if not isinstance(reasons, dict): return False
    expired = reasons.get('evidence_expired')
    digest = state.get('statement_sha256')
    return (card.get('terminal_stop') in ('freshness_evidence_unavailable', 'timeout')
            and info.get('outcome') == 'evidence_incomplete' and type(expired) is int and expired > 0
            and info.get('invalid_evidence_reasons') == {'evidence_expired': expired}
            and info.get('invalid_evidence') == expired and state.get('version') == 1
            and type(state.get('attempts')) is int and 0 <= state['attempts'] <= 2
            and isinstance(digest, str) and re.fullmatch(r'[0-9a-f]{64}', digest) is not None
            and card.get('statement_sha256', digest) == digest)


def freshness_retry_stop(card):
    """Retry expiry, no-verdict stops and the two verified pre-fix generations."""
    if (card.get('status') != 'stopped' or card.get('failed_gate') or card.get('checkpoint_error')
            or 'fail' in (card.get('gates') or {}).values()): return False
    if expiry_freshness_stop(card): return True
    # A completed unresolved verdict needs a ruling, not another paid review.
    # Only a review that did not complete is eligible for an automatic retry.
    if card.get('terminal_stop') == 'freshness_review_unavailable':
        info = card.get('admission_freshness')
        return (isinstance(info, dict) and info.get('outcome') == 'review_unresolved'
                and (card.get('freshness_confirmation') or {}).get('status') != 'completed')
    info = card.get('loop_freshness')
    return (card.get('terminal_stop') == 'freshness_unresolved'
            and isinstance(info, dict) and info.get('outcome') == 'unresolved'
            and (('verdict_path' in info and info['verdict_path'] is None)
                 or legacy_freshness_coverage_gap(card) or pinned_version_freshness_gap(card)))


def gate_only_continuation(card):
    """Public eligibility; the importer/runner verifies the sealed stress evidence."""
    marker = card.get('gate_continuation') or {}
    return (card.get('status') == 'stopped' and not card.get('failed_gate') and
            not card.get('checkpoint_error') and 'fail' not in (card.get('gates') or {}).values() and
            marker.get('version') == 1 and marker.get('phase') == 'final_gates' and
            type(marker.get('round')) is int and marker['round'] >= card.get('builder_rounds', 0) and
            all(isinstance(marker.get(k), str) and re.fullmatch('[0-9a-f]{64}', marker[k])
                for k in ('case_sha256', 'stress_receipt_sha256', 'report_sha256')))


def paused_rounds_exhausted(card):
    """Legacy TTL retirement can publish a pause after its round allowance is spent."""
    saved = (card.get('recovery_config') or {}).get('rounds')
    completed = card.get('builder_rounds')
    return (card.get('terminal_stop') == 'paused' and not gate_only_continuation(card) and type(saved) is int and saved > 0
            and type(completed) is int and completed >= saved)


def raised_limits(card, limit, rounds, *, explicit_budget=False, explicit_rounds=False):
    """Only an explicit economic/round decision reopens an exhausted case."""
    paused = paused_rounds_exhausted(card)
    late = str(card.get('terminal_stop', '')).startswith('late_defect_needs_ruling:')
    if not late and not paused and card.get('terminal_stop') not in (*BUDGET_STOPS, *REREVIEW_STOPS):
        return {}
    if (card.get('status') != 'stopped' or card.get('failed_gate') or card.get('checkpoint_error') or
            'fail' in (card.get('gates') or {}).values()):
        raise ValueError('a genuine failed gate cannot be restored by raising limits')
    from budget import case_spending
    spent = case_spending(card.get('continuation_budget'), card.get('models_used'))['spent_usd']
    if spent is None or not isinstance(card.get('continuation_budget'), dict):
        raise ValueError('case list-price spending is unknown')
    config = card.get('recovery_config') or {}
    old_limit = (card.get('case_budget') or {}).get('limit_usd', config.get('case_budget'))
    old_rounds = config.get('rounds', 3)
    if paused:
        old_rounds = max(old_rounds, card['builder_rounds'])
        if not explicit_rounds or rounds <= old_rounds:
            raise ValueError('exhausted paused rounds require explicit --rounds above the saved count')
    # A failed resume already published its raised limits before finding the
    # legacy report gap. Explicitly repeating that same raise authorizes retry;
    # historical raise fields alone never authorize an automatic restart.
    if card.get('terminal_stop') == REREVIEW_STOP:
        prior = card.get('budget_raised') or {}
        if (limit == old_limit and prior.get('to') == old_limit and type(prior.get('from', 0) or 0) in (int, float) and
                math.isfinite(prior.get('from') or 0) and (prior.get('from') or 0) < old_limit):
            old_limit = prior.get('from')
        prior = card.get('rounds_raised') or {}
        if rounds == old_rounds and prior.get('to') == old_rounds and type(prior.get('from')) is int and 1 <= prior['from'] < old_rounds:
            old_rounds = prior['from']
    changes = {}
    if explicit_budget and math.isfinite(limit) and limit > max(spent, old_limit or 0):
        changes['budget_raised'] = {'from': old_limit, 'to': limit, 'spent_at_raise': spent}
    if explicit_rounds and rounds > old_rounds:
        changes['rounds_raised'] = {'from': old_rounds, 'to': rounds}
    if late and 'rounds_raised' not in changes:
        raise ValueError('late defect requires a new one-round founder ruling')
    if not changes and rereview_stop(card) and math.isfinite(limit) and limit > spent:
        return {}
    if not changes or not math.isfinite(limit) or limit <= spent:
        raise ValueError('restore requires an explicit raised budget and/or rounds with remaining list-price budget')
    return changes



def explicit_pause(card):
    """TTL retirement has its own authorization; its PauseRequested is not a user pause."""
    return (card.get('terminal_stop') == 'paused' or
            (card.get('terminal_stop') != 'ttl_retired' and
             (card.get('continuation_budget') or {}).get('terminal_stop') in ('PauseRequested', 'paused')))


def recoverable_crash(card):
    crash = crash_stop(card)
    if crash and (card.get('terminal_stop') or '') in ('', 'runner_error:' + crash['error_type']):
        return crash
    return None


def limits_from_args(card, argv):
    def option(name, default):
        value = default
        for i, item in enumerate(argv):
            if item == name: value = argv[i + 1]
            elif item.startswith(name + '='): value = item.split('=', 1)[1]
        return value
    explicit = lambda name: any(item == name or item.startswith(name + '=') for item in argv)
    limit = float(option('--case-budget', 50))
    if str(card.get('terminal_stop', '')).startswith('late_defect_needs_ruling:') and not explicit('--founder-ruling-sha256'):
        raise ValueError('late defect requires a pinned founder ruling')
    return limit, raised_limits(card, limit, int(option('--rounds', 8)),
                               explicit_budget=explicit('--case-budget'), explicit_rounds=explicit('--rounds'))


def require_restart_stop(card, argv, *, admission=False):
    """Validate Boat stop eligibility; return whether an approved model cutover resumes a pause."""
    stop = card.get('terminal_stop') or ''
    _, raised = limits_from_args(card, argv)
    crash = recoverable_crash(card)
    if (card.get('status') != 'stopped' or (card.get('failed_gate') and not crash) or
            card.get('checkpoint_error') or not
            (admission or crash or raised or freshness_retry_stop(card) or RETRY.fullmatch(stop))):
        raise ValueError('stop needs a repair or budget decision')
    from free_models import approved_pause
    raised_pause = paused_rounds_exhausted(card) and 'rounds_raised' in raised
    model_cutover = stop == 'paused' and not raised_pause and approved_pause(card, argv)
    if stop == 'paused' and not (model_cutover or raised_pause or gate_only_continuation(card)):
        raise ValueError('an explicit pause requires a deliberate resume')
    return model_cutover


HOLDER_STOPS = ('codex_login_expired', 'codex_cli_not_0.162.1', 'stalled', 'provider_limit', 'timeout', 'paused',
                'ttl_retired', 'process_error', 'opencode_error', 'runner_error',
                'Budget ledger stopped', 'usage_monitor')


def require_holder_stop(card, argv, mode):
    """Holder's public stop policy, after audit/explicit gate-repair authorization.

    The holder's historic operational-stop allowance is intentionally distinct
    from automatic Boat retry. An exceptional case stop needs its original
    bounded economic, crash or review evidence. Return whether it is a rereview.
    """
    if paused_rounds_exhausted(card):
        # Do not let the operational-stop shortcut reopen an exhausted pause.
        limits_from_args(card, argv)
    if not card.get('failed_gate') and str(card.get('terminal_stop', '')).split(':', 1)[0] in HOLDER_STOPS:
        return False
    limit, raised = limits_from_args(card, argv)
    rereview = mode == 'case' and rereview_stop(card)
    freshness_retry = mode == 'case' and freshness_retry_stop(card)
    if freshness_retry:
        from budget import BudgetError, require_case_budget
        try: require_case_budget(card.get('continuation_budget') or {}, limit)
        except BudgetError as error:
            raise ValueError('exhausted or unknown case list-price budget') from error
    if mode != 'case' or not (raised or recoverable_crash(card) or rereview or freshness_retry):
        raise ValueError('no automatic recovery for failed gates or exhausted budgets')
    return rereview


def ledger_agrees(card, *, route, mode='case', model_cutover=False, rereview=False, pause_raised=False):
    """Interpret ledger/public labels without clearing or rewriting either record.

    Explicit repair, sealed audit and authenticated peer cancellation remain the
    holder's responsibility; they are not automatic reconciliation exceptions.
    """
    if route not in ('restart', 'holder'):
        raise ValueError('unknown recovery route')
    stop = (card.get('terminal_stop') or '') if route == 'restart' else card.get('terminal_stop')
    ledger = (card.get('continuation_budget') or {}).get('terminal_stop')
    if ledger in (None, 'complete', stop) or str(stop).startswith('runner_error:'):
        return True
    if route == 'restart':
        return bool(((model_cutover or ((pause_raised or gate_only_continuation(card)) and stop == 'paused')) and ledger == 'PauseRequested') or
                    (rereview_stop(card) and RETRY.fullmatch(ledger or '')))
    return bool((mode == 'review' and stop == 'time_limit' and ledger == 'timeout') or
                (stop in ('paused', 'ttl_retired') and ledger == 'PauseRequested') or
                stop in ('Budget ledger stopped: ' + str(ledger), 'usage_monitor:' + str(ledger)) or
                (stop == 'codex_cli_not_0.162.1' and ledger == 'cancelled') or
                (rereview and RETRY.fullmatch(ledger or '')))


def adopter_stop_reason(card):
    """Legacy in-place adoption never reopens failed gates, including crash cards.

    Its paid-worker pause behavior differs from the Boat coordinator's explicit
    pause policy. Keep that existing behavior until deliberately migrated.
    """
    if card.get('failed_gate'):
        return f"failed {card['failed_gate']}: needs a repair decision"
    stop = card.get('terminal_stop') or ''
    if not RETRY.fullmatch(stop):
        return f"stop {stop or 'unknown'} is not a passing one"
    return None
