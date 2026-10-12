"""The equational generator runs beside the concrete one, one theorem per batch."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent
for item in (str(ROOT), str(TESTS)):
    if item not in sys.path:
        sys.path.insert(0, item)

from learn_support import make_engine
from theorem_gen.errors import GenerationError
from theorem_gen.learn.batches import rich_items, source_for
from theorem_gen.richgen import apply_first, ac_key, generate_rich, main, rich_theorem
from theorem_gen.verify import find_lake, verify_source

PROJECT = ROOT / "lean"


def _lake() -> bool:
    try:
        find_lake(PROJECT)
    except FileNotFoundError:
        return False
    return True


class RewriteTests(unittest.TestCase):
    def test_add_zero_hits_the_leftmost_redex_only(self):
        expr = ("+", ("+", ("v", "a"), ("n", 0)), ("+", ("v", "b"), ("n", 0)))
        got = apply_first(expr, "Nat.add_zero")
        self.assertEqual(got, ("+", ("v", "a"), ("+", ("v", "b"), ("n", 0))))

    def test_add_mul_then_mul_add_expands_the_left_sum_first(self):
        expr = ("*", ("+", ("v", "a"), ("v", "b")), ("+", ("v", "c"), ("v", "d")))
        once = apply_first(expr, "Nat.add_mul")
        self.assertEqual(
            once,
            (
                "+",
                ("*", ("v", "a"), ("+", ("v", "c"), ("v", "d"))),
                ("*", ("v", "b"), ("+", ("v", "c"), ("v", "d"))),
            ),
        )
        twice = apply_first(once, "Nat.mul_add")
        self.assertEqual(
            ac_key(twice),
            ac_key(
                (
                    "+",
                    ("+", ("*", ("v", "a"), ("v", "c")), ("*", ("v", "a"), ("v", "d"))),
                    ("*", ("v", "b"), ("+", ("v", "c"), ("v", "d"))),
                )
            ),
        )

    def test_association_does_not_change_the_ac_key(self):
        left = ("+", ("+", ("v", "a"), ("v", "b")), ("v", "c"))
        right = ("+", ("v", "c"), ("+", ("v", "b"), ("v", "a")))
        self.assertEqual(ac_key(left), ac_key(right))
        self.assertNotEqual(ac_key(left), ac_key(("*", ("v", "a"), ("v", "b"))))


class GenerateRichTests(unittest.TestCase):
    def test_seed_is_stable_and_a_longer_run_extends_it(self):
        short = generate_rich(1, 4)
        longer = generate_rich(1, 6)
        self.assertEqual(short, longer[:4])
        self.assertEqual(generate_rich(1, 4), short)
        self.assertEqual([item.name for item in short], [f"rich_s1_{i:04d}" for i in range(4)])

    def test_another_seed_is_a_different_batch(self):
        self.assertNotEqual(
            [item.source for item in generate_rich(1, 2)],
            [item.source for item in generate_rich(2, 2)],
        )

    def test_zero_count_is_empty_and_a_bad_count_is_rejected(self):
        self.assertEqual(generate_rich(1, 0), ())
        with self.assertRaises(GenerationError):
            generate_rich(1, -1)

    def test_batch_covers_rearrangement_and_a_real_rewrite(self):
        theorems = generate_rich(1, 4)
        families = [item.family for item in theorems]
        self.assertEqual(families, ["ac_add", "ac_mul", "ac_mix", "rewrite"])
        self.assertTrue(all(item.depth >= 3 for item in theorems))
        sources = [item.source for item in theorems]
        self.assertEqual(len(sources), len(set(sources)))
        for item in theorems:
            self.assertNotIn("sorry", item.source)
            self.assertNotIn("import ", item.source)
            self.assertNotIn("axiom", item.source)
            self.assertNotIn(":= rfl", item.source)
            self.assertIn("ac_rfl", item.source)
            self.assertIn("(a : Nat)", item.source)
        rewrite = theorems[3]
        self.assertIn("conv =>", rewrite.source)
        self.assertIn("rw [Nat.", rewrite.source)
        self.assertGreaterEqual(rewrite.size, 7)

    def test_negative_seed_has_a_lean_name(self):
        theorem = generate_rich(-3, 1)[0]
        self.assertTrue(theorem.name.startswith("rich_sneg3_"))
        self.assertTrue(theorem.source.startswith(f"theorem {theorem.name} "))

    def test_a_late_index_is_its_own_draw(self):
        late = rich_theorem(1, 74000)
        self.assertEqual(late, rich_theorem(1, 74000))
        self.assertEqual(rich_theorem(1, 3), generate_rich(1, 4)[3])
        self.assertNotEqual(late.statement, rich_theorem(1, 0).statement)
        self.assertIn("rich_s1_74000", late.name)

    def test_cli_writes_the_same_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rich.lean"
            code = main(["--seed", "1", "--count", "2", "--out", str(path)])
            self.assertEqual(code, 0)
            text = path.read_text(encoding="utf-8")
            expected = "".join(item.source for item in generate_rich(1, 2))
            self.assertEqual(text, expected)


class QueueTests(unittest.TestCase):
    def test_rich_item_keeps_its_source_and_skips_a_seen_statement(self):
        items = rich_items(1, 3, "run-1", ())
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.provenance["origin"], "generator")
        self.assertEqual(item.provenance["generator"], "richgen")
        self.assertFalse(item.needs_roles)
        source = source_for(item)
        self.assertIn("ac_rfl", source)
        self.assertIn("conv =>", source)
        self.assertEqual(rich_items(1, 3, "run-1", {item.structural_hash}), ())

    def test_one_step_keeps_both_generators(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp, max_steps=1, batch_count=1)
            engine.bootstrap()
            engine.run_steps(1)
            rows = engine.store.list_candidates("run-1")
            generators = {json.loads(row["provenance"]).get("generator") for row in rows}
            self.assertIn("richgen", generators)
            self.assertTrue(generators - {"richgen"})
            rich = [row for row in rows if json.loads(row["provenance"]).get("generator") == "richgen"]
            self.assertEqual(len(rich), 1)
            payload = engine.store._one(
                """
                SELECT payload_json FROM queue_jobs
                WHERE run_id='run-1' AND job_type='lean_validate'
                  AND idempotency_key LIKE '%richgen%'
                """
            )
            self.assertIn("ac_rfl", json.loads(payload["payload_json"])["source"])
            roles = engine.store._one(
                """
                SELECT COUNT(*) AS n FROM queue_jobs
                WHERE run_id='run-1' AND job_type='prove_primary'
                  AND idempotency_key LIKE '%richgen%'
                """
            )
            self.assertEqual(roles["n"], 0)


@unittest.skipUnless(PROJECT.is_dir() and _lake(), "lake is not available")
class RichLeanTests(unittest.TestCase):
    def test_lean_accepts_a_batch(self):
        source = "".join(item.source + "\n" for item in generate_rich(1, 4))
        with tempfile.TemporaryDirectory() as tmp:
            report = verify_source(
                source,
                destination=Path(tmp) / "Rich.lean",
                project_dir=PROJECT,
                timeout_s=60,
            )
        self.assertEqual(report.status, "proved", report.message)


if __name__ == "__main__":
    unittest.main()
