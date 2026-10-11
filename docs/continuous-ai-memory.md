# Pamięć procesu

> Pomiar: 2026-10-12, gałąź `main`, audyt pętli.
> Polecenie: `python3 -m theorem_gen.learn memory`

```
peak_rss_bytes: 16646144
budget_bytes: 19327352832
within_budget: yes
weights_loaded: no
resident_copies: 0
Measured the Python control plane only. No 7B-8B weights were resident. The budget is 18 GB so Lean and macOS keep headroom on a 24 GB machine.
```

Kod wyjścia: 0.

16646144 bajtów to szczyt RSS tego procesu Pythona (na macOS `ru_maxrss` jest w bajtach). Budżet 19327352832 bajtów to 18 GiB. Maszyna zakładana w planie ma 24 GB. Pomiar nie obciążał jej modelem.

Wagi 7B–8B nie były załadowane. `resident_copies` to liczba kopii w `ModelSlot`, nie liczba procesów Leana. Trzy rezydentne kopie modelu nie powstały, bo slot odmawia drugiej.

Ten raport nie jest pomiarem zajętości po dołożeniu kwantyzowanego modelu ani workerów Leana pod obciążeniem wag. Dopóki backend to `RaiseBackend`, proces zostaje płaszczyzną sterowania.
