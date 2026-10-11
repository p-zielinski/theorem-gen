# Etapy i kryteria ukończenia

Kod realizuje etapy 0–8. Domyślny generator konkretny z etapu 1 pozostaje bez zmian.

## Etap 0 — analiza

Status: ukończony. Dowód: [stage-0.md](stage-0.md), [architecture.md](architecture.md).

Ukończony, gdy wiadomo, jakie narzędzia są dostępne, która część systemu jest w Pythonie, a która w Leanie, jak wyglądają katalogi i interfejs oraz jakie są kryteria kolejnych etapów.

## Etap 1 — konkretna arytmetyka

Status: ukończony. Raport: [stage-1.md](stage-1.md).

Ukończony, gdy jednocześnie:

- to samo ziarno i ta sama konfiguracja dają ten sam zbiór twierdzeń
- da się poprosić o określoną liczbę przykładów, w tym zero
- przy `unique` w jednym zbiorze nie ma dwóch zdań o tym samym kluczu; przy braku miejsca powstaje jawny błąd
- eksport jest poprawnym, wąskim Lean 4 i nie zmienia znaczenia drzewa
- prawdziwy Lean akceptuje wygenerowany plik
- błąd kompilacji, timeout i brak narzędzia są rozróżnione; timeout nie jest werdyktem „fałsz”
- testy jednostkowe, brzegowe, deterministyczne, właściwościowe i integracyjne z Leanem przechodzą
- raport etapu wymienia uruchomione polecenia i ich wynik

## Etap 2 — zmienne i twierdzenia ogólne

Status: ukończony. Raport: [stage-2.md](stage-2.md).

Ukończony, gdy generator rozróżnia zdanie konkretne, zdanie dla wszystkich elementów typu, zdanie z założeniami i wyrażenie bez dowodu, a żadnego z nich nie traktuje jako prawdziwego tylko dlatego, że zostało wygenerowane.

## Etap 3 — szersze AST

Status: ukończony. Raport: [stage-3.md](stage-3.md).

Ukończony, gdy każda nowa konstrukcja ma testy typowania, eksportu i Leana, a niedozwolona kombinacja typów kończy się błędem zamiast kodu o innym znaczeniu.

## Etap 4 — rejestr i zależności

Status: ukończony. Raport: [stage-4.md](stage-4.md).

Ukończony, gdy wyniki mają stabilne identyfikatory, widać brakującą zależność i cykl, a graf da się odtworzyć z zapisanej historii. Użycie wcześniejszego twierdzenia nie jest liczone jako jego ponowne odkrycie.

## Etap 5 — złożoność

Status: ukończony. Raport: [stage-5.md](stage-5.md).

Ukończony, gdy generowanie umie trafić w zadany zakres kilku miar (rozmiar drzewa, głębokość, liczba zmiennych, operatorów, zależności, definicji), a sama wielkość liczby nie jest jedyną miarą trudności.

## Etap 6 — definicje

Status: ukończony. Raport: [stage-6.md](stage-6.md).

Ukończony, gdy system tworzy definicję w obsługiwanej reprezentacji, sprawdza ją, buduje z niej twierdzenia, zapisuje zależności i przechodzi przez Leana.

## Etap 7 — hipotezy

Status: ukończony. Raport: [stage-7.md](stage-7.md).

Ukończony, gdy hipoteza może być udowodniona, obalona kontrprzykładem, nierozstrzygnięta albo błędna składniowo lub typowo. Brak dowodu nie jest oznaczany jako fałsz. Jest pomiar powtarzalności i różnorodności.

## Etap 8 — otwarta eksploracja

Status: ukończony. Raport: [stage-8.md](stage-8.md).

System tworzy zdania, których sam nie zawsze rozstrzyga. Brak dowodu, fałsz i niedowodliwość w zarejestrowanym fragmencie pozostają różnymi wynikami. Nie ma obietnicy pełnej automatyzacji.
