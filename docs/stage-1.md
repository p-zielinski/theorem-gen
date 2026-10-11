# Etap 1 — minimalny generator arytmetyczny

> Data ukończenia: 2026-10-11
> Status: ukończony

## 1. Zaimplementowany zakres

- typowane, niemutowalne AST: `NatLit`, `BinOp`, `Compare`
- typy `Nat` i `Prop`; operatory `+`, `*`, `=`, `<=`, `<`
- 12 jawnych reguł tworzących prawdziwe zdania o konkretnych liczbach
- oddzielenie zdania, dowodu (`rfl` / `decide`) i metadanych
- deterministyczny 32-bitowy LCG, stabilny między wersjami Pythona
- konfiguracja liczby wyników, granic, głębokości, reguł i unikalności
- eksport ograniczonego podzbioru Lean 4 bez zmiany znaczenia AST
- CLI `python3 -m theorem_gen generate`
- weryfikacja przez prawdziwy Lean z timeoutem, limitem CPU i zabijaniem grupy
  procesów
- jawne statusy `proved`, `failed`, `timeout`, `unavailable`
- osobna klasyfikacja błędu: `syntax`, `typing`, `proof`, `rejected`, `other`
- gotowy przykład `lean/TheoremGen/Generated.lean`

W samym etapie 1 nie dodano zmiennych, kwantyfikatorów, założeń, rejestru
zależności ani generowania hipotez. Te możliwości doszły w etapach 2–8 i nie
zmieniają domyślnego generatora konkretnych twierdzeń.

## 2. Przebieg TDD

1. Przed pakietem `theorem_gen` zapisano testy AST, RNG, generatora, eksportu,
   CLI i weryfikatora.
2. Pierwsze uruchomienie:

   ```text
   Ran 7 tests
   FAILED (errors=7)
   ModuleNotFoundError: No module named 'theorem_gen'
   ```

3. Po minimalnej implementacji zestaw jednostkowy wykrył błąd w samym teście
   sekwencji RNG (tworzona była nowa instancja dla każdej liczby). Test
   poprawiono tak, by badał jedną sekwencję.
4. Po implementacji integracji pierwszy pełny zestaw dał `67 tests ... OK`.
5. Audyt dodał test procesu zabitego sygnałem i test `lake build`; zestaw
   wzrósł do 69.
6. Końcowa, rzeczywista komenda CLI ze względnym `--out` wykryła regresję:
   Lean szukał `lean/lean/TheoremGen/Generated.lean`. Najpierw dodano test
   `test_relative_destination_is_made_absolute_before_changing_cwd` i
   potwierdzono jego czerwony wynik, następnie weryfikator zaczął rozwiązywać
   ścieżki przed zmianą katalogu procesu.
7. Końcowy zestaw ma 70 testów.

## 3. Dodane testy

- jednostkowe: AST, typowanie, ewaluacja, klucze strukturalne, RNG, eksport
- deterministyczność: złota sekwencja i powtarzalność konfiguracji
- brzegowe: zero wyników, ujemny seed, `max_literal = 0`, wyczerpanie
  unikalności, pusty zbiór reguł, limit prób
- regresyjne: względna ścieżka pliku przy innym `cwd`, sygnał/limit procesu,
  `sorry` przy kodzie 0, priorytet błędu dowodu nad tekstem `Type mismatch`
- właściwościowe bez zależności zewnętrznych: wiele seedów daje prawdziwe,
  unikalne zdania bez `sorry`; dodatkowa sonda 100 seedów po 8 twierdzeń
- integracyjne: poprawny batch, fałszywa równość, błąd typu, błąd składni,
  dokładność zapisanego przykładu, CLI z `--verify`, czysty `lake build`

## 4. Rzeczywiście uruchomione polecenia

Z katalogu repozytorium:

```sh
export ELAN_HOME="$PWD/.toolchains/elan"
export PATH="$ELAN_HOME/bin:$PATH"

python3 -m unittest discover -s tests -v
python3 -m theorem_gen generate \
  --seed 1 \
  --count 8 \
  --out lean/TheoremGen/Generated.lean \
  --verify \
  --timeout 120
```

Z katalogu `lean/`:

```sh
export ELAN_HOME="$PWD/../.toolchains/elan"
export PATH="$ELAN_HOME/bin:$PATH"
lake clean
lake build
```

Dodatkowo:

```sh
python3 -m compileall -q theorem_gen tests
git diff --check
```

## 5. Wyniki

```text
Python 3.9.6
Lean 4.34.1
Lake 5.0.0-src+5045d00

Ran 70 tests
OK

generated 8 theorems
wrote lean/TheoremGen/Generated.lean
verification: proved
Lean accepted the file with exit code 0.

Build completed successfully (4 jobs).
100 seeds x 8: OK
```

Przykład jest bajt w bajt zgodny z wynikiem `export_module(generate(...))`.
IDE nie raportuje błędów lintera. `compileall` i `git diff --check` kończą się
kodem 0.

## 6. Znane ograniczenia

- generator `generate` tworzy tylko konkretne zdania o `Nat`; zmienne i kwantyfikatory są w modułach etapów 2–8
- brak Mathlib; etap 1 korzysta z Lean prelude
- LCG używa modulo w `randint`, więc rozkład może być lekko skośny, ale jest
  deterministyczny
- na Darwin/Python 3.9 nie działa ustawienie `RLIMIT_AS`; działają timeout i
  `RLIMIT_CPU`. Mechanizm limitu CPU jest uniksowy.
- `verify_source` jest przeznaczone dla zaufanego kodu z eksportera etapu 1.
  Bramka odrzuca konstrukcje wykonawcze i niedokończone dowody, ale nie jest
  pełnym sandboxem dla dowolnego kodu Lean.
- warning `declaration uses sorry` jest odrzucany mimo kodu 0. Pozostałe
  wyniki Lean są oceniane przede wszystkim według kodu procesu.
- `max_value` ogranicza wartości obu stron, a nie rozmiar AST ani trudność;
  pełne sterowanie złożonością należy do etapu 5.

## 7. Ocena kryteriów

Wszystkie kryteria etapu 1 z [stages.md](stages.md) są spełnione:
deterministyczność, liczba wyników, opcjonalna unikalność, poprawny eksport,
rzeczywista weryfikacja Lean, jawne błędy, testy oraz ten raport.

Niezależny audyt nie znalazł błędów krytycznych ani wysokich. W trakcie
końcowej weryfikacji poprawiono dodatkowo regresję ścieżki względnej i ponownie
uruchomiono cały zestaw.

## 8. Następny krok

W momencie zamknięcia etapu 1 kolejnym krokiem był etap 2. Został zrealizowany
później. Aktualny stan etapów 2–8 jest w `docs/stage-2.md` … `docs/stage-8.md`.
