"""Separate writer-fixable defects from unfinished stress validation."""


def classify(report):
    """Normalize typed lists; unknown legacy prose remains blocking (fail closed)."""
    if not isinstance(report, dict) or type(report.get('complete')) is not bool:
        return None
    blocking = report.get('blocking')
    unfinished = report.get('unfinished_validation', [])
    if any(not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values)
           for values in (blocking, unfinished)):
        return None
    defects, validation = [], list(unfinished)
    for finding in blocking:
        # This explicit legacy label described the reviewer's unfinished work.
        # Do not infer operational failure from words inside a case-defect claim.
        if finding.lstrip().lower().startswith('validation unfinished:'):
            validation.append(finding)
        else:
            defects.append(finding)
    return {**report, 'blocking': defects, 'unfinished_validation': validation}
