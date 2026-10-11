# Etap 3 — szersze AST

> Data ukończenia: 2026-10-11
> Status: ukończony

## 1. Zaimplementowany zakres

Do drzewa doszły: `IntLit`, `Var` (`Nat`, `Int`, `Prop`), `UnaryOp` (`succ`, `neg`), `Const`, `Atom`, `Implies`, `Forall`.

Niedozwolone kombinacje nie powstają i nie są przepisywane na inne znaczenie:

- `Nat + Int` → `TypingError` (`cannot apply add to Nat and Int`)
- `neg` na `Nat` i `succ` na `Int` → błąd typu
- `pred` → błąd, bo obcięty poprzednik na `Nat` zamienia 0 na 0
- stała `Nat` zastosowana do `Int` oraz atom zastosowany do zdania → błąd typu
- wolna zmienna i zdublowany binder w `Forall` → błąd

Eksport zachowuje kształt: `(Nat.succ 2)`, `((1 : Int) + (-1 : Int))`, `(-(1 : Int))`, `(P a)`. Generator konkretny etapu 1 tych konstrukcji nie losuje. Atom bez deklaracji Lean odrzuca; plik z samym `#check` nie staje się dowodem.

## 2. Testy

- `tests/test_stage3.py`: ewaluacja `succ`, eksport `succ`, `neg` i atomu, odrzucenie złych typów, `pred`, bindery, implikacja z `Nat` zamiast `Prop`
- Lean: `(Nat.succ 2) = 3`, `((1 : Int) + (-1 : Int)) = (0 : Int)` oraz `(-(1 : Int)) = (-1 : Int)` kończą się statusem `proved`. `#check` niezadeklarowanego atomu `P` kończy się błędem.

## 3. Polecenia i wyniki

Wspólny przebieg jest w [stage-8.md](stage-8.md). Test `test_succ_and_int_decide` przechodzi na Lean 4.34.1.

## 4. Ograniczenia

Nie ma odejmowania, dzielenia ani ogólnych twierdzeń o `Int` w generatorze. `Int` występuje w ręcznie zbudowanych drzewach i w eksporcie. `Atom` nie ma interpretacji w Leanie; nie jest wysyłany jako twierdzenie.

## 5. Ocena kryteriów

Kryterium etapu 3 jest spełnione: nowe konstrukcje mają testy typowania, eksportu i Leana, a zła kombinacja typów kończy się wyjątkiem.

## 6. Następny krok

Etap 4 zapisuje stabilne identyfikatory i zależności.
