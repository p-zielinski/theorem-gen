# Etap 4 — rejestr i zależności

> Data ukończenia: 2026-10-11
> Status: ukończony

## 1. Zaimplementowany zakres

`Registry` trzyma rekordy z identyfikatorem, rodzajem, zależnościami, regułami i flagą `discovered`. `extend` odrzuca:

- powtórzony identyfikator
- zależność spoza rejestru i spoza tej samej transakcji (`missing dependencies: …`)
- cykl, także pętlę własną (`cycle: …`)

`dependency_graph` i `Registry.replay(history)` odtwarzają ten sam graf. `stable_identifier` jest prefiksem i 16 znakami SHA-256 z kanonicznego JSON-a; kolejność kluczy słownika nie zmienia wyniku.

Użycie wcześniejszego wyniku nie jest jego ponownym odkryciem. Twierdzenie o `double` ma `discovered=False` i regułę `use_definition`. Definicja ma `discovered=True` i regułę `define`.

## 2. Testy

`tests/test_stage4.py`: cytowanie, brakująca zależność, cykl własny i wzajemny, replay, duplikat, stabilny identyfikator.

## 3. Polecenia i wyniki

Wspólny przebieg jest w [stage-8.md](stage-8.md).

## 4. Ograniczenia

Rejestr jest w pamięci procesu. Historia to lista słowników, nie plik. Nie ma trwałej bazy twierdzeń między uruchomieniami CLI.

## 5. Ocena kryteriów

Kryterium etapu 4 jest spełnione: identyfikatory są stabilne, brak zależności i cykl są widoczne, graf da się odtworzyć, a cytowanie nie jest liczone jako odkrycie.

## 6. Następny krok

Etap 5 mierzy złożoność drzewa niezależnie od wielkości liczebnika.
