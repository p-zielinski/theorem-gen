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
- `docs/prompts/audit-lean-generator.md` — prompt niezależnego audytu etapów 0–8
- `docs/prompts/build-continuous-lean-ai.md` — prompt ciągłego AI + SQLite + Lean
- `docs/continuous-ai-architecture.md` — pętla `theorem_gen.learn` (pamięć eksperymentu, nie wytrenowany model)
- `docs/continuous-ai-schema.sql` — schemat SQLite
- `docs/continuous-ai-report.md` — polecenia faktycznie uruchomione w tej dostawie

Poza CLI dostępne są zdania ogólne (`generate_general`), definicja `double`,
ocena hipotez (`assess_hypothesis`) i eksploracja czterech szablonów
(`explore`). Brak dowodu, kontrprzykład i brak reguły we fragmencie to osobne
wyniki.

Słowo `proved` ma trzy różne znaczenia — nie wolno ich mieszać:

| Gdzie | Znaczenie |
|-------|-----------|
| `VerificationReport.status` | Lean zaakceptował plik |
| `HypothesisAssessment.status` | ocena hipotezy po Lean / kontrprzykładzie |
| `ExplorationResult.status` | cytowanie zarejestrowanego lematu |

`ExplorationResult.status == "proved"` **nie** jest `claimed_true`. Eksport z
`theorem_from_proved` zostaje `unverified`, dopóki Lean nie sprawdzi pliku.
`claimed_true(theorem)` wymaga `verification == "proved"` **oraz** niepustego
dowodu.

## Pętla ciągła

`python3 -m theorem_gen.learn` zapisuje kandydatów w SQLite i prosi Leana 4.34.1 o werdykt. Status `proved` albo `refuted` bierze się wyłącznie z walidacji Leana. Domyślny generator `python3 -m theorem_gen generate` działa osobno i nie czyta tej bazy. Ten bieg nie ładuje wag modelu. `learning: yes` pojawia się dopiero wtedy, gdy zapisany champion pobije baseline na stałym zbiorze held-out. Szczegóły: `docs/continuous-ai-architecture.md`.

Z katalogu repozytorium, ta sama zmienna `ELAN_HOME` co przy generowaniu:

```sh
export ELAN_HOME="$PWD/.toolchains/elan"
export PATH="$ELAN_HOME/bin:$PATH"

python3 -m theorem_gen.learn start --run-id run-1 --until-pause
```

Domyślnie: baza `var/learn.sqlite` (katalog `var/` jest w `.gitignore`), curriculum 1, ziarno 1, cztery twierdzenia w partii, timeout Leana 60 s, checkpoint co 300 s. `--until-pause` zdejmuje limit 50 kroków. Proces pracuje, aż dostanie SIGINT albo SIGTERM.

Stan bazy, także gdy pętla trwa:

```sh
python3 -m theorem_gen.learn status --run-id run-1
```

Zatrzymanie żywego procesu to Ctrl-C albo `kill -TERM` na jego PID. Sygnał nie ucina wywołania Leana w połowie: pętla kończy bieżący krok (najwyżej tyle, ile wynosi `--timeout`), zwalnia dzierżawy, zapisuje checkpoint pauzy i kończy się kodem 0. Drugiego `start` albo `resume` na tej samej bazie nie wolno odpalać, dopóki pierwszy proces żyje.

Kontynuacja tego samego biegu:

```sh
python3 -m theorem_gen.learn resume --run-id run-1
```

Bieg założony z `--until-pause` wznawia się znowu do następnego sygnału. Jawne `--max-steps` na `resume` ogranicza tylko to wznowienie. Prace zostawione w kolejce są dokańczane; nowe partie dochodzą, gdy kolejka jest pusta. `SIGKILL` nie pisze checkpointu pauzy. `resume` wraca wtedy do ostatniego znanego checkpointu (start albo interwał 300 s) i przejmuje osierocone dzierżawy.

Odtworzenie od checkpointu startu, na osobnej bazie `var/learn-replay.sqlite`:

```sh
python3 -m theorem_gen.learn replay --run-id run-1 --from-checkpoint 1
```

To powtórzenie zapisanego biegu, nie kontynuacja. Kontynuacja żywej bazy to `resume`.
