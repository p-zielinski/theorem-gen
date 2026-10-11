# Theorem Gen

Deterministyczny generator twierdzeń w Lean 4. Python buduje typowane AST
i eksportuje wąski podzbiór Lean; Lean sprawdza dowody. Etapy 0–8 są
zaimplementowane. Domyślne CLI nadal tworzy konkretne twierdzenia o `Nat`.

## Wymagania

- Python 3.9+
- Lean 4.34.1 i Lake 5.0.0 przez elan

Repozytorium przypina wersję w `lean/lean-toolchain`. Jeżeli `elan` nie jest
zainstalowany, można utworzyć toolchain lokalny, bez zmiany `PATH` użytkownika:

```sh
export ELAN_HOME="$PWD/.toolchains/elan"
mkdir -p "$ELAN_HOME"
curl https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -sSf \
  | sh -s -- -y \
      --default-toolchain leanprover/lean4:v4.34.1 \
      --no-modify-path
export PATH="$ELAN_HOME/bin:$PATH"
```

## Generowanie i weryfikacja

Z katalogu repozytorium:

```sh
export ELAN_HOME="$PWD/.toolchains/elan"
export PATH="$ELAN_HOME/bin:$PATH"

python3 -m theorem_gen generate \
  --seed 1 \
  --count 8 \
  --out lean/TheoremGen/Generated.lean \
  --verify \
  --timeout 120
```

Oczekiwany koniec:

```text
verification: proved
Lean accepted the file with exit code 0.
```

Wynik znajduje się w `lean/TheoremGen/Generated.lean`.

## Testy

```sh
export ELAN_HOME="$PWD/.toolchains/elan"
export PATH="$ELAN_HOME/bin:$PATH"
python3 -m unittest discover -s tests -v
```

Zestaw zawiera testy jednostkowe i prawdziwe wywołania Lean. Jeśli Lean nie
jest dostępny, klasa integracyjna zostanie pominięta; nie jest to pełna
weryfikacja etapu.

Pełny build projektu Lean:

```sh
cd lean
export ELAN_HOME="$PWD/../.toolchains/elan"
export PATH="$ELAN_HOME/bin:$PATH"
lake clean
lake build
```

## Dokumentacja

- `docs/stage-0.md` — środowisko i decyzje techniczne
- `docs/architecture.md` — moduły i kontrakt weryfikacji
- `docs/stage-1.md` … `docs/stage-8.md` — raporty etapów
- `docs/stages.md` — kryteria ukończenia

Poza CLI dostępne są zdania ogólne (`generate_general`), definicja `double`,
ocena hipotez (`assess_hypothesis`) i eksploracja czterech szablonów
(`explore`). Brak dowodu, kontrprzykład i brak reguły we fragmencie to osobne
wyniki.
