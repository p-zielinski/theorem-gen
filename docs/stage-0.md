# Etap 0 — analiza i plan techniczny

> Data: 2026-10-11
> Status: ukończony

## Środowisko

Sprawdzone w katalogu repozytorium na maszynie `arm64`, Darwin 25.5.0:

| Narzędzie | Wynik |
|-----------|--------|
| Python | 3.9.6, `/usr/bin/python3` |
| git, curl, brew | dostępne |
| `lean`, `lake`, `elan` w `PATH` | brak |
| `~/.elan` | brak |

Lean nie był zainstalowany globalnie. Żeby nie zmieniać konfiguracji powłoki, elan został zainstalowany lokalnie w projekcie:

```sh
export ELAN_HOME="$PWD/.toolchains/elan"
curl https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -sSf \
  | sh -s -- -y --default-toolchain leanprover/lean4:v4.34.1 --no-modify-path
```

Po instalacji:

- Lean 4.34.1 (`arm64-apple-darwin24.6.0`, commit `5045d0056413`)
- Lake 5.0.0-src+5045d00

Katalog `.toolchains/` jest w `.gitignore`. Plik `lean/lean-toolchain` przypina tę samą wersję, więc `lake` potrafi ją pobrać także przy globalnym elan.

## Sonda dialektu Lean 4.34

Uruchomiono prawdziwy kompilator na krótkich plikach.

- `((2 + 3) = 5) := rfl`, `(((2 + 3) * 4) = 20) := rfl` i `((2 + 4) = (4 + 2)) := rfl` przechodzą.
- `(2 <= 5)` i `(2 < 5)` przechodzą jako `:= by decide`.
- `(1 = 0) := rfl` kończy się kodem 1. Komunikat zawiera `Not a definitional equality`, a potem osobną linię `Type mismatch` dla termu `rfl`. Klasyfikacja musi najpierw rozpoznać błąd dowodu, inaczej opisze go jako błąd typu.
- `True + 1` kończy się kodem 1 i `failed to synthesize` / `synthInstanceFailed`.
- Urwane `(1 = := rfl` kończy się kodem 1 i `unexpected token`.
- `:= sorry` kończy się kodem 0 i ostrzeżeniem `declaration uses sorry`. Sam kod wyjścia nie wystarcza, żeby uznać dowód.

Na tym macOS `resource.setrlimit(RLIMIT_AS, ...)` w Pythonie 3.9 rzuca `ValueError` (`RLIMIT_AS` i `RLIMIT_RSS` mają ten sam numer). Limit pamięci wirtualnej nie jest używany. Zostają limit czasu ściennego i `RLIMIT_CPU` w procesie potomnym.

## Podział Python / Lean

Python trzyma generator, typowane drzewo, ziarno, eksport ograniczonego podzbioru i uruchomienie procesu. Testy tej części nie wymagają kompilatora.

Lean 4 jest jedynym sędzią poprawności dowodu. Nie ma własnego parsera Leana ani heurystyki, która z tekstu komunikatu wnioskuje, że twierdzenie jest prawdziwe. Tekst komunikatu służy tylko do opisu błędu i do odrzucenia `sorry`, które kompilator i tak akceptuje z kodem 0.

Mathlib nie wchodzi do etapu 1. Konkretne twierdzenia o `Nat` z `+`, `*` i porównaniami mieszczą się w prelude.

## Minimalny zakres etapu 1

Jest w kodzie:

- literały `Nat`, dodawanie, mnożenie, `=`, `<=`, `<`
- twierdzenie konkretne: wyrażenie typu `Prop` plus metoda dowodu `rfl` albo `decide`
- generator sterowany ziarnem i konfiguracją
- eksport modułu Lean
- weryfikacja procesem `lake env lean` z limitem czasu

Poza zakresem etapu 0, dopisane później w etapach 2–8:

- zmienne, kwantyfikatory, implikacje
- szersze AST
- rejestr zależności i cykle
- sterowanie złożonością
- definicje
- hipotezy
- otwarta eksploracja

W samym etapie 1 eksporter przyjmował rodzaj `concrete`. Późniejsze rodzaje mają własne ścieżki eksportu i nie są cicho tłumaczone na konkretny dowód.

## Struktura katalogów

```
theorem_gen/          generator w Pythonie
tests/                unittest
lean/                 projekt Lake (weryfikacja)
docs/                 architektura, etapy, raporty
.toolchains/elan/     lokalny Lean, poza gitem
```

## Interfejs

Konfiguracja `GeneratorConfig`: `seed`, `count`, `max_literal`, `max_depth`, `max_value`, `unique`, `rules`, `max_attempts`.

`generate(config)` zwraca listę twierdzeń. Ten sam config daje ten sam wynik. Przy jednej regule generator nie zużywa losowania na jej wybór. Generator liczb to 32-bitowy LCG (mnożnik `1664525`, przyrost `1013904223`), niezależny od wersji `random` w Pythonie.

Eksport: `export_module(theorems, config)` — plik z komentarzem konfiguracji i twierdzeniami.

Weryfikacja: `verify_source` / `verify_theorems`. Statusy: `proved`, `failed`, `timeout`, `unavailable`. Klasa błędu, gdy status to `failed`: `syntax`, `typing`, `proof`, `rejected`, `other`.

Uruchomienie testów z katalogu repozytorium:

```sh
python3 -m unittest discover -s tests -v
```

Przykład:

```sh
export ELAN_HOME="$PWD/.toolchains/elan"
export PATH="$ELAN_HOME/bin:$PATH"
python3 -m theorem_gen generate --seed 1 --count 8 --out lean/TheoremGen/Generated.lean --verify
```

## Kryteria ukończenia

Zapisane w [stages.md](stages.md). Etap 0 jest zamknięty tą notatką i
[architecture.md](architecture.md). Etap 1 został następnie zrealizowany i
opisany w [stage-1.md](stage-1.md).
