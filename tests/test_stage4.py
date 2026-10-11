import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from theorem_gen.definitions import double_definition, register_definition, theorem_about_double
from theorem_gen.errors import RegistryError
from theorem_gen.registry import Registry, stable_identifier


class RegistryTests(unittest.TestCase):
    def test_citation_is_not_rediscovery(self):
        registry = register_definition(double_definition(), theorem_about_double())
        cited = registry.get("gen_double_zero")
        self.assertFalse(cited.discovered)
        self.assertEqual(cited.rules, ("use_definition",))
        self.assertNotIn("define", cited.rules)
        self.assertEqual(cited.dependencies, ("def_double",))
        self.assertTrue(registry.get("def_double").discovered)

    def test_missing_dependency_names_the_identifier(self):
        registry = Registry()
        with self.assertRaises(RegistryError) as caught:
            registry.add("later", kind="theorem", dependencies=("missing_lemma",))
        self.assertIn("missing dependencies: missing_lemma", str(caught.exception))

    def test_self_dependency_and_mutual_pair_are_cycles(self):
        registry = Registry()
        with self.assertRaises(RegistryError) as caught:
            registry.add("loop", kind="theorem", dependencies=("loop",))
        self.assertIn("cycle", str(caught.exception))
        with self.assertRaises(RegistryError) as caught:
            Registry().extend(
                (
                    {"identifier": "left", "kind": "theorem", "dependencies": ("right",)},
                    {"identifier": "right", "kind": "theorem", "dependencies": ("left",)},
                )
            )
        self.assertIn("cycle", str(caught.exception))

    def test_history_replays_the_graph(self):
        registry = register_definition(double_definition(), theorem_about_double())
        replayed = Registry.replay(registry.history)
        self.assertEqual(replayed.dependency_graph(), registry.dependency_graph())
        self.assertEqual(replayed.get("gen_double_zero"), registry.get("gen_double_zero"))
        self.assertEqual(replayed.cycles(), ())

    def test_dependency_may_arrive_later_in_the_same_batch(self):
        registry = Registry()
        registry.extend(
            (
                {
                    "identifier": "user",
                    "kind": "theorem",
                    "dependencies": ("earlier",),
                    "rules": ("cite",),
                    "discovered": False,
                },
                {
                    "identifier": "earlier",
                    "kind": "lemma",
                    "rules": ("primitive",),
                    "discovered": True,
                },
            )
        )
        self.assertEqual(registry.dependencies("user"), ("earlier",))
        self.assertFalse(registry.get("user").discovered)
        self.assertEqual(registry.cycles(), ())

    def test_duplicate_identifier_is_rejected(self):
        registry = Registry()
        registry.add("once", kind="lemma")
        with self.assertRaises(RegistryError) as caught:
            registry.add("once", kind="lemma")
        self.assertIn("already registered", str(caught.exception))

    def test_stable_identifier_ignores_dict_order(self):
        left = stable_identifier("thm", {"b": 1, "a": 2})
        right = stable_identifier("thm", {"a": 2, "b": 1})
        self.assertEqual(left, right)
        self.assertNotEqual(left, stable_identifier("thm", {"a": 1}))
        self.assertTrue(left.startswith("thm_"))


if __name__ == "__main__":
    unittest.main()
