# Etap 5 — złożoność

> Data ukończenia: 2026-10-11
> Status: ukończony

## 1. Zaimplementowany zakres

`measure_expr` i `measure_theorem` liczą:

- `ast_size`
- `depth`
- `variables`
- `operators`
- `dependencies`
- `definitions`

`NatLit(1)` i `NatLit(10**12)` mają ten sam rozmiar i tę samą głębokość. Wielkość liczebnika nie jest miarą. Zdanie z kwantyfikatorem jest większe niż sam duży liczebnik.

`GeneratorConfig.complexity_bounds` filtruje kandydatów `generate` i `generate_general`. Para `(low, high)` z `low > high` jest odrzucana przy tworzeniu konfiguracji. Granica, której żaden kandydat nie spełnia, kończy się `GenerationError` i tekstem, że to limit generowania, a nie werdykt matematyczny.

Generator trafia w każdą z sześciu miar:

- `ast_size` 5–5 i `variables` 0–0 dla `add_zero` zostawia `((8 + 0) = 8)`
- `depth` 2–2 i `operators` 1–1 też zostawia to zdanie; `operators` 0–0 wybiera `(8 <= 8)`
- `variables` 1–1 wybiera `add_zero_all`, a 2–2 wybiera `add_comm_all`
- `dependencies` 1–1 i `definitions` 1–1 przy regule `use_definition` wybiera twierdzenie o `double`; cytowanie ma `discovered=False`

Gdy wszystkie kandydaty `add_zero` mieszczą się w `ast_size` 5–5 i `variables` 0–0, ziarno 1 nadal daje `((8 + 0) = 8)` i `((7 + 0) = 7)`. Nagłówek konkretny pozostaje przy banerze etapu 1 i dopisuje linię `complexity`.

Liczba definicji bez rejestru liczy węzły `Const`. Z rejestrem liczy zależności, których rekord ma rodzaj `definition`.

## 2. Testy

`tests/test_stage5.py`: wielkość liczebnika, trafienie w granice, niemożliwa granica, granica zmiennych, odwrócona para, zależność definicyjna.

## 3. Polecenia i wyniki

Wspólny przebieg jest w [stage-8.md](stage-8.md).

## 4. Ograniczenia

Filtr granic działa w `generate` i `generate_general`. `explore` ma stałe cztery szablony i nie czyta tych granic. Miary są strukturalne: nie oceniają trudności dowodu w Leanie. Reguła `use_definition` nie wchodzi do domyślnego zestawu etapu 1.

## 5. Ocena kryteriów

Kryterium etapu 5 jest spełnione: generowanie umie utrzymać się w zadanym zakresie kilku miar, a duża liczba nie jest automatycznie trudniejsza.

## 6. Następny krok

Etap 6 dodaje definicję i twierdzenie, które z niej korzysta.
