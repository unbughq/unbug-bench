"""Narrow writer feedback extraction shared by durable diagnosis."""
import copy
from budget import BudgetError

def refuse(label='extension_snapshot_changed'):
    raise BudgetError(label)



def writer_feedback(stage, data):
    if data is None or data['ok'] is not False: refuse()
    info = data['info']
    if stage == 'G1':
        feedback = info.get('problems')
    else:
        observation = info.get('writer_observation')
        if (not isinstance(observation, dict) or set(observation) != {'feedback', 'bench_workers'} or
                type(observation['bench_workers']) is not int or observation['bench_workers'] < 1): refuse()
        feedback = observation['feedback']
    if not isinstance(feedback, list) or not feedback or any(not isinstance(p, str) or not p for p in feedback): refuse()
    return copy.deepcopy(feedback)
