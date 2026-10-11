# Etap 8 — otwarta eksploracja

> Data ukończenia: 2026-10-11
> Status: ukończony

## 1. Zaimplementowany zakres

`explore(seed, count)` losuje bez zwracania cztery szablony, a po wyczerpaniu puli zaczyna ją od nowa. Ten sam seed daje tę samą listę.

| Szablon | Status | Znaczenie |
|---------|--------|-----------|
| `proved_add_zero` | `proved` | cytowanie zarejestrowanego `Nat.add_zero`; `discovered=False` |
| `refuted_lt` | `refuted` | `∀ a, a < a`, świadek `a = 0` |
| `bounded_le` | `no_proof` | `∀ a b, a ≤ a + b` mieści się w małym przeszukaniu i nie ma tu dowodu |
| `atom_p` | `unprovable_in_fragment` | atom `P` nie ma reguły w tym fragmencie |

`no_proof` nie jest obaleniem. `unprovable_in_fragment` mówi tylko o zarejestrowanym fragmencie, nie o niedowodliwości w matematyce.

Eksport cytowania zostawia twierdzenie jako `unverified`, dopóki Lean go nie sprawdzi. `theorem_from_proved` wypisuje `:= Nat.add_zero a`. Lean ten plik akceptuje.

Ziarno 1 i liczba 4 dają, w tej kolejności: `proved`, `refuted`, `no_proof`, `unprovable_in_fragment`. Inne ziarna zmieniają kolejność. Zbiór czterech statusów przy `count=4` jest pełny.

## 2. Testy

- `tests/test_stage8.py`: cztery statusy, rozdzielenie świadka, braku dowodu i fragmentu, rejestr cytowania, eksport nadal `unverified`, puste i ujemne `count`
- Lean: `test_cited_exploration_theorem_is_accepted`

## 3. Rzeczywiście uruchomione polecenia

Z katalogu repozytorium, po etapach 2–8:

```sh
python3 -m unittest discover -s tests -v
python3 -m theorem_gen generate \
  --seed 1 \
  --count 8 \
  --out lean/TheoremGen/Generated.lean \
  --verify \
  --timeout 120
python3 -m compileall -q theorem_gen tests
git diff --check
```

`lake build` wykonał test `test_package_build_accepts_the_generated_module` w tym samym zestawie. Lokalny elan ustawia `ELAN_HOME` na `.toolchains/elan`.

## 4. Wyniki

```text
Ran 133 tests
OK

generated 8 theorems
wrote lean/TheoremGen/Generated.lean
verification: proved
Lean accepted the file with exit code 0.
```

`compileall` i `git diff --check` kończą się kodem 0. Przykład etapu 1 pozostaje zgodny z generatorem.

Osobno, `explore(1, 4)`:

```text
explore_0000 proved witness=() deps=('lemma_Nat_add_zero',)
explore_0001 refuted witness=(('a', 0),) deps=()
explore_0002 no_proof witness=() deps=()
explore_0003 unprovable_in_fragment witness=() deps=()
```

## 5. Ograniczenia

Eksploracja ma cztery szablony, nie dowolną przestrzeń zdań. Status `proved` w wyniku eksploracji oznacza, że pasuje zarejestrowany lemat; twierdzenie w eksporcie i tak czeka na Leana. System nie obiecuje rozstrzygnięcia zdań spoza tych szablonów. Brak dowodu, fałsz i niedowodliwość we fragmencie pozostają trzema różnymi wynikami.

## 6. Ocena kryteriów

Kryterium etapu 8 jest spełnione. Po etapach 2–7 system tworzy zdania, których sam nie zawsze rozstrzyga, i nie utożsamia braku dowodu ani z fałszem, ani z niedowodliwością poza zarejestrowanym fragmentem.

## 7. Następny krok

Etapy 0–8 są zamknięte. Dalsza praca, jeśli miałaby powstać, dotyczyłaby nowych konstrukcji albo trwałego rejestru, a nie domknięcia tej serii.
