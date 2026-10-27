# △ Sierpiński Studio

Graficzny generator trójkąta Sierpińskiego (Python + CustomTkinter + Pillow + NumPy).

## Uruchomienie

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe app.py
```

Albo po prostu dwuklik na **`uruchom.bat`** (za pierwszym razem sam utworzy venv).

## Funkcje

| Opcja | Opis |
|---|---|
| Głębokość **n** | suwak 0–12 + przyciski −/+ |
| Margines, krycie | suwaki (%) |
| Kolor trójkątów / tła | systemowy wybierak kolorów lub wpis HEX, gotowe palety, zamiana kolorów |
| Przezroczyste tło | podgląd na szachownicy, zapis z kanałem alfa |
| Wygładzanie | antyaliasing (supersampling) |
| Odwrócony, format | wierzchołek w dół; obraz kwadratowy lub dopasowany do trójkąta |
| Rozdzielczość | 256–8192 px, informacja o rozmiarze najmniejszego trójkąta |
| Zapis (Ctrl+S) | PNG, SVG (wektor), WebP, TIFF, JPEG, BMP |

## Dlaczego to jest szybkie

Zamiast rysować 3ⁿ wielokątów, każdy piksel jest klasyfikowany wektorowo (NumPy)
w czasie **O(liczba pikseli)** – niezależnie od n:

1. Piksel P zapisujemy we współrzędnych skośnych trójkąta: `P = A + s·(B−A) + t·(C−A)`.
2. Skalujemy: `S = s·2ⁿ`, `T = t·2ⁿ`, komórka `(i, j) = (⌊S⌋, ⌊T⌋)`.
3. Komórka jest „prosta”, gdy `⌊S+T⌋ == i + j`.
4. Z twierdzenia Lucasa `C(i+j, j)` jest nieparzyste ⇔ **`(i & j) == 0`** – to są wypełnione trójkąty.

Podgląd renderuje się w osobnym wątku z debouncingiem (zawsze tylko najnowszy stan suwaków),
eksport też działa w tle z paskiem postępu. Duże obrazy liczone są blokami, żeby nie zająć dużo RAM.
SVG to jedna ścieżka z regułą `evenodd` (trójkąt + „dziury”), więc przezroczystość działa poprawnie.
