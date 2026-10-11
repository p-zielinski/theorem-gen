# Etap 7 — hipotezy

> Data ukończenia: 2026-10-11
> Status: ukończony

## 1. Zaimplementowany zakres

`assess_hypothesis` zwraca jeden ze statusów:

| Status | Kiedy |
|--------|--------|
| `proved` | podano dowód i weryfikacja Leana ma status `proved` |
| `refuted` | skończone przeszukanie znalazło kontrprzykład |
| `unresolved` | nie ma kontrprzykładu i nie ma przyjętego dowodu |
| `invalid_syntax` | błąd składni źródła |
| `invalid_type` | zdanie nie jest poprawnie otypowanym `Prop` albo Lean zgłosił błąd typu |

Kontrprzykład jest sprawdzany przed zadeklarowanym dowodem. Fałszywe `1 = 0` z podrobionym statusem `proved` pozostaje `refuted`.

Przeszukanie podstawia `Nat` od 0 do `search_bound` włącznie. `∀ a, a < a` daje świadka `a = 0`. `∀ a, a + a = a` przy granicy 0 zostaje `unresolved`, bo `0 + 0 = 0` nie jest kontrprzykładem; przy granicy 1 świadkiem jest `a = 1`. Brak świadka nie jest dowodem prawdy. Nieudany dowód źródła bez drzewa też nie jest fałszem: komunikat mówi wprost, że porażka dowodu nie ustala fałszywości.

Zamknięte porównania `Int` są liczone bezpośrednio. `(1 + -1) = 1` jest obalone, a `(1 + -1) = 0` bez dowodu zostaje `unresolved`.

`limit_repetition` zwija zdania o tym samym kluczu strukturalnym. `diversity_metrics` podaje liczbę, liczbę unikalnych, iloraz i entropię kształtu według klasy korzenia. Pusty zbiór ma iloraz 1 i entropię 0.

Lean dla `theorem witness : (0 < 0) := by decide` zwraca `failed` / `proof`, bo taktyka wykazała, że zdanie jest fałszywe (`proved that the proposition`).

## 2. Testy

`tests/test_stage7.py` oraz `test_concrete_false_comparison_is_a_proof_failure` i dopisek w `tests/test_verify.py` dla komunikatu `decide`.

## 3. Polecenia i wyniki

Wspólny przebieg jest w [stage-8.md](stage-8.md). Rzeczywisty komunikat Leana dla `0 < 0`:

```text
error: Tactic `decide` proved that the proposition
  0 < 0
is false
```

Klasyfikator przypisuje go do `proof`, nie do `other`.

## 4. Ograniczenia

Przeszukanie kwantyfikatorów obejmuje tylko bindery `Nat`. Zdanie, którego po podstawieniu nie da się policzyć, nie jest obalane; szukanie kończy się brakiem świadka. To nie jest rozstrzygnięcie dla dowolnej arytmetyki. Entropia kształtu grupuje po klasie korzenia, więc dwa różne porównania `Compare` mają ten sam kształt; powtórzenia łapie osobno klucz strukturalny.

## 5. Ocena kryteriów

Kryterium etapu 7 jest spełnione: hipoteza może być udowodniona, obalona, nierozstrzygnięta albo błędna składniowo lub typowo. Brak dowodu nie jest fałszem. Jest pomiar powtórzeń i różnorodności.

## 6. Następny krok

Etap 8 miesza te werdykty w jednej eksploracji i zostawia zdania nierozstrzygnięte.
