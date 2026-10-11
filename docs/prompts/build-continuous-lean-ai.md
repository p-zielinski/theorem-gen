# Prompt: ciągle rozwijane AI nad generatorem Lean 4

Skopiuj cały blok poniżej (od `Jesteś senior engineerem…` do końca bloku) jako pełne polecenie implementacyjne. Ten prompt **nie** obiecuje, że model „rozwiąże każdą matematykę”. Buduje system, który może się uczyć długo, z pauzą/wznowieniem, Leanem jako arbitrem i SQLite jako pamięcią.

Uwaga dla autorów Markdown: blok jest w fence `text` czterema backtickami, żeby wewnętrzne przykłady poleceń nie ucinały copy-paste.

````text
Jesteś senior engineerem Python + Lean 4 + ML systems.
Rozszerz istniejący projekt w bieżącym katalogu repozytorium (root z docs/,
theorem_gen/, tests/, lean/). Nie zakładaj absolutnej ścieżki użytkownika.

Cel długoterminowy: model AI, który ciągle się uczy na pętli
generowanie → walidacja Lean 4 → klasyfikacja wyniku → zapis w SQLite,
z możliwością zatrzymania i wznowienia w dowolnym momencie.
Docelowa aspiracja (po bardzo długiej nauce): coraz lepsze rozwiązywanie
zadań matematycznych i hipotez. NIE twierdź, że system już to umie.
Nie obiecuj pełnej automatyzacji ani „rozwiąże każdą hipotezę”.

## Kontekst istniejącego kodu (zachowaj)

- Traktuj etapy 0–8 jako bazę TYLKO po zielonym audycie z lake
  (nie incomplete_without_lean). W przeciwnym razie najpierw napraw bazę
  albo uruchom docs/prompts/audit-lean-generator.md.
- Python buduje typowane AST; Lean 4.34.1 sprawdza dowody (bez Mathlib).
- Domyślny CLI generate() nadal produkuje konkretne Nat.
- Istnieją: generate, generate_general, registry, complexity, definitions,
  assess_hypothesis, explore, verify_source.
- Istniejące testy (unittest, 134) muszą pozostać zielone.
- Preferuj typed AST + istniejący exporter zamiast dowolnego tekstu Lean od modelu.
- TDD, małe fazy, dokumentacja odzwierciedlająca faktyczny kod.
- Nie pytaj użytkownika; przy wątpliwościach wybierz rekomendowaną opcję z tego promptu.
- Prowadź handoff w .cursor/work/continuous-lean-ai.md.

## Krytyka pomysłu „3 osobowości = brak halucynacji” (obowiązkowa)

Trzy role, które się zgadzają, NIE eliminują halucynacji.
Mogą współdzielić wagi, biasy, prompt lub skopiować sobie nawzajem błąd.
Zgoda ról jest sygnałem priorytetu / jakości roboczej, NIGDY statusem formalnym.
Tylko Lean może nadać proved lub refuted.
Analogia „lustro / nagranie siebie” jest dobra jako niezależna krytyka artefaktów,
ale nie jako walidacja matematyczna.

## Kanoniczne statusy (SQLite + API)

Każdy kandydat kończy w dokładnie jednym statusie wyprowadzonym z dowodów:

1. proved — Lean zaakceptował kompletny dowód (bez sorry).
2. refuted — Lean zaakceptował dowód, że skonkretyzowane zdanie jest fałszywe
   (certyfikat kontrprzykładu), nie sama heurystyka Pythona.
3. unresolved — brak przyjętego dowodu i brak certyfikowanego kontrprzykładu;
   obejmuje timeout, porażkę przeszukiwania, brak świadka w boundzie, zgodę ról bez Leana.
4. ill_formed — błąd AST/typów albo Lean syntax/typing.
   Mapowanie z istniejącego assess_hypothesis:
   invalid_syntax | invalid_type → ill_formed;
   proved | refuted | unresolved bez zmiany znaczenia.
   SQLite/API continuous-AI NIE wprowadza równoległych synonimów statusów.

Zasady:
- Brak dowodu ≠ fałsz.
- Błąd kompilacji ≠ kontrprzykład.
- Model/role NIGDY nie zapisują bezpośrednio proved/refuted.
- Python find_counterexample może zaproponować świadka; refuted dopiero po Lean certificate.
- Odrzucaj: sorry, axiom, opaque, unsafe, #eval, run_io, run_cmd, niezatwierdzone importy.

## Faza 0 — architektura przed kodem

Zanim napiszesz implementację, zapisz:
- docs/continuous-ai-architecture.md
- draft DDL / migracji w docs (projekt schematu); pliki migracji + zastosowanie = Faza 1 pod TDD
- diagram pętli: propose → prove/critique → validate → classify → store → schedule
- plan curriculum i bramek promocji
- plan pamięci na Mac 24 GB RAM

Dopiero potem TDD i kod.

## Faza 1 — SQLite od razu (minimalny schemat, nie archiwum)

Użyj SQLite z WAL, foreign keys, busy_timeout, transakcjami, migracjami,
idempotency keys i crash-safe commitami.

Tabele (minimum):
- schema_migrations
- runs — status, seed, config JSON, curriculum_level, model_version, created/updated
- candidates — stable_id, canonical AST JSON, structural_hash, kind
  (hypothesis|theorem|definition|expression), provenance, current_status, timestamps
- attempts — candidate_id, role, model_version, prompt_hash, raw_response,
  proof_artifact / critique_artifact, timings; IMMUTABLE
- validations — candidate_id, attempt_id, lean_version, toolchain_hash,
  validation_type (proof|counterexample|check), result, bounded stdout/stderr; IMMUTABLE
- counterexamples — candidate_id, assignment JSON, instantiated_prop, lean_certificate_id
- dependencies — from_id, to_id, relation (cites|uses_definition|generalizes|…)
- queue_jobs — type, priority, state, lease_owner, lease_expiry, retry_count, idempotency_key
- events — append-only state transitions
- curriculum_progress — level, windows, metrics, gate_status
- model_versions — path/hash, adapter_hash, eval_scores, champion/challenger/retired
- checkpoints — run_id, seq, event_cursor, scheduler_state, rng_state,
  curriculum_state, artifact hashes

Outcome kandydata jest DERIVED z accepted validations, nie z opinii modelu.

## Faza 2 — pause / resume / checkpoint

- Checkpoint co 300 s domyślnie; konfigurowalne tylko w zakresie 300–600 s.
- Checkpoint także: pause, SIGINT/SIGTERM, promocja curriculum, promocja modelu.
- Pause: zatrzymaj nowe dequeue, dokończ lub release lease’ów, commit, atomic publish checkpoint, exit.
- Resume: integrity check, restore RNG/scheduler, reclaim expired leases, zero duplicate attempts.
- Snapshot musi pozwalać na replay runu z zapisanych raw_response bez ponownego wołania modelu.
- Zachowuj latest known-good checkpoint.

Trackery: run status, curriculum level, event cursor, queue depths, model version.
CLI minimum: start | pause | resume | status | replay.

## Faza 3 — kolejki i workers (żeby model nie czekał bezczynnie)

Bounded queues:
- propose
- prove_primary
- prove_alternate_or_critique
- counterexample_search
- lean_validate

Wymagania:
- backpressure przy high-water mark
- priorytet jobów odblokowujących downstream
- leases + heartbeats
- JEDEN załadowany serwer modelu; role multiplexowane requestami (nie 3 pełne kopie w RAM)
- start: 1 inference worker + 1–2 Lean workers; skaluj po pomiarze
- mierz utilization i latency, ale nie poświęcaj poprawności dla zajętości

## Faza 4 — curriculum: trudność rośnie bardzo wolno

Zacznij od istniejącego generatora konkretnego Nat (etap 1).
Rozszerzaj możliwości etapów 2→6 po JEDNYM poziomie naraz.
Nie pomijaj etapów.

Bramka promocji poziomu (wszystkie warunki):
- ≥ 1000 nowo ocenionych przez Lean kandydatów na poziomie
- 3 kolejne okna ewaluacji spełniają progi
- zero naruszeń poprawności (false proved/refuted)
- stabilna różnorodność (structural novelty, diversity metrics)
- brak regresji na held-out benchmarku
- co najwyżej jedna promocja na ukończone okno checkpointowe

Complexity: używaj istniejących miar (ast_size, depth, variables, operators,
dependencies, definitions). Wielkość liczebnika NIE jest trudnością.

Po zaliczeniu bramki etapu 6 generatora wprowadź trzy izolowane role
jako helper etapu 7 (hipotezy), nie wcześniej:

1. theorem_proposer
   - emituje typowany kandydat (AST kontrakt) + krótkie rationale
   - NIE nadaje werdyktu
   - tryb „bez kontekstu”: brak historii innych agentów; tylko kontrakt AST,
     seed/losowość, opcjonalnie mały retrieval z SQLite po structural_hash / family
     (retrieval ≠ shared chat scratchpad)

2. prover
   - niezależna próba dowodu; nie widzi roboczych notatek proposera poza kandydatem

3. alternate_prover_critic
   - najpierw niezależna próba dowodu BEZ widoku primary proof
   - potem krytyka obu artefaktów (różnice, luki, alternatywa)

Role wymieniają tylko immutable artifacts przez SQLite.
Zapisujemy „robocze rozwiązanie” do dalszego treningu / retrieval TYLKO gdy:
- Lean zaakceptował proof LUB certyfikowany counterexample, ORAZ
- (opcjonalnie) obie ścieżki proverów nie są sprzeczne względem tego samego artefaktu.
Zgoda ról bez Leana NIGDY nie wystarcza.

Nieudana bramka zamraża advancement; nie przepisuje accepted evidence.

## Faza 5 — strategia modelu na Mac 24 GB RAM

Rekomendacja domyślna:
- jeden lokalny model 7B–8B instruct/code, kwantyzacja 4-bit (MLX lub llama.cpp)
- context 8K–16K
- peak process memory < ~18 GB (zostaw headroom dla Lean i macOS)
- NIE trzymaj trzech resident copies modelu
- 14B 4-bit tylko jako opcjonalny benchmark po pomiarze latency/RAM

Najpierw ucz system przez:
- data flywheel (SQLite memory)
- retrieval wcześniejszych proved/refuted
- ranking szablonów / taktyk / reguł generatora
- contextual bandit / policy scheduling

LoRA / fine-tune DOPIERO później, offline między runami:
- trenuj WYŁĄCZNIE na Lean-validated proved/refuted
- NIGDY na unresolved, ill_formed, samej zgodzie ról, niecertyfikowanych świadkach
- challenger vs champion na held-out; rollback przy regresji
- każda wersja: hash, eval scores, możliwość retire

## Faza 6 — ochrona przed self-training collapse

- Immutable seed corpus + held-out benchmark (nigdy w train).
- Deduplikacja po structural_hash między train/eval.
- Balance family / outcome / difficulty.
- Cap potomków syntezowanych z jednego ancestora.
- Wykrywaj triviality gaming: novelty, AST complexity, dependency depth, proof diversity.
- Quarantine jeśli ten sam kandydat wygląda na proved i refuted jednocześnie → system defect.
- Promocja modelu/policy tylko gdy poprawia correctness, solve rate, calibration, diversity, resource use.

## Faza 7 — Lean validation

- Pin i zapisuj toolchain (lean/lean-toolchain, hash).
- Waliduj kandydatów osobno (jeden zły plik nie psuje batcha).
- Kontrprzykład = Lean akceptuje twierdzenie o negacji instantiated proposition.
- Limits: wall-clock, CPU, process group kill, output truncate, controlled imports, temp files.
- reuse theorem_gen.verify gdzie możliwe; nie buduj drugiego ad-hoc runnera bez potrzeby.

## Faza 8 — CLI i DX

Polecenia (repo root):

    python3 -m theorem_gen.learn start --run-id ... --curriculum ...
    python3 -m theorem_gen.learn pause --run-id ...
    python3 -m theorem_gen.learn resume --run-id ...
    python3 -m theorem_gen.learn status --run-id ...
    python3 -m theorem_gen.learn replay --run-id ... --from-checkpoint ...

Istniejący `python3 -m theorem_gen generate` musi dalej działać bez regresji.

## Acceptance tests (musi przejść lub mieć mierzalny protokół)

1. Istniejący suite unittest pozostaje zielony.
2. Migracje, FK, transakcje, idempotency.
3. Trzy zgadzające się role NIE mogą oznaczyć Lean-rejected jako proved.
4. Świadek z Pythona bez Lean certificate → unresolved.
5. Lean-certified witness → refuted z reproducible evidence.
6. syntax/typing → ill_formed; timeout → unresolved.
7. Kill w ≥3 zdefiniowanych punktach (między dequeue→lease, po Lean validate
   przed commit, podczas checkpoint write) + resume → zero lost/duplicate attempts
   (sprawdzane przez idempotency_key).
8. Pause → valid checkpoint; resume odtwarza scheduler/RNG.
9. Expired leases reclaim; backpressure ogranicza kolejki.
10. Pod synthetic load z eligible work: utilization inference/Lean powyżej progu
    (np. ≥80% busy gdy kolejka > 0) — nie „zero idle forever”.
11. Curriculum nie awansuje wcześnie ani z samych training metrics.
12. Challenger fail → rollback champion.
13. Replay z recorded outputs bez inference odtwarza outcomes.
14. Peak RSS procesu inference+workers+Lean w budżecie (~18 GB headroom na Mac 24 GB),
    zmierzony skryptem/raportem w docs.
15. Forbidden Lean constructs rejected mimo zgody ról.
16. Raport fazy z faktycznie uruchomionymi komendami i wynikami.

## Kolejność dostarczania

1. Architektura + schema draft + handoff
2. SQLite store + migrations + tests
3. Queue + pause/resume/checkpoint + tests
4. Lean validation adapter + classify + tests
5. Curriculum level 1 wired to existing generate()
6. Slow gates through stage 6 capabilities
7. Three roles helper for stage 7
8. Retrieval / ranking / optional offline LoRA later
9. Docs: architecture, stage notes, measured commands

## Definicja „learning”

Wolno napisać, że system się uczy, TYLKO gdy istnieje persisted, evaluated
policy lub model_version, która bije fixed baseline na held-out.
Sam zapis coraz większej liczby rekordów w SQLite to pamięć eksperymentów, nie jeszcze „nauka modelu”.

## Out of scope na start

- Mathlib
- trzy pełne modele w RAM jednocześnie
- online fine-tune podczas serving
- obietnica rozwiązania dowolnej hipotezy
- przepisywanie generatora etapów 0–8 „po cichu”

Zaczynaj od architektury i czerwonych testów SQLite/pause. Nie kończ fazy bez zielonych testów i raportu komend.
````

## Jak używać

1. Najpierw (opcjonalnie) uruchom prompt audytu z `docs/prompts/audit-lean-generator.md`, żeby mieć bazę.
2. Wklej cały blok `text` powyżej do nowego czatu z dostępem do repozytorium i narzędzi.
3. Trzymaj handoff w `.cursor/work/continuous-lean-ai.md`.
4. Curriculum i LoRA wdrażaj dopiero po zielonych bramkach — nie skacz do „trzech osobowości” przed etapem 6.

## Rekomendowane decyzje domyślne (gdy agent ma wątpliwości)

| Pytanie | Wybór |
|---------|--------|
| Ile modeli w RAM? | 1 × 7–8B 4-bit |
| Checkpoint interval | 300 s |
| Kiedy 3 role? | Po bramce curriculum odpowiadającej etapowi 6 |
| Kiedy LoRA? | Offline, po korpusie Lean-validated i held-out |
| Co jest prawdą? | Tylko Lean certificate |
| Proposer „bez kontekstu”? | Brak shared chat; wolno mały retrieval z SQLite |
