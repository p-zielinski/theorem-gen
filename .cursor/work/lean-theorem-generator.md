# Ewolucyjny generator twierdzeń Lean 4

> Last updated: 2026-10-11
> Branch: `main` (zmiany etapów 0–8 są niezacommitowane)
> Status: done

## Problem & goal

Generator tworzy twierdzenia jako struktury, eksportuje je do wąskiego podzbioru Lean 4 i oddaje dowód do sprawdzenia kompilatorowi. „Done” dla serii 0–8: konkretna arytmetyka, zdania ogólne, szersze AST, rejestr, złożoność, definicje, hipotezy i eksploracja, która umie zostawić zdanie nierozstrzygnięte. Lean sprawdza to, co ma dowód. Brak dowodu nie jest fałszem.

## Scope

- **In scope:** etapy 0–8 według `docs/stages.md`.
- **Out of scope:** Mathlib, pełny parser Leana, trwały rejestr na dysku, nowe zależności Pythona, commit (użytkownik o niego nie prosił).

## Key files & context

| Area | Path | Role |
|------|------|------|
| Raporty | `docs/stage-0.md` … `docs/stage-8.md` | Zakres, testy, polecenia, ograniczenia |
| Architektura | `docs/architecture.md` | Moduły i kontrakt weryfikacji |
| Kryteria | `docs/stages.md` | Definicja ukończenia |
| Pakiet | `theorem_gen/` | Generacja, eksport, rejestr, hipotezy, eksploracja |
| Testy | `tests/test_stage2.py` … `tests/test_stage8.py`, `tests/test_lean_integration.py` | unittest i prawdziwy Lean |
| Projekt Lean | `lean/` | Lake, bez Mathlib; złoty plik etapu 1 |
| Toolchain | `.toolchains/elan/` | Lokalny Lean 4.34.1, poza gitem |

## Decisions

- 2026-10-11: Python generuje i eksportuje, Lean wyłącznie sprawdza. Bez parsera Leana i bez Mathlib.
- 2026-10-11: Elan jest lokalny (`.toolchains/elan`, `--no-modify-path`). Wersja przypięta: Lean 4.34.1, Lake 5.0.0.
- 2026-10-11: LCG zamiast `random.Random`, żeby ziarno nie zależało od wersji Pythona.
- 2026-10-11: `sorry` przy kodzie wyjścia 0 nie jest dowodem. `RLIMIT_AS` pominięty, bo CPython 3.9 na tym macOS nie umie go ustawić; zostają timeout i `RLIMIT_CPU`.
- 2026-10-11: Testy na `unittest` ze standardowej biblioteki, bez nowych zależności Pythona.
- 2026-10-11: Ścieżki pliku i projektu są rozwiązywane przed zmianą `cwd` Lake.
- 2026-10-11: `rules=None` znaczy co innego w `generate` (reguły konkretne) i w `generate_general` (reguły ogólne). Eksport ogólny używa `config_for_export`.
- 2026-10-11: `pred` jest odrzucony, bo obcięty poprzednik na `Nat` zmienia znaczenie zera.
- 2026-10-11: Cytowanie i użycie definicji mają `discovered=False`.
- 2026-10-11: Eksploracja ma cztery szablony. `no_proof`, `refuted` i `unprovable_in_fragment` są rozłączne. Status `proved` w eksploracji oznacza cytowanie lematu; plik Lean i tak jest sprawdzany osobno.
- 2026-10-11: Komunikat Leana `decide` „proved that the proposition … is false” jest klasą `proof`.
- 2026-10-11: Granice złożoności obejmują wszystkie sześć miar. `variables` wybiera zdanie ogólne, a `dependencies` i `definitions` wymagają jawnej reguły `use_definition`, spoza domyślnego zestawu.

## Progress

- [x] Etap 0: środowisko, architektura, kryteria
- [x] Etap 1: konkretne `Nat`, eksport, Lean, raport
- [x] Etap 2: universal, conditional, expression
- [x] Etap 3: szersze AST i odrzucenie złych typów
- [x] Etap 4: rejestr, cykle, replay
- [x] Etap 5: miary i granice generowania
- [x] Etap 6: definicja `double` sprawdzona w Leanie
- [x] Etap 7: hipotezy i metryki różnorodności
- [x] Etap 8: eksploracja czterech werdyktów

## Next steps

1. Nie zaczynać kolejnego etapu w tej serii. Etapy 0–8 są zamknięte.
2. Commit tylko na prośbę użytkownika.

## Blockers / open questions

- Brak. Lean 4.34.1 jest zainstalowany lokalnie.

## Verification

```sh
python3 -m unittest discover -s tests -v
python3 -m theorem_gen generate --seed 1 --count 8 \
  --out lean/TheoremGen/Generated.lean --verify --timeout 120
python3 -m compileall -q theorem_gen tests
git diff --check
```

Wynik: 133 testy `OK`. Zestaw obejmuje każdy schemat ogólny z dowodem sprawdzony przez Lean, odrzucenie źle otypowanego argumentu stałej i atomu, timeout hipotezy oraz rejestr z zależnością dopisaną w tej samej partii. CLI `verification: proved`. `lake build` przechodzi w teście pakietu. Raport zbiorczy poleceń: `docs/stage-8.md`.
