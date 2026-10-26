"""Small reviewed VM-side patch; never replaces gate implementations or live prompts."""

EDITS = [
    ("    families = [family(roles[r]['model']) for r in flags]",
     "    from free_models import apply as apply_free_models\n    roles = apply_free_models(c, roles)\n    families = [family(roles[r]['model']) for r in flags]"),
    ("    if 'mimo' in model.lower(): return 'xiaomi'",
     "    if 'minimax' in model.lower(): return 'minimax'\n    if 'deepseek' in model.lower(): return 'deepseek'\n    if 'mimo' in model.lower(): return 'xiaomi'"),
    ('def opencode_config():', 'def opencode_config(model=None, case=None):'),
    ('    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=path.name, delete=False) as staged:',
     '    if model in {"opencode/minimax-m3.1-flash-free", "opencode/deepseek-v4.1-flash-free"}:\n        from free_models import provider_config\n        cfg["provider"]["opencode"] = provider_config(case, model)\n        cfg["small_model"] = model\n        path = path.with_name("factory-opencode-" + model.split("/", 1)[1] + ".json")\n    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=path.name, delete=False) as staged:'),
    ('        alt = FREE_FALLBACK.get(model)',
     '        alt = None if c.card.get("model_transition") else FREE_FALLBACK.get(model)'),
    ('"OPENCODE_CONFIG": str(opencode_config()),', '"OPENCODE_CONFIG": str(opencode_config(cli_model, case=c.case_id)),'),
    ('    kept.discard("G3")',
     '    from free_models import first_resume as first_free_resume\n    c.free_transition_first = bool(a.resume and first_free_resume(c.case_id, prev_card, a))\n    if c.free_transition_first: kept.clear()  # all gates rerun after a configuration change\n    kept.discard("G3")'),
    ("                finished = old.name in ('strong_calibrator', 'easy_calibrator') and isinstance(jload(old / 'results.json'), list)",
     "                finished = not c.free_transition_first and old.name in ('strong_calibrator', 'easy_calibrator') and isinstance(jload(old / 'results.json'), list)"),
]


def patch(source):
    import ast
    import re
    def gates(text):
        return {n.name: ast.dump(n) for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and re.fullmatch(r'g\d+', n.name)}
    original_gates = gates(source)
    if 'from free_models import apply as apply_free_models' in source:
        # Upgrade the exact first deployment without touching another source seam.
        previous_route = '    if model in {"opencode/minimax-m3.1-flash-free", "opencode/deepseek-v4.1-flash-free"}:\n        cfg["provider"]["opencode"]["options"]["baseURL"] = "https://opencode.ai/inference/openai/v1"\n    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=path.name, delete=False) as staged:'
        if previous_route in source:
            if source.count(previous_route) != 1:
                raise ValueError('ambiguous previous free route')
            source = source.replace('def opencode_config(model=None):', 'def opencode_config(model=None, case=None):', 1)
            source = source.replace(previous_route, EDITS[3][1], 1)
            source = source.replace('"OPENCODE_CONFIG": str(opencode_config(model)),', '"OPENCODE_CONFIG": str(opencode_config(cli_model, case=c.case_id)),', 1)
        # Idempotence only for exactly this patch, not partially deployed code.
        if not all(new in source for old, new in EDITS):
            raise ValueError('partial or incompatible free-model patch')
        compile(source, 'run.py', 'exec')
        if gates(source) != original_gates:
            raise ValueError('route upgrade altered a gate implementation')
        return source
    for old, new in EDITS:
        if source.count(old) != 1:
            raise ValueError('VM factory source differs at model-transition seam')
        source = source.replace(old, new, 1)
    compile(source, 'run.py', 'exec')
    if gates(source) != original_gates:
        raise ValueError('model patch altered a gate implementation')
    return source
