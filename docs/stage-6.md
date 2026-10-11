# Etap 6 — definicje

> Data ukończenia: 2026-10-11
> Status: ukończony

## 1. Zaimplementowany zakres

`Definition` ma identyfikator, nazwę, parametry, ciało i typ wyniku. `validate_definition` sprawdza, że parametry są zmiennymi, nazwy się nie powtarzają, typ ciała zgadza się z deklaracją, nie ma wolnych zmiennych spoza parametrów i ciało nie woła samej definicji.

Obsługiwany przykład:

```lean
def double (n : Nat) : Nat := (n + n)

theorem gen_double_zero : ((double 0) = 0) := rfl
```

Twierdzenie zależy od `def_double`, ma regułę `use_definition` i `discovered=False`. Lean akceptuje ten plik.

Odrzucane są: wolna zmienna, ciało `Nat` przy deklaracji `Int` oraz `Const("double", …)` w ciele `double`.

## 2. Testy

- `tests/test_stage6.py`: walidacja, eksport, rejestr
- Lean: `test_definition_and_dependent_theorem` daje `proved`

## 3. Polecenia i wyniki

Wspólny przebieg jest w [stage-8.md](stage-8.md).

## 4. Ograniczenia

Fragment nie obejmuje rekursji, definicji zdaniowych ani definicji zależnych od innych definicji poza jednym przykładem `double`. Eksporter nie naprawia niepoprawnej definicji.

## 5. Ocena kryteriów

Kryterium etapu 6 jest spełnione: definicja jest sprawdzana, twierdzenie z niej korzysta, zależność jest zapisana, a Lean akceptuje plik.

## 6. Następny krok

Etap 7 ocenia hipotezy osobno od generowania dowodu.
