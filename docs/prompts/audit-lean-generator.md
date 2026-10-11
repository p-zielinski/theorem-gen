# Prompt: niezależny audyt generatora Lean 4 (etapy 0–8)

Skopiuj cały blok poniżej (od `Jesteś niezależnym…` do końca bloku) jako pełne polecenie dla agenta lub modelu. Nie ufaj statusom „ukończony” w dokumentacji — wymagaj dowodów z kodu, testów i rzeczywistego Leana.

Uwaga dla autorów Markdown: blok jest w fence `text` czterema backtickami, żeby wewnętrzne przykłady poleceń nie ucinały copy-paste.

````text
Jesteś niezależnym audytorem inżynierii oprogramowania i formalnej weryfikacji.
Przeprowadź audyt projektu w bieżącym katalogu repozytorium (root z plikami
docs/, theorem_gen/, tests/, lean/). Nie zakładaj absolutnej ścieżki użytkownika.

Cel: sprawdzić, czy etapy 0–8 generatora twierdzeń Lean 4 są faktycznie
zaimplementowane, przetestowane i działają zgodnie z kryteriami w docs/stages.md.

Zakres: TYLKO audyt. Nie implementuj nowych funkcji i nie „naprawiaj po drodze”.
Jeśli coś jest zepsute: oznacz etap not_met lub incomplete_without_lean i wypisz
poprawki P0/P1/P2. Nie zmieniaj kodu w ramach tego promptu.

## Zasady audytu

1. Status „ukończony” w docs/stages.md, docs/stage-*.md lub .cursor/work/* NIE jest dowodem.
2. Dla każdego etapu zbuduj obowiązkową mapę:
   kryterium → ścieżka kodu / API → test → Lean (lub N/A) → wynik uruchomienia.
   Lean=N/A tylko gdy etap nie wymaga Leana (np. 0, 4). Skip LeanIntegrationTests
   z braku lake = incomplete, nie „met”.
3. Audyt jest niekompletny, jeśli testy LeanIntegrationTests zostały pominięte
   z braku lake/lean.
4. Timeout, unavailable i brak dowodu NIE są fałszem.
5. Trzy różne słowa „proved” nie wolno mieszać:
   - VerificationReport.status (Lean zaakceptował plik)
   - HypothesisAssessment.status (ocena hipotezy)
   - ExplorationResult.status (cytowanie lematu w eksploracji; nie jest jeszcze claimed_true)
6. claimed_true(theorem) jest prawdziwe tylko gdy verification == "proved" ORAZ proof is not None.
7. Nie traktuj wygenerowania zdania jako prawdy matematycznej.
8. Złoty plik lean/TheoremGen/Generated.lean dla seed=1, count=8 musi pozostać zgodny z generate().
9. Domyślny CLI (python3 -m theorem_gen generate) ćwiczy tylko generator konkretny etapu 1.
10. Mathlib jest poza zakresem. Nie dodawaj zależności Pythona.
11. Zwróć werdykt per etap: met | met_with_limitations | not_met | incomplete_without_lean,
    z dowodami i listą poprawek.

## Środowisko i polecenia obowiązkowe

Z katalogu root repozytorium:

    export ELAN_HOME="$PWD/.toolchains/elan"
    export PATH="$ELAN_HOME/bin:$PATH"

    # Wymagane: Lean 4.34.1 i Lake (patrz lean/lean-toolchain i README.md).
    # Jeśli toolchainu brakuje — zainstaluj lokalnie według README, bez zmiany PATH użytkownika.
    # Bez lake audyt etapów Lean jest NIEKOMPLETNY.

    python3 -m unittest discover -s tests -v
    python3 -m theorem_gen generate \
      --seed 1 \
      --count 8 \
      --out lean/TheoremGen/Generated.lean \
      --verify \
      --timeout 120
    python3 -m compileall -q theorem_gen tests
    git diff --check

Oczekiwane (pełny audyt z Leanem): 134 testów OK; CLI: verification: proved.

Dodatkowo:

    (cd lean && lake build)
    python3 -c "
    from theorem_gen.explore import explore
    for r in explore(1, 4):
        print(r.identifier, r.status, r.witness, r.dependencies)
    "
    python3 -c "
    from theorem_gen.config import GeneratorConfig
    from theorem_gen.generate import generate
    from theorem_gen.export_lean import export_module
    from pathlib import Path
    c = GeneratorConfig(seed=1, count=8)
    src = export_module(generate(c), c)
    print(src == Path('lean/TheoremGen/Generated.lean').read_text(encoding='utf-8'))
    "

Opcjonalne szybsze wycinki:

    python3 -m unittest tests.test_expr tests.test_rng tests.test_generate tests.test_export tests.test_verify tests.test_cli -v
    python3 -m unittest tests.test_stage2 tests.test_stage3 tests.test_stage4 tests.test_stage5 tests.test_stage6 tests.test_stage7 tests.test_stage8 -v
    python3 -m unittest tests.test_lean_integration -v

## Mapa etapów — co musisz sprawdzić

### Etap 0 — analiza
Źródła: docs/stage-0.md, docs/architecture.md, docs/stages.md, lean/lean-toolchain.
Sprawdź:
- Python generuje AST/eksport/proces; Lean jest jedynym sędzią dowodu; brak parsera Leana w Pythonie.
- Pin toolchainu leanprover/lean4:v4.34.1.
- Kontrakt statusów w theorem_gen/verify.py: proved|failed|timeout|unavailable oraz failure_class.
- Tabela modułów w architecture.md odpowiada plikom w theorem_gen/.

### Etap 1 — konkretna arytmetyka
Kod: theorem_gen/{rng,expr,config,theorem,generate,export_lean,verify,__main__}.py
Testy: tests/test_{rng,expr,generate,export,verify,cli,lean_integration}.py
Sprawdź:
- determinizm generate(GeneratorConfig)
- count=0 → []
- unique i GenerationError z tekstem „not a mathematical verdict”
- DEFAULT_RULES (12 reguł); reguły ogólne odrzucane jako „not a concrete rule”
- identyfikatory gen_s{seed}_{index}, ujemny seed → token neg
- eksport nie zmienia znaczenia; rfl/decide nie są podmieniane
- sorry przy exit 0 nie jest proved; timeout/sygnał nie jest false
- złoty plik Generated.lean; CLI --verify; lake build

### Etap 2 — zmienne i twierdzenia ogólne
Kod: theorem_gen/general.py, export_lean.py, theorem.py
Testy: tests/test_stage2.py, test_lean_integration.py
Sprawdź:
- rodzaje: concrete / universal / conditional / expression
- rules=None: generate → DEFAULT_RULES; generate_general → GENERAL_RULES
- eksport ogólny przez config_for_export
- expression: #check, brak :=, claimed_true False, verify_theorems nie oznacza proved bez proof
- Lean akceptuje każdy schemat z dowodem (bez open_double_eq)

### Etap 3 — szersze AST
Kod: theorem_gen/expr.py, export_lean.py
Testy: tests/test_stage3.py, test_lean_integration.py
Sprawdź:
- IntLit, Var, UnaryOp(succ|neg), Const, Atom, Implies, Forall
- TypingError dla Nat+Int, neg Nat, succ Int, pred, złych argumentów Const/Atom, unbound/duplicate binders
- Lean: succ, Int decide/neg; undeclared atom → failed
- generator konkretny nadal nie losuje tych konstrukcji w DEFAULT_RULES

### Etap 4 — rejestr i zależności
Kod: theorem_gen/registry.py, definitions.py
Testy: tests/test_stage4.py
Sprawdź:
- stable_identifier, missing deps, cycles (self i mutual), duplicate id
- zależność w tej samej partii extend
- Registry.replay(history) odtwarza graf
- citation/use_definition → discovered=False; define → discovered=True
- Lean=N/A dla samego rejestru (in-memory)

### Etap 5 — złożoność
Kod: theorem_gen/complexity.py, config.py, generate.py, general.py
Testy: tests/test_stage5.py
Sprawdź sześć miar: ast_size, depth, variables, operators, dependencies, definitions.
- NatLit(1) i NatLit(10**12) mają ten sam rozmiar/głębokość
- granice filtrują generate i generate_general
- use_definition + dependencies/definitions wybiera double
- explore() NIE czyta complexity_bounds
- niemożliwe granice → GenerationError, nie werdykt matematyczny

### Etap 6 — definicje
Kod: theorem_gen/definitions.py, export_lean.export_library
Testy: tests/test_stage6.py, test_lean_integration.py
Sprawdź validate_definition, double, theorem_about_double, supporting_definitions,
odrzucenie free var / type mismatch / recursion / duplicate param,
Lean: def double + gen_double_zero := rfl → proved.

### Etap 7 — hipotezy
Kod: theorem_gen/hypothesis.py
Testy: tests/test_stage7.py, test_verify.py, test_lean_integration.py
Sprawdź statusy: proved, refuted, unresolved, invalid_syntax, invalid_type.
- kontrprzykład przed zadeklarowanym „proved”
- skończone przeszukanie Nat; brak świadka ≠ prawda
- timeout nie rozstrzyga prawdziwego zdania
- decide „proved that the proposition … is false” → failure_class proof
- limit_repetition i diversity_metrics

### Etap 8 — otwarta eksploracja
Kod: theorem_gen/explore.py
Testy: tests/test_stage8.py, test_lean_integration.py
Sprawdź explore(seed, count):
- statusy: proved (cytowanie), refuted, no_proof, unprovable_in_fragment
- seed 1, count 4 obejmuje wszystkie cztery; no_proof ≠ refuted
- theorem_from_proved zostaje unverified do czasu Leana
- Lean akceptuje cytowanie Nat.add_zero

## Inwarianty do grepa / ręcznego sprawdzenia

- Jedyny zapis składni Lean: theorem_gen/export_lean.py (brak drugiego string-buildera Lean).
- GenerationError zawiera „not a mathematical verdict” przy limitach generowania.
- Komunikaty timeout nie zawierają „false” / „rejected” jako werdyktu.
- discovered=False dla cite / use_definition.
- Brak słowa sorry w poprawnych eksportach generatora.
- Dualne pętle generate.py vs general.py: porównaj unique, max_attempts, complexity.
- Dualne _within_complexity: concrete vs general — obie ścieżki muszą mieć testy.

## Format raportu audytu

Dla każdego etapu 0–8:

### Etap N — <nazwa>
- Werdykt: met | met_with_limitations | not_met | incomplete_without_lean
- Mapa (obowiązkowa tabela; Lean=N/A tylko gdy etap nie wymaga Leana, np. 0/4):

| Kryterium (docs/stages.md) | Kod / API | Test | Lean (polecenie lub N/A) | Wynik |
|----------------------------|-----------|------|--------------------------|-------|
| … | … | … | … | pass/fail/skip→incomplete |

- Ograniczenia (jeśli met_with_limitations): …
- Luki / ryzyka: …
- Wymagane poprawki (jeśli not_met): priorytet P0/P1/P2

Na końcu:
1. Tabela zbiorcza etapów
2. Wynik poleceń (liczba testów, CLI verify, lake build)
3. Top 10 ryzyk (np. pominięte Lean tests, przeciążenie „proved”, CLI tylko stage-1)
4. Rekomendacja: accept / accept with caveats / reject / incomplete_without_lean

Nie kończ audytu werdyktem accept, dopóki nie uruchomisz pełnego unittest z dostępem
do lake albo jawnie oznaczysz audyt jako incomplete_without_lean.
````

## Jak używać

1. Wklej cały blok `text` powyżej do nowego czatu / agenta z dostępem do repozytorium.
2. Wymagaj pełnego toolchainu Lean przed werdyktem „met” / „accept”.
3. Zachowaj wynik audytu jako osobny raport (np. `docs/audits/YYYY-MM-DD.md`), jeśli chcesz historię.
