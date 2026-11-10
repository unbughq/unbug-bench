"""Pure diagnosis prompt and role validation used by the durable adapter."""
import json
import diagnosis as d
import diagnosis_task as task
import model_router
from budget import BudgetError
from carry_over import digest

def contract(root):
    try:
        templates = [d._input_bytes(root / 'source/factory/prompts' / name, root).decode()
                     for name in ('diagnosis.md', 'diagnosis-repair.md')]
    except (FileNotFoundError, ValueError): raise BudgetError('diagnosis_schema_wait') from None
    return templates, digest(dict(schema=d.RESULT_SCHEMA, judgment_template=templates[0], repair_template=templates[1]))



def reviewer(c):
    roles = c.card['roles']
    names = ('writer', 'stress_tester', 'strong_calibrator', 'reviewer')
    families = []
    for name in names:
        model = roles[name]['model']
        family = model_router.family(model)
        if not family or roles[name].get('family', family) != family: raise ValueError('contradictory role')
        families.append(family)
    if len(set(families)) != len(families): raise ValueError('dependent reviewer')
    return roles['reviewer']['model'], families[-1]



def validate(c, manifest, root, raw):
    # A reviewer's result that is not JSON is an invalid result like any other, not a crash of this
    # step (json.JSONDecodeError and UnicodeDecodeError are ValueErrors).
    try: value = json.loads(raw)
    except ValueError: raise d.BudgetError('diagnosis_result_invalid') from None
    return d.validate_result(value, case=c.case_id, generation=manifest['generation'], evidence_root=root)
