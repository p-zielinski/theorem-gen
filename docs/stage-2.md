# Etap 2 — zmienne i twierdzenia ogólne

> Data ukończenia: 2026-10-11
> Status: ukończony

## 1. Zaimplementowany zakres

`generate_general` rozróżnia cztery rodzaje wyników:

| Rodzaj | Przykład | Dowód w eksporcie |
|--------|----------|-------------------|
| `concrete` | zostaje w `generate` | `rfl` albo `decide` |
| `universal` | `∀ a, a + 0 = a` | aplikacja lematu, np. `Nat.add_zero a` |
| `conditional` | `a = b → a + 0 = b` | `rw` i `exact h` |
| `expression` | `∀ a, a + a = a` | brak; w pliku jest tylko `#check` |

Wygenerowane zdanie ma status `unverified`. `claimed_true` jest prawdziwe dopiero wtedy, gdy istnieje dowód i Lean oznaczył kopię metadanych jako `proved`. Wyrażenie bez dowodu nie dostaje statusu `proved`, nawet gdy otaczający plik się kompiluje.

Reguły ogólne: `add_zero_all`, `zero_add_all`, `add_comm_all`, `mul_comm_all`, `mul_one_all`, `one_mul_all`, `le_refl_all`, `eq_implies_add_zero`, `open_double_eq`.

`generate` odrzuca nazwę reguły ogólnej. Domyślny generator konkretny i plik `lean/TheoremGen/Generated.lean` pozostają bez zmian.

Gdy `GeneratorConfig.rules` jest `None`, `generate` używa reguł etapu 1, a `generate_general` używa reguł ogólnych. Nagłówek eksportu ogólnego trzeba złożyć przez `config_for_export`, inaczej komentarz wypisałby listę reguł konkretnych.

## 2. Testy

- `tests/test_stage2.py`: dokładny eksport uniwersalny, przemienny i warunkowy; wyrażenie bez `:=` i bez `sorry`; nagłówek reguł; powtarzalność ziarna; wyczerpanie unikalności; odrzucenie reguły ogólnej przez generator konkretny
- `tests/test_lean_integration.py`: Lean akceptuje każdy schemat ogólny, który ma dowód (`add_zero_all`, `zero_add_all`, `add_comm_all`, `mul_comm_all`, `mul_one_all`, `one_mul_all`, `le_refl_all`, `eq_implies_add_zero`). Wyrażenie bez dowodu zostaje `unverified`, także gdy reszta pliku przechodzi.

## 3. Polecenia i wyniki

Te same polecenia co w [stage-8.md](stage-8.md). Dla tego etapu rozstrzygający jest test `test_universal_conditional_and_unproved_expression`: status pliku `proved`, a wyrażenie bez dowodu nie jest oznaczone jako prawdziwe.

## 4. Ograniczenia

Każda reguła ogólna ma jeden schemat. To nie jest przeszukiwanie dowolnych formuł. `open_double_eq` jest fałszywe, ale generator go nie obala; obalenie należy do etapu 7.

## 5. Ocena kryteriów

Kryterium etapu 2 jest spełnione: system rozróżnia zdanie konkretne, zdanie dla wszystkich, zdanie z założeniem i wyrażenie bez dowodu, i żadnego nie uznaje za prawdziwe tylko dlatego, że je wygenerował.

## 6. Następny krok

Etap 3 rozszerza AST o `Int`, `succ` i odrzucenie kombinacji, które zmieniłyby znaczenie.
