# Audyt ciągłej pętli Lean AI

> Data: 2026-10-12. Gałąź: `main`.
> Werdykt: `met_with_limitations`

Audyt szedł od kodu i od poleceń uruchomionych w tym przebiegu. Poprzedni raport nie był werdyktem. Po czytaniu ścieżki statusu znalazły się dwie luki: tożsamość kandydata dało się przepisać pod już policzonym statusem, a prawdziwe komunikaty składni Lean 4.34.1 zostawiały kandydata jako `unresolved`. Obie są poprawione i pokryte testami.

## Odpowiedzi

Silnik nie zapisze fałszywego `proved` ani `refuted`. Tekst roli, świadek Pythona bez zgodnej tezy, timeout, konstrukcja zabroniona, plik o innym skrócie niż `bound_source`, niespójna para `accepted` / `result`, przyjęty `check` i podmiana tezy po insercie nie ustawiają tych statusów. `current_status` da się ustawić tylko na wartość wyprowadzoną z `validations`. `accepted=1` wymaga `result='accepted'` i typu `proof` albo `counterexample`.

Osobna ścieżka zostaje: proces z dostępem do pliku SQLite może wstawić spójny wiersz `validations` (`accepted=1`, `result='accepted'`, typ `proof` albo `counterexample`) bez uruchomienia Leana. Status pójdzie za tym wierszem. Tak działa fixture kohorty 1000. CLI tej ścieżki nie używa.

Pause, resume i replay są odporne na trzy wymagane punkty crasha oraz na czwarty, po `os.replace`, a przed wierszem `known_good`. Resume nie gubi ani nie dubluje `attempts`. Osierocony plik checkpointu nie staje się `known_good`. Scheduler zatwierdzony razem z propozycją jest dosuwany zdarzeniem `scheduler_committed`. Replay poziomu 7 woła zapisane `raw_response`. Poziom 1 ma zero wywołań modelu, bo propozycja jest z generatora. Podmieniony `rng_state` w wierszu checkpointu jest odrzucany, gdy plik snapshotu ma inne ziarno. Suite, który te punkty wykonuje, zakończył się `OK`.

Nie wolno pisać, że system się uczy. W tym przebiegu nie załadowano wag. `learning_claimed` zostaje fałszem, dopóki champion i baseline mają jednocześnie stałe `diversity=1` i `resource=1`, albo dopóki aktywna wersja to `champion-generator-v0`. CLI wydrukowało `learning: no`.

## Ustalenia

### medium — tezę dało się podmienić pod statusem `proved`

Trigger `candidates_status_matches_validations` w `theorem_gen/learn/migrations/002_integrity.sql` pilnuje tylko `current_status`. `UPDATE` kolumny `canonical_ast_json`, `structural_hash`, `proof_method` albo `ast_size` przechodził. Po prawdziwym dowodzie dało się wpisać inną tezę albo podnieść `ast_size`, a status zostawał.

Reprodukcja: po `upsert_candidate` wykonać `UPDATE candidates SET canonical_ast_json='{"rewritten":true}'`. Przed migracją 004 SQLite przyjmowało ten zapis.

Testy tego nie widziały. Sprawdzały wstawienie `proved` bez walidacji i `UPDATE` samego statusu. Nie próbowały przepisać tezy.

Poprawka: `theorem_gen/learn/migrations/004_identity.sql`. Przy `UPDATE` wolno zmienić `current_status` i `updated_at`. Reszta tożsamości i metryk bramki jest zamrożona. `docs/continuous-ai-schema.sql` jest sklejką migracji 001–004.

### medium — składnia Lean 4.34.1 zostawała `unresolved`

`classify_lean_failure` w `theorem_gen/verify.py` szukało `unexpected token`, `expected term` i `expected token`, i robiło to po kubełku dowodu (`unsolved goals`). Prawdziwy plik `theorem bad : (0 = 0) :=` daje `unexpected end of input` i klasę `other`. Plik `this is not lean` daje `unexpected identifier; expected command`. Plik z `???` w taktyce daje naraz `unsolved goals` i `unexpected token`, więc wygrywał kubełek dowodu. `derive_outcome` dla klasy `other` albo `proof` zostawia `unresolved`, nie `ill_formed`.

Reprodukcja: `validate_source` tych trzech źródeł na Lean 4.34.1, przed zmianą kolejności fraz.

Testy tego nie widziały. Atrapa składni podawała dokładnie `unexpected token` / `expected term`. Nie puszczała komunikatu, który emituje ten Lean.

Poprawka: frazy `unexpected end of input`, `unexpected identifier` i `expected command` są składnią, i składnia jest sprawdzana przed `unsolved goals`. `Unknown identifier` zostaje klasą `other` — ten podział jest w teście `test_syntax_and_typing_are_separate_from_proof` i nie został ruszony. Prawdziwy Lean w `test_real_lean_accepts_a_proof_and_a_negation_certificate` sprawdza urwany dowód i plik, który nie jest Leanem.

## Co zostało sprawdzone i trzyma się

- `proved` i `refuted` wychodzą z `derive_outcome` tylko przy `accepted` i `result='accepted'` oraz typie `proof` albo `counterexample`. Trigger przy UPDATE statusu liczy to samo.
- Kandydat startuje jako `unresolved`. Przyjęty `check` ma `accepted=0` i zostaje `unresolved`. Timeout i `unavailable` nie wchodzą do progu 1000.
- Źródło `proof` i `check` musi mieć skrót w niezmiennym zdarzeniu `bound_source`. Kontrprzykład jest liczony od nowa z przypisania i tezy tego kandydata. Certyfikat przy INSERT i UPDATE musi wskazywać przyjętą walidację `counterexample` tego samego kandydata.
- `sorry`, `axiom`, `opaque`, `unsafe`, `#eval`, `run_io`, `run_cmd` i `import` na początku linii są odrzucane, zanim wystartuje proces. `admit` nie jest na liście słów. Lean 4.34.1 kończy je kodem 0 z ostrzeżeniem incomplete proof i adapter nie stawia `proved`. `sorryAx` nie przechodzi filtra słowa `sorry`, ale Lean odrzuca je jako typing, więc nie ma `proved`.
- `quarantined` powstaje tylko przy jednoczesnym przyjętym dowodzie i przyjętym certyfikacie. `mathematical_outcome` zwraca `None`.
- WAL, `foreign_keys` i `busy_timeout` są ustawiane przy połączeniu. Migracje 1–4 są pomijane, gdy wersja jest w `schema_migrations`. Skrypt wykonany bez wiersza wersji da się dokończyć (`IF NOT EXISTS` w 001, powtórka 002–004). Dwa połączenia na tym samym kluczu idempotencji zwracają jeden wiersz.
- Kolejka: priorytet walidacji nad propozycją, high-water, dzierżawa, heartbeat, reclaim po wygaśnięciu, backpressure cofa cały scheduler łącznie z `last_mix` i nie zatrzymuje prac Leana. Błąd propozycji ma trzy próby, potem następny indeks. `unavailable` wraca do kolejki i jest krokiem bezczynnym.
- Checkpoint: interwał 300–600 s, `os.replace`, potem wiersz `known_good`. Weryfikacja porównuje skrót pliku oraz LCG, scheduler, kursor, poziom i flagę zamrożenia. Crash po `os.replace` zostawia poprzedni `known_good`.
- Curriculum: nowy bieg od poziomu 1, bez przeskoków, próg 1000, trzy pełne okna, `training_loss` nie jest wejściem, jedna promocja na okno, nieudana bramka nie kasuje walidacji, role od poziomu 7. Liczebnik nie jest miarą trudności. Kohorta timeoutów nie promuje.
- Role: proposer nie zapisuje werdyktu, prover dostaje tylko AST, alternate w fazie `prove` dostaje `primary=None`, krytyka widzi oba artefakty, retrieval zwraca `stable_id`, status i rodzinę. Jeden `ModelSlot` nie trzyma drugiej rezydentnej kopii. Tekst `{"verdict":"proved"}` nie zmienia statusu.
- Held-out nie wchodzi do `select_training_rows`. Cap potomków to 8. Balans idzie po rodzinie, wyniku i paśmie `ast_size`. Słabszy challenger jest `rolled_back` i nie pisze checkpointu promocji.
- CLI `start` i `resume` dokładają następną partię, gdy kolejka jest pusta, a budżet kroków jeszcze trwa. Klucz propozycji, który nie jest `queued`, nie jest wstawiany drugi raz. Replay skończonego budżetu od checkpointu startu powtarza ten budżet. Bieg `--until-pause` przy replay nie wchodzi w pętlę bez końca.
- `python3 -m theorem_gen generate` do pliku tymczasowego kończy się kodem 0. Złoty `lean/TheoremGen/Generated.lean` nie jest w `git status`. Różnica w `theorem_gen/verify.py` wobec `HEAD` to wcześniejsze pierwszeństwo frazy „is not a proposition” oraz, w tym audycie, frazy składni. Generator etapów 0–8 nie dostał innego werdyktu na przyjętym dowodzie.

## Macierz acceptance

| # | Test | Wynik |
|---|------|--------|
| 1 | Istniejący unittest zostaje zielony | pass — `Ran 192 tests in 14.546s`, `OK` |
| 2 | Migracje, FK, transakcje, idempotencja | pass |
| 3 | Zgoda ról nie oznacza odrzuconego pliku jako `proved` | pass |
| 4 | Świadek Pythona bez certyfikatu → `unresolved` | pass |
| 5 | Certyfikat Leana → `refuted` | pass — prawdziwy `Not (1 = 0)` |
| 6 | Składnia / typing → `ill_formed`; timeout → `unresolved` | pass — po poprawce fraz; `Unknown identifier` zostaje `unresolved` |
| 7 | Trzy punkty crasha, zero duplikatów | pass — suite wykonuje haki dequeue, commit i zapis checkpointu |
| 8 | Pause i resume odtwarzają scheduler oraz LCG | pass |
| 9 | Wygasła dzierżawa i backpressure | pass |
| 10 | Zajętość ≥ 80%, gdy jest praca | pass jako licznik kroków, nie CPU |
| 11 | Curriculum nie awansuje wcześnie ani z `training_loss` | pass na kohorcie, nie na tysiącu wywołań `lake` |
| 12 | Słabszy challenger jest wycofywany | pass |
| 13 | Replay bez żywego modelu odtwarza wyniki | pass od checkpointu startu; poziom 7 bierze `raw_response` |
| 14 | Szczyt RSS inferencji, workerów i Leana w budżecie 18 GB | not_measured dla procesu z wagami; płaszczyzna sterowania: `16646144` bajtów, `within_budget: yes` |
| 15 | Zabronione konstrukcje odrzucone mimo zgody ról | pass — runner nie startuje; prawdziwy Lean potwierdził odmowę i `admit` |
| 16 | Raport z faktycznie odpalonych poleceń | pass — `docs/continuous-ai-report.md` |

## Polecenia tego przebiegu

```sh
export ELAN_HOME="$PWD/.toolchains/elan"
export PATH="$ELAN_HOME/bin:$PATH"
python3 -m unittest discover -s tests
python3 -m compileall -q theorem_gen tests
git diff --check
lake --dir lean build
lean --version
lake --version
python3 -m theorem_gen.learn memory
python3 -m theorem_gen generate --seed 1 --count 1 --out "$TMP/Generated.lean"
python3 -m theorem_gen.learn start|status|pause|resume|replay …
```

Wyniki: unittest `192` / `14.546s` / `OK` po domknięciu partii. Wcześniej tego dnia compileall i `git diff --check`: kod 0. Lake: `Build completed successfully (4 jobs).` Lean `4.34.1`, Lake `5.0.0-src+5045d00`. Memory: kod 0, `peak_rss_bytes: 16646144`, `weights_loaded: no`. Generate: kod 0, zapis do pliku tymczasowego. CLI `start --max-steps 2 --count 1`: dwa `proved`, `learning: no`, kod 0. `replay --from-checkpoint 1`: `replay_match: yes`. Błędne argumenty: tabelka w `docs/continuous-ai-report.md`. Silnik, ten sam kształt co `start` bez `--max-steps`: 52 `proved`, pusta kolejka, zero `failed`, `learning: no`.

`git status` rozdziela warstwy. Śledzone różnice sprzed tej pętli to `theorem_gen/rng.py` i `tests/test_rng.py` (`get_state` / `set_state`), wpisy w `README.md` i `docs/architecture.md`, `var/` w `.gitignore` oraz skrót next steps w `.cursor/work/lean-theorem-generator.md`. Śledzone `theorem_gen/verify.py` i `tests/test_verify.py` niosą klasyfikację „is not a proposition” oraz fraz składni z tego audytu. Pakiet `theorem_gen/learn/`, testy `tests/test_learn_*.py` i dokumenty `docs/continuous-ai-*` są nienadzorowane. Złoty `lean/TheoremGen/Generated.lean` nie jest w różnicy.

## Poprawki

- `theorem_gen/learn/migrations/004_identity.sql` i sklejka w `docs/continuous-ai-schema.sql`
- `classify_lean_failure`: składnia Lean 4.34.1 przed kubełkiem `unsolved goals`
- testy tożsamości kandydata, fraz składni i prawdziwego Leana na urwany plik
- architektura, raport, pamięć i ten plik opisują ten przebieg
- budżet kroków kończy już zakolejkowane `lean_validate` i nie otwiera następnej partii; `--max-steps 0` kolejki nie rusza

## Ograniczenia, które zostają

- Kohorta 1000 to fixture o kształcie przyjętej walidacji. Osobna kohorta timeoutów sprawdza, że sam timeout nie promuje. Prawdziwy Lean: pojedyncze pliki, krótki CLI (`--max-steps 2 --count 1`) oraz domyślny budżet 50 kroków przy `count=4` (52 `proved`, pusta kolejka, zero prac `failed`). Tysiąc wywołań `lake` na poziom nie było odpalane.
- Spójny wiersz `validations` wpisany SQL-em, z pominięciem adaptera, nadal niesie status. Silnik tak nie zapisuje. Ten sam proces może dopisać zdarzenie `bound_source`, więc trigger „musi istnieć skrót” nie zamyka tej ścieżki.
- Replay na świeżą bazę odtwarza bieg od schedulera, LCG i `attempt_cursor`. Nie kopiuje zastanej kolejki. Kontynuacja żywej bazy to `resume`. Replay od checkpointu pauzy startuje z LCG zapisanym po zakończonych partiach i dostaje kolejne twierdzenia. Odtworzenie biegu idzie od checkpointu startu.
- Zajętość jest ułamkiem kroków. Krok oddanej, niedostępnej albo nieudanej pracy liczy się jako bezczynny. Pętla nie woła `heartbeat` w trakcie blokującego wywołania Leana. Jeden proces i tak kończy dzierżawę w `complete`, bo w pętli nie ma `reclaim_expired`. Drugi proces na tej samej bazie nie jest obsługiwany.
- RSS `16646144` to ten proces bez wag 7B i bez obciążenia Leana.
- `verify.py` etapów 0–8 nadal nie odrzuca `import`. Odrzuca go adapter pętli, zanim zawoła `verify_source`.
- `Unknown identifier` zostaje klasą `other` i statusem `unresolved`. To nie jest `proved`.
- `admit` nie jest na liście słów. Lean zgłasza je jako incomplete proof i adapter nie stawia `proved`.
