"""Every rotation slot names, for each role, a model with a bounded route for that role.

A walled role (strong or easy calibrator) never takes a free or Go plan lane, so its model
needs a gated, capped route (model_runtime.require_bounded_models is the rule admission runs).
"""
import sys
from pathlib import Path as _TestPath

_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_ROOT / "factory"), str(_TestPath(__file__).resolve().parent)]

import json
from types import SimpleNamespace
import unittest

import model_router
import model_runtime
from token_prices import FREE_ROUTES, GO_ROUTES

TABLES = ("rotation-3writers.json", "rotation.json")


def bounded(model, role):
    return any(model_router.route_maximum(r["route"]) is not None
               and not (role in model_router.WALLED_ROLES and (r["route"] in FREE_ROUTES or r["route"] in GO_ROUTES))
               for r in model_router.routes(model))


class RotationRouteTests(unittest.TestCase):

    def test_every_slot_model_is_bounded_for_its_role(self):
        for name in TABLES:
            path = model_runtime.PROMPTS.parent / name
            if not path.is_file():
                continue
            slots = json.loads(path.read_text())["slots"]
            for slot in range(1, len(slots) + 1):
                try:
                    roles = model_runtime.rotation(slot, name)
                except ValueError:
                    continue  # a refused family (e.g. OpenAI writing) is not a runnable slot
                for role, row in roles.items():
                    with self.subTest(table=name, slot=slot, role=role, model=row["model"]):
                        self.assertTrue(bounded(row["model"], role))
                # The same check admission runs, with the default easy calibrator.
                models = {"builder": [roles["writer"]["model"]], "attacker": [roles["stress_tester"]["model"]],
                          "reviewers": [[roles["reviewer"]["model"]]],
                          "strong_calibrator": [roles["strong_calibrator"]["model"]],
                          "easy_calibrator": ["opencode/glm-5.3-flash-free"]}
                with self.subTest(table=name, slot=slot, check="require_bounded_models"):
                    model_runtime.require_bounded_models(SimpleNamespace(models=models))


if __name__ == "__main__":
    unittest.main()
