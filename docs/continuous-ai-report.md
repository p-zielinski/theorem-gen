# Raport dostawy pętli

> Data: 2026-10-12. Katalog: korzeń repozytorium. Gałąź: `main`.
> Liczby poniżej pochodzą z audytu tego dnia, po migracji 004, poprawce klasyfikacji składni i domknięciu partii uciętej budżetem.

Środowisko Leana:

```sh
export ELAN_HOME="$PWD/.toolchains/elan"
export PATH="$ELAN_HOME/bin:$PATH"
lake --version
lean --version
```

```
Lake version 5.0.0-src+5045d00 (Lean version 4.34.1)
Lean (version 4.34.1, arm64-apple-darwin24.6.0, commit 5045d0056413266e57c625dcd7c365b10e377c52, Release)
```

`lake --dir lean build` zakończyło się komunikatem `Build completed successfully (4 jobs).` Kod 0.

## Testy

```sh
python3 -m unittest discover -s tests
```

```
Ran 192 tests in 14.546s
OK
```

Kod 0. W zestawie jest prawdziwy Lean 4.34.1: dowód `0 = 0`, certyfikat `Not (1 = 0)`, odrzucenie `Not (0 = 0)`, błąd typowania `theorem bad : Nat := rfl` (`ill_formed`), składnia `theorem bad : (0 = 0) :=` i `this is not lean` (`ill_formed`), przyjęta definicja `double` jako `check` z `accepted=0`, oraz timeout 2 s na `repeat (first | done | skip)` (`timeout`, `accepted` fałsz).

```sh
python3 -m compileall -q theorem_gen tests
git diff --check
```

Oba polecenia zakończyły się kodem 0.

`python3 -m theorem_gen generate --seed 1 --count 1 --out "$TMP/Generated.lean"` zakończyło się kodem 0 (`generated 1 theorems`). Złoty `lean/TheoremGen/Generated.lean` nie był celem zapisu i nie pojawia się w `git status`.

## Pamięć

```sh
python3 -m theorem_gen.learn memory
```

Kod 0. `peak_rss_bytes: 16646144`, `within_budget: yes`, `weights_loaded: no`, `resident_copies: 0`. Pełny wydruk: `docs/continuous-ai-memory.md`.

## Krótki bieg Leana

```sh
python3 -m theorem_gen.learn start --run-id smoke --curriculum 1 \
  --db "$DB" --seed 1 --count 1 --max-steps 2
```

Kod 0. Dwa kandydaty, oba `proved`. `learning: no`. `checkpoint_seq: 2`. `event_cursor: 9`.

```sh
python3 -m theorem_gen.learn replay --run-id smoke --db "$DB" --from-checkpoint 1
```

```
replay_match: yes
```

Kod 0. `resume --max-steps 0` i `pause` też kończą się kodem 0.

| Polecenie | Kod | Komunikat |
|-----------|-----|-----------|
| `start --curriculum 4` | 1 | `a new run starts at curriculum level 1` |
| `replay --from-checkpoint 99` | 1 | `checkpoint not found` |
| ponowny `replay --from-checkpoint 1` | 1 | `replay database already exists: …/learn-replay.sqlite` |
| `status --run-id missing` | 1 | `unknown run missing` |
| `start --checkpoint-interval 10` | 1 | `checkpoint interval must be between 300 and 600 seconds` |
| ponowny `start` tego samego biegu | 1 | `run already exists; use resume` |
| `status` na pliku, który nie jest bazą SQLite | 1 | `file is not a database` |
| `theorem_gen.learn nosuch` | 2 | argparse: `invalid choice: 'nosuch'` |

Prawdziwy Lean w tym przebiegu, przez `validate_source`: `0 = 0` → `proved`; `1 = 0 := rfl` → `unresolved`; `Not (1 = 0)` → `refuted`; `Not (0 = 0)` → `unresolved`; `theorem bad : Nat` → `ill_formed` / `typing`; `theorem bad : (0 = 0) :=` i `this is not lean` → `ill_formed` / `syntax`; `def double` → `check`, `accepted=0`, `unresolved`; timeout 2 s → `timeout`, `unresolved`. `sorry`, `axiom`, `opaque`, `unsafe`, `#eval`, `run_io`, `run_cmd` i `import` są odrzucane przed procesem (`failure_class=rejected`). `admit` kończy się kodem 0 z ostrzeżeniem sorry i nie jest `proved`. `sorryAx` Lean odrzuca jako typing.

Domyślny budżet, ten sam kształt co `start` bez `--max-steps` (`seed=1`, `count=4`, `max_steps=50`, `refill_when_idle`), na Lean 4.34.1: 52 kandydatów, wszyscy `proved`, zero prac w kolejce, zero prac `failed`, `learning: no`, poziom 1, `advancement_frozen` wyłączone, checkpoint 2, `event_cursor` 120. Budżet wypada w środku trzynastej partii; pętla kończy te cztery walidacje i nie otwiera czternastej. Osobny bieg `--max-steps 2 --count 4` dał 4 `proved` i pustą kolejkę. `--max-steps 0` nadal nie woła Leana.

## Czego ten przebieg nie pokazuje

Nie załadowano modelu 7B–8B. Nie liczono RSS inferencji razem z workerami Leana pod obciążeniem wag. Zajętość ≥ 80% w teście jest licznikiem kroków schedulera, kiedy kolejka ma pracę, a nie procentem CPU systemu. Bramka 1000 kandydatów jest sprawdzona na kohorcie z walidacją o kształcie przyjętego dowodu oraz na osobnej kohorcie timeoutów, która nie promuje. Tysiąc osobnych wywołań `lake` na poziom nie było odpalane. CLI `--max-steps 2 --count 1` to dwa `proved`. Domyślne 50 kroków przy `count=4` to 52 `proved`. `learning: no` jest zgodne z definicją: w tym procesie champion nie pobił baseline pomiarem innym niż stałe generatora.
