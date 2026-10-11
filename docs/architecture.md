# Architektura

> Ostatnia aktualizacja: 2026-10-11
> Obowiązujący zakres kodu: etapy 0–8. Domyślna ścieżka CLI nadal generuje konkretne twierdzenia etapu 1. Osobna pętla z SQLite jest w `docs/continuous-ai-architecture.md` i nie zmienia tego kontraktu.

Generator składa twierdzenia jako drzewo, a nie jako sklejany tekst. Lean dostaje dopiero gotowy, wąski fragment języka i sam sprawdza dowód.

```
GeneratorConfig + LCG
        │
        ▼
   reguły konstrukcji
        │
        ▼
  Compare : Prop          Metadata (id, kind, reguły, status)
        │
        ▼
   eksport Lean 4  ──►  lake env lean  ──►  VerificationReport
```

## Moduły

| Moduł | Rola |
|-------|------|
| `theorem_gen/rng.py` | LCG. Ta sama sekwencja na każdym CPythonie. |
| `theorem_gen/expr.py` | AST: `Nat`, `Int`, zmienne, `succ`, `neg`, kwantyfikator, implikacja, atom. |
| `theorem_gen/config.py` | `GeneratorConfig`, reguły konkretne i ogólne, granice złożoności. |
| `theorem_gen/theorem.py` | Twierdzenie, opcjonalny dowód, metadane, `claimed_true`. |
| `theorem_gen/export_lean.py` | Jedyny zapis składni Lean, także definicji i `#check`. |
| `theorem_gen/generate.py` | Konkretne zdania o `Nat`. |
| `theorem_gen/general.py` | Zdania uniwersalne, warunkowe i wyrażenia bez dowodu. |
| `theorem_gen/complexity.py` | Miary strukturalne. |
| `theorem_gen/registry.py` | Identyfikatory, zależności, cykle, replay. |
| `theorem_gen/definitions.py` | Definicja `double` i twierdzenie, które z niej korzysta. |
| `theorem_gen/hypothesis.py` | Ocena hipotezy osobno od generowania. |
| `theorem_gen/explore.py` | Cztery szablony eksploracji i cztery różne werdykty. |
| `theorem_gen/verify.py` | Proces Leana, limity, klasyfikacja wyniku. |
| `theorem_gen/__main__.py` | CLI `generate`. |
| `lean/` | Projekt Lake bez Mathlib. |

## Typy etapu 1

- `Nat`: literał nieujemny albo `+` / `*` dwóch wyrażeń `Nat`.
- `Prop`: porównanie dwóch wyrażeń `Nat` (`=`, `<=`, `<`).

Konstruktor odrzuca literał ujemny, wartość `bool`, obcy operator i dziecko złego typu. Eksporter nie naprawia takiego drzewa, bo drzewo w ogóle nie powstaje. Fałszywe, ale poprawnie otypowane zdanie (`1 = 0`) da się wyeksportować bez zmiany znaczenia; generator sam go nie tworzy. Odrzuca je Lean.

## Dowód

| Zdanie | Metoda w generatorze | Lean |
|--------|----------------------|------|
| równość konkretnych `Nat` z `+` i `*` | `rfl` | równość definicyjna |
| `<=`, `<` | `by decide` | rozstrzygalne porównanie |

Eksporter wypisuje metodę, którą dostał. Nie podmienia `rfl` na `decide` ani odwrotnie. `sorry` nie jest metodą dowodu.

## Generator

Reguły: `eval_eq`, `add_zero`, `zero_add`, `mul_one`, `one_mul`, `mul_zero`, `zero_mul`, `add_comm`, `mul_comm`, `le_between`, `lt_between`, `le_refl`.

Kandydat odpada, gdy reguła nie stosuje się do granic (na przykład `a < b` przy `max_literal = 0`), gdy któraś strona przekracza `max_value`, albo gdy `unique` widzi powtórzony klucz strukturalny. Po wyczerpaniu prób powstaje `GenerationError`. To limit konfiguracji, nie werdykt o fałszywości zdania.

Identyfikator `gen_s<seed>_<index>` jest stabilny dla pozycji w wyniku. Ujemne ziarno dostaje token `neg`.

## Weryfikacja

Polecenie, bez powłoki:

```text
lake --dir <projekt> env lean <plik>
```

- kod 0 i brak ostrzeżenia `sorry` → `proved`
- kod 0 i `declaration uses sorry` → `failed` / `proof`
- kod dodatni → `failed` oraz klasa: `proof`, `syntax`, `typing` albo `other`
- timeout albo kod ujemny (proces zabity przez limit) → `timeout`, wynik nierozstrzygnięty
- brak `lake` lub błąd uruchomienia → `unavailable`

Przed startem procesu odrzucane są fragmenty spoza etapu 1, które mogłyby coś wykonać albo uznać niedokończony dowód: `#eval`, `run_io`, `run_cmd`, `sorry`, `unsafe`, `axiom`, `opaque`. To bramka bezpieczeństwa, nie sprawdzanie prawdy.

Limit czasu jest parametrem. Proces dostaje własną grupę, więc timeout zabija także dzieci `lake`. Dodatkowo ustawiany jest `RLIMIT_CPU`. `RLIMIT_AS` na tym interpreterze nie działa (etap 0).

`verify_source` jest interfejsem dla zaufanego kodu utworzonego przez eksporter
etapu 1, nie sandboxem dla dowolnego kodu Lean. Eksporter nie wypisuje importów,
komend ani własnych deklaracji poza twierdzeniami. Przed uruchomieniem ścieżki
projektu i pliku są zamieniane na absolutne, żeby zmiana `cwd` procesu Lake nie
zmieniała wskazanego pliku.

Status weryfikacji dopisywany jest do kopii metadanych. Obiekty zwrócone przez generator pozostają `unverified`, dopóki ktoś nie uruchomi Leana.

## Format pliku

Nagłówek powtarza ziarno, liczbę twierdzeń i parametry konfiguracji. Treść to wyłącznie twierdzenia `rfl` i `decide`. Odtworzenie pliku wymaga tego samego kodu generatora, tego samego configu i tego samego LCG.

## Po etapie 1

Konkretny generator nie losuje zmiennych. Ogólne zdania powstają w `generate_general`, definicje w `definitions`, a otwarte wyniki w `explore`. Eksporter nadal odrzuca rodzaj, którego nie umie zapisać. `verify_theorems` dopisuje status Leana tylko do twierdzeń, które mają dowód.

Cztery werdykty eksploracji są rozłączne: cytowanie lematu, kontrprzykład, brak dowodu oraz brak reguły dla atomu w tym fragmencie. Timeout procesu Leana pozostaje wynikiem nierozstrzygniętym i nie jest fałszem.

`ExplorationResult.status == "proved"` oznacza tylko cytowanie lematu
(`discovered=False`). To nie jest `claimed_true` i nie zastępuje
`VerificationReport.status` po `verify_source`. Filtr złożoności dla
`generate` i `generate_general` idzie przez wspólne
`complexity.candidate_within_bounds`.

## Rozszerzanie

Nowa konstrukcja powinna dostać wariant drzewa, test typowania, test eksportu i test Leana. Nie należy zmieniać po cichu konkretnych twierdzeń etapu 1 ani złotego pliku `lean/TheoremGen/Generated.lean`.

Pętla `theorem_gen.learn` dokłada kolejkę, checkpoint i status wyprowadzony z Leana. Jej opis, bramki curriculum i budżet RAM są w `docs/continuous-ai-architecture.md`.
