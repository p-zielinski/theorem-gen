# Ciągła pętla Lean + SQLite

> Last updated: 2026-10-12
> Branch: `main`
> Status: done
> Audyt: `met_with_limitations` (`docs/continuous-ai-audit.md`), przebieg 2026-10-12

## Problem & goal

Pętla ma dać się zatrzymać i wznowić: propozycja → Lean 4 → status → SQLite. „Done” dla tej dostawy: schemat, kolejka, checkpoint, adapter Leana, curriculum od istniejącego `generate()` i trzy role dopiero po bramce poziomu 6. Nie twierdzimy, że model już rozwiązuje hipotezy. `learning` jest prawdziwe tylko wtedy, gdy zapisany champion bije baseline na held-out.

## Scope

- **In scope:** `theorem_gen/learn/`, testy, `docs/continuous-ai-*.md`, wskaźniki w README i `docs/architecture.md`.
- **Out of scope:** Mathlib, trzy kopie modelu w RAM, online fine-tune, cicha zmiana generatora etapów 0–8 i złotego `lean/TheoremGen/Generated.lean`.

## Key files & context

| Area | Path | Role |
|------|------|------|
| Architektura | `docs/continuous-ai-architecture.md` | Pętla, statusy, bramki, RAM |
| Schemat | `docs/continuous-ai-schema.sql` | Sklejone migracje 001–004 |
| Audyt | `docs/continuous-ai-audit.md` | Werdykt i macierz acceptance |
| Raport | `docs/continuous-ai-report.md` | Polecenia z tego przebiegu |
| Pamięć | `docs/continuous-ai-memory.md` | RSS płaszczyzny sterowania |
| Pakiet | `theorem_gen/learn/` | Store, kolejka, silnik, CLI |
| Testy | `tests/test_learn_*.py`, `tests/learn_support.py` | unittest, bez nowej zależności |
| Baza etapów 0–8 | `.cursor/work/lean-theorem-generator.md` | Zamknięta; ta pętla jej nie przepisuje |

## Decisions

- 2026-10-11: Status liczy `derive_outcome` wyłącznie z `validations`. Tekst roli nie jest wejściem.
- 2026-10-11: `quarantined` to defekt (dowód i certyfikat naraz), nie piąty synonim wyniku matematycznego.
- 2026-10-11: Jeden proces, jeden `ModelSlot`. Domyślny backend nie ładuje wag.
- 2026-10-11: Checkpoint 300–600 s, domyślnie 300. Zapis przez `os.replace`, wiersz `known_good` po podmianie pliku.
- 2026-10-11: Nowy bieg tylko od poziomu 1. Promocja wymaga 1000 ocen Leana, trzech okien i braku regresji held-out. `training_loss` jest ignorowany. Liczba 1000 nie rośnie z poziomem. Poziom 2 liczy tylko `generate_general`, poziom 3 jeden `wide_ast`, poziom 6 definicję i twierdzenie `double`. Poziomy 4 i 5 nie podnoszą progu.
- 2026-10-11: Role od poziomu 7. Alternate w fazie prove nie dostaje primary proof.
- 2026-10-11: `diversity` / `resource` w score baseline to stałe 1.0 generatora, nie pomiar sieci.
- 2026-10-11: Import odrzuca adapter pętli. `verify.py` etapów 0–8 nie dostał zakazu `import`.
- 2026-10-11: `Engine.promote_model` checkpointuje tylko promocję. Rollback challengera nie pisze snapshotu.
- 2026-10-11: LCG dostał `get_state` / `set_state` pod checkpoint. Sekwencja losowania bez tego wywołania się nie zmienia.
- 2026-10-11: Audyt dopisał migrację 002. Status startuje jako `unresolved` i musi zgadzać się z walidacjami. Źródło dowodu jest związane skrótem. Replay poziomu 7 bierze `raw_response`. Stałe `diversity=1` i `resource=1` nie włączają `learning`.
- 2026-10-11: Brak `lake` (`unavailable`) nie zamyka walidacji. Praca wraca do kolejki, bieg staje, CLI zwraca błąd. Kolejne `resume` może dokończyć te same kandydaty. Krok `unavailable` liczy się jako bezczynny.
- 2026-10-11: Drugi audyt. Przyjęty `check` ma `accepted=0` i zostawia `unresolved`. Timeout nie wchodzi do progu 1000. INSERT certyfikatu musi wskazywać tego samego kandydata. Wznowienie porównuje LCG i scheduler z plikiem snapshotu. Propozycja ma trzy próby, potem następny indeks. Bieg bez pierwszego checkpointu da się wznowić, jeśli nie ma jeszcze prac ani kandydatów. „is not a proposition” jest błędem typowania.
- 2026-10-12: CLI `start` i `resume` dokładają następną partię, gdy kolejka jest pusta, a budżet kroków jeszcze trwa. Testy crashy zostają przy jednym opróżnieniu kolejki. Replay skończonego budżetu powtarza ten budżet od checkpointu startu. Migracja 001 da się powtórzyć, gdy skrypt wykonał się bez wiersza wersji.
- 2026-10-12: Tożsamość kandydata jest niezmienna po insercie. Status i `updated_at` wolno przepisać. Frazy składni Lean 4.34.1 (`unexpected end of input`, `unexpected identifier`, `expected command`) są `syntax` i wygrywają z `unsolved goals`.
- 2026-10-12: Budżet kroków, który wypada w środku partii, kończy już zakolejkowane `lean_validate` i nie otwiera następnej partii. `--max-steps 0` nie woła Leana. Nieudana propozycja zostaje w kolejce.

## Progress

- [x] Architektura, schemat, handoff
- [x] SQLite, migracje, idempotencja, triggery
- [x] Kolejka, pauza, wznowienie, trzy punkty crasha, replay
- [x] Adapter Leana i klasyfikacja
- [x] Curriculum 1 na `generate()`, bramki do możliwości etapu 6
- [x] Trzy role jako pomoc etapu 7, po bramce
- [x] Retrieval, wybór korpusu, adjudicate challengera (bez trenowania wag)
- [x] Dokumenty ze zmierzonymi poleceniami

## Next steps

1. Nie podłączać trzech modeli. Ewentualny backend 7B–8B 4-bit ma wejść w ten sam `ModelSlot`.
2. LoRA tylko offline, tylko na `select_training_rows`, i tylko jeśli held-out challengera bije championa.
3. Nie ustawiać `learning: yes` ręcznie. Ma wyjść z `learning_claimed`.

## Blockers / open questions

- Brak wagi lokalnej. Pomiar RSS nie obejmuje procesu z modelem 7B.
- Pełne 1000 prawdziwych wywołań Leana na poziom nie było odpalane jako bieg produkcyjny. Bramka przyjętych dowodów jest sprawdzona na kohorcie. Osobna kohorta timeoutów nie promuje. Prawdziwy Lean: CLI `--max-steps 2 --count 1` dało dwa `proved`. Domyślny budżet `seed=1`, `count=4`, `max_steps=50` dał 52 `proved` i pustą kolejkę.
- Spójny wiersz `validations` wpisany SQL-em, z pominięciem adaptera, nadal ustawia status. Silnik tak nie zapisuje.
- Replay na świeżą bazę nie kopiuje zastanej kolejki. Kontynuacja żywej bazy to `resume`.

## Verification

```sh
export ELAN_HOME="$PWD/.toolchains/elan"
export PATH="$ELAN_HOME/bin:$PATH"
python3 -m unittest discover -s tests
python3 -m compileall -q theorem_gen tests
git diff --check
python3 -m theorem_gen.learn memory
```

Wynik 2026-10-12: `Ran 192 tests in 14.546s` / `OK`. Wcześniej tego dnia compileall, `git diff --check` i `lake --dir lean build` kod 0. Memory: `peak_rss_bytes: 16646144`, `weights_loaded: no`, kod 0. CLI `--max-steps 2 --count 1`: dwa `proved`, `learning: no`, replay od checkpointu 1 `replay_match: yes`. Domyślny budżet `seed=1`, `count=4`, `max_steps=50`: 52 `proved`, pusta kolejka, zero `failed`, `learning: no`. Szczegóły: `docs/continuous-ai-report.md`. Werdykt: `docs/continuous-ai-audit.md`.
