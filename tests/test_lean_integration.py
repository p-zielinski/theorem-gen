import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from theorem_gen.__main__ import main
from theorem_gen.config import GeneratorConfig
from theorem_gen.definitions import (
    double_definition,
    supporting_definitions,
    theorem_about_double,
)
from theorem_gen.explore import explore, theorem_from_proved
from theorem_gen.export_lean import export_library, export_module
from theorem_gen.expr import Atom, BinOp, Compare, Forall, IntLit, NatLit, UnaryOp, Var
from theorem_gen.general import GENERAL_RULES, generate_general
from theorem_gen.generate import generate
from theorem_gen.theorem import Metadata, Proof, Theorem, claimed_true
from theorem_gen.verify import build_lean_env, find_lake, verify_source, verify_theorems

PROJECT = ROOT / "lean"
EXAMPLE = PROJECT / "TheoremGen" / "Generated.lean"
EXAMPLE_CONFIG = GeneratorConfig(seed=1, count=8)


def lake_available():
    if not PROJECT.is_dir():
        return False
    try:
        find_lake(PROJECT)
    except FileNotFoundError:
        return False
    return True


@unittest.skipUnless(lake_available(), "lake is not installed or lean/ is missing")
class LeanIntegrationTests(unittest.TestCase):
    def test_generated_batch_is_accepted(self):
        config = EXAMPLE_CONFIG
        source = export_module(generate(config), config)
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "Batch.lean"
            report = verify_source(
                source,
                destination=destination,
                project_dir=PROJECT,
                timeout_s=120,
            )
        self.assertEqual(report.status, "proved", report.message + "\n" + report.stderr)

    def test_false_equality_is_a_proof_failure(self):
        report = self.verify("theorem bad_eq : (1 = 0) := rfl\n")
        self.assertEqual(report.status, "failed", report.message)
        self.assertEqual(report.failure_class, "proof")
        self.assertIn("definitional", report.stderr.lower() + report.stdout.lower())

    def test_ill_typed_addition_is_a_typing_failure(self):
        report = self.verify("theorem bad_ty : (True + 1 = 1) := rfl\n")
        self.assertEqual(report.status, "failed", report.message)
        self.assertEqual(report.failure_class, "typing")

    def test_broken_token_is_a_syntax_failure(self):
        report = self.verify("theorem bad_syn : (1 = := rfl\n")
        self.assertEqual(report.status, "failed", report.message)
        self.assertEqual(report.failure_class, "syntax")

    def test_committed_example_matches_the_generator_and_lean(self):
        source = export_module(generate(EXAMPLE_CONFIG), EXAMPLE_CONFIG)
        self.assertEqual(EXAMPLE.read_text(encoding="utf-8"), source)
        report = verify_source(
            source,
            destination=EXAMPLE,
            project_dir=PROJECT,
            timeout_s=120,
        )
        self.assertEqual(report.status, "proved", report.message + "\n" + report.stderr)

    def test_cli_verify_accepts_the_example_config(self):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = main(
                [
                    "generate",
                    "--seed",
                    "1",
                    "--count",
                    "8",
                    "--out",
                    str(EXAMPLE),
                    "--verify",
                    "--timeout",
                    "120",
                ]
            )
        self.assertEqual(code, 0, stdout.getvalue())
        self.assertIn("proved", stdout.getvalue())

    def test_package_build_accepts_the_generated_module(self):
        completed = subprocess.run(
            [str(find_lake(PROJECT)), "build"],
            cwd=str(PROJECT),
            env=build_lean_env(PROJECT),
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_universal_conditional_and_unproved_expression(self):
        rules = ("add_zero_all", "eq_implies_add_zero", "open_double_eq")
        theorems = tuple(
            self.renumber(
                generate_general(GeneratorConfig(seed=1, count=1, rules=(rule,)))[0],
                index,
            )
            for index, rule in enumerate(rules)
        )
        config = GeneratorConfig(seed=1, count=3, rules=rules)
        with tempfile.TemporaryDirectory() as temporary:
            report, marked = verify_theorems(
                theorems,
                config,
                destination=Path(temporary) / "General.lean",
                project_dir=PROJECT,
                timeout_s=120,
            )
        self.assertEqual(report.status, "proved", report.message + "\n" + report.stderr)
        kinds = {item.metadata.kind: item for item in marked}
        self.assertEqual(kinds["universal"].metadata.verification, "proved")
        self.assertEqual(kinds["conditional"].metadata.verification, "proved")
        self.assertEqual(kinds["expression"].metadata.verification, "unverified")
        self.assertFalse(claimed_true(kinds["expression"]))
        self.assertTrue(claimed_true(kinds["universal"]))

    def test_every_proved_general_schema_is_accepted(self):
        rules = tuple(rule for rule in GENERAL_RULES if rule != "open_double_eq")
        theorems = tuple(
            self.renumber(
                generate_general(GeneratorConfig(seed=1, count=1, rules=(rule,)))[0],
                index,
            )
            for index, rule in enumerate(rules)
        )
        config = GeneratorConfig(seed=1, count=len(theorems), rules=rules)
        with tempfile.TemporaryDirectory() as temporary:
            report, marked = verify_theorems(
                theorems,
                config,
                destination=Path(temporary) / "Schemas.lean",
                project_dir=PROJECT,
                timeout_s=120,
            )
        self.assertEqual(report.status, "proved", report.message + "\n" + report.stderr)
        self.assertTrue(all(item.metadata.verification == "proved" for item in marked))
        self.assertTrue(all(claimed_true(item) for item in marked))

    def test_succ_and_int_decide(self):
        succ = Theorem(
            Compare("eq", UnaryOp("succ", NatLit(2)), NatLit(3)),
            Proof("rfl"),
            Metadata("gen_succ", "concrete", ("succ_concrete",), "unverified"),
        )
        integer = Theorem(
            Compare("eq", BinOp("add", IntLit(1), IntLit(-1)), IntLit(0)),
            Proof("decide"),
            Metadata("gen_int", "concrete", ("int_neg_add",), "unverified"),
        )
        config = GeneratorConfig(seed=1, count=2, rules=("eval_eq",))
        with tempfile.TemporaryDirectory() as temporary:
            report, marked = verify_theorems(
                (succ, integer),
                config,
                destination=Path(temporary) / "Wider.lean",
                project_dir=PROJECT,
                timeout_s=120,
            )
        self.assertEqual(report.status, "proved", report.message + "\n" + report.stderr)
        self.assertTrue(all(item.metadata.verification == "proved" for item in marked))

    def test_definition_and_dependent_theorem(self):
        definition = double_definition()
        theorem = theorem_about_double(definition)
        source = export_library(
            (definition,),
            (theorem,),
            GeneratorConfig(seed=1, count=1, rules=("le_refl",)),
        )
        report = self.verify(source)
        self.assertEqual(report.status, "proved", report.message + "\n" + report.stderr)

    def test_concrete_false_comparison_is_a_proof_failure(self):
        report = self.verify("theorem witness : (0 < 0) := by\n  decide\n")
        self.assertEqual(report.status, "failed", report.message + "\n" + report.stderr)
        self.assertEqual(report.failure_class, "proof")

    def test_negation_is_an_int_equality(self):
        theorem = Theorem(
            Compare("eq", UnaryOp("neg", IntLit(1)), IntLit(-1)),
            Proof("rfl"),
            Metadata("gen_neg", "concrete", ("int_neg",), "unverified"),
        )
        source = export_module(
            (theorem,),
            GeneratorConfig(seed=1, count=1, rules=("eval_eq",)),
        )
        report = self.verify(source)
        self.assertEqual(report.status, "proved", report.message + "\n" + report.stderr)

    def test_undeclared_atom_is_rejected_by_lean(self):
        variable = Var("a", "Nat")
        theorem = Theorem(
            Forall((variable,), Atom("P", (variable,))),
            None,
            Metadata("gen_atom", "expression", ("atom_p",), "unverified"),
        )
        source = export_module(
            (theorem,),
            GeneratorConfig(seed=1, count=1, rules=("eval_eq",)),
        )
        report = self.verify(source)
        self.assertEqual(report.status, "failed", report.message + "\n" + report.stderr)
        self.assertIn("unknown", (report.stderr + report.stdout).lower())

    def test_generated_definition_bound_is_accepted(self):
        config = GeneratorConfig(
            seed=1,
            count=1,
            rules=("use_definition",),
            complexity_bounds={"dependencies": (1, 1), "definitions": (1, 1)},
        )
        theorems = tuple(generate(config))
        source = export_library(supporting_definitions(theorems), theorems, config)
        report = self.verify(source)
        self.assertEqual(report.status, "proved", report.message + "\n" + report.stderr)

    def test_cited_exploration_theorem_is_accepted(self):
        proved = next(item for item in explore(1, 4) if item.status == "proved")
        theorem = theorem_from_proved(proved)
        source = export_module(
            (theorem,),
            GeneratorConfig(seed=1, count=1, rules=("add_zero_all",)),
        )
        report = self.verify(source)
        self.assertEqual(report.status, "proved", report.message + "\n" + report.stderr)

    def renumber(self, theorem, index):
        meta = theorem.metadata
        return Theorem(
            theorem.statement,
            theorem.proof,
            Metadata(
                identifier=f"gen_mix_{index:04d}",
                kind=meta.kind,
                rules=meta.rules,
                verification=meta.verification,
                dependencies=meta.dependencies,
                discovered=meta.discovered,
            ),
        )

    def verify(self, source):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "Check.lean"
            return verify_source(
                source,
                destination=destination,
                project_dir=PROJECT,
                timeout_s=120,
            )


if __name__ == "__main__":
    unittest.main()
