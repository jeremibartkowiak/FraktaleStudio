"""Silnik generowania trójkąta Sierpińskiego.

Rastrowanie jest w pełni zwektoryzowane (NumPy) i ma złożoność O(liczba pikseli)
– niezależnie od głębokości n. Nie rysujemy 3^n osobnych wielokątów.

Idea:
    Każdy punkt P wewnątrz trójkąta ABC zapisujemy we współrzędnych skośnych
    P = A + s·(B-A) + t·(C-A). Po przeskalowaniu S = s·2^n, T = t·2^n
    komórka siatki to (i, j) = (floor(S), floor(T)). Komórka jest „prosta”
    (trójkąt skierowany jak rodzic), gdy frac(S) + frac(T) < 1.
    Z twierdzenia Lucasa: współczynnik C(i+j, j) jest nieparzysty
    <=>  (i & j) == 0  – i dokładnie te komórki należą do fraktala.

Wektorowy eksport SVG korzysta z jednej ścieżki z regułą `evenodd`
(duży trójkąt + „dziury”), więc przezroczystość działa poprawnie.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
from PIL import Image

SQRT3_2 = math.sqrt(3.0) / 2.0
MAX_DEPTH = 12
# Maksymalna liczba próbek przetwarzana w jednym bloku (ogranicza zużycie RAM).
_CHUNK_SAMPLES = 1_500_000
# Budżet próbek przy eksporcie z wygładzaniem (supersampling).
_EXPORT_SAMPLE_BUDGET = 80_000_000


@dataclass(frozen=True)
class Settings:
    """Wszystkie parametry obrazu – niemutowalne, bezpieczne między wątkami."""

    depth: int = 7
    size: int = 2048               # szerokość eksportowanego obrazu [px]
    margin: float = 0.05           # margines jako ułamek wymiaru
    fg: str = "#A78BFA"            # kolor trójkątów
    fg_alpha: int = 255            # krycie trójkątów 0..255
    bg: str = "#0F0B1E"            # kolor tła
    transparent: bool = False      # przezroczyste tło
    inverted: bool = False         # wierzchołek w dół
    antialias: bool = True         # wygładzanie krawędzi
    fit: str = "square"            # "square" | "fit" (dopasowany do trójkąta)


# --------------------------------------------------------------------------- #
# Narzędzia
# --------------------------------------------------------------------------- #
def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def triangle_count(depth: int) -> int:
    """Liczba najmniejszych (wypełnionych) trójkątów dla głębokości n."""
    return 3 ** depth


def export_dimensions(s: Settings) -> tuple[int, int]:
    width = int(s.size)
    height = width if s.fit == "square" else max(1, round(width * SQRT3_2))
    return width, height


def triangle_vertices(width: float, height: float, margin: float,
                      inverted: bool) -> np.ndarray:
    """Największy trójkąt równoboczny mieszczący się w prostokącie (z marginesem).

    Zwraca tablicę (3, 2): wierzchołek główny A, potem B (lewy) i C (prawy).
    """
    avail_w = width * (1.0 - 2.0 * margin)
    avail_h = height * (1.0 - 2.0 * margin)
    side = max(0.0, min(avail_w, avail_h / SQRT3_2))
    tri_h = side * SQRT3_2
    cx = width / 2.0
    top = (height - tri_h) / 2.0
    bottom = top + tri_h
    if inverted:
        pts = [(cx, bottom), (cx - side / 2, top), (cx + side / 2, top)]
    else:
        pts = [(cx, top), (cx - side / 2, bottom), (cx + side / 2, bottom)]
    return np.asarray(pts, dtype=np.float64)


def smallest_side(s: Settings) -> float:
    """Długość boku najmniejszego trójkąta w eksportowanym obrazie [px]."""
    w, h = export_dimensions(s)
    a, b, _ = triangle_vertices(w, h, s.margin, s.inverted)
    return float(np.hypot(*(b - a))) / (2 ** s.depth)


def export_supersample(width: int, height: int) -> int:
    """Dobiera współczynnik supersamplingu tak, by nie przekroczyć budżetu RAM/CPU."""
    factor = int(math.sqrt(_EXPORT_SAMPLE_BUDGET / max(1, width * height)))
    return max(1, min(4, factor))


# --------------------------------------------------------------------------- #
# Rastrowanie
# --------------------------------------------------------------------------- #
def coverage(width: int, height: int, depth: int, margin: float, inverted: bool,
             supersample: int = 1,
             progress: Optional[Callable[[float], None]] = None) -> np.ndarray:
    """Mapa pokrycia (float32, 0..1) o wymiarach (height, width)."""
    ss = max(1, int(supersample))
    a, b, c = triangle_vertices(width, height, margin, inverted)
    e1, e2 = b - a, c - a
    det = e1[0] * e2[1] - e1[1] * e2[0]
    out = np.zeros((height, width), dtype=np.float32)
    if abs(det) < 1e-9:
        return out

    n_cells = float(1 << depth)
    k = n_cells / det
    # Liczymy tylko w prostokącie otaczającym trójkąt.
    xs_v, ys_v = (a[0], b[0], c[0]), (a[1], b[1], c[1])
    x0, x1 = max(0, int(math.floor(min(xs_v)))), min(width, int(math.ceil(max(xs_v))))
    y0, y1 = max(0, int(math.floor(min(ys_v)))), min(height, int(math.ceil(max(ys_v))))
    if x1 <= x0 or y1 <= y0:
        return out
    bw = x1 - x0

    # Współrzędne skośne są liniowe w x i y -> liczymy je separowalnie
    # (float64 dla wektorów bazowych, float32 dla dużych bloków).
    xs = (np.arange(x0 * ss, x1 * ss, dtype=np.float64) + 0.5) / ss - a[0]
    s_x = ((k * e2[1]) * xs).astype(np.float32)
    t_x = ((-k * e1[1]) * xs).astype(np.float32)

    rows_per_chunk = max(1, _CHUNK_SAMPLES // (bw * ss * ss))
    span = y1 - y0
    for r0 in range(y0, y1, rows_per_chunk):
        r1 = min(y1, r0 + rows_per_chunk)
        ys = (np.arange(r0 * ss, r1 * ss, dtype=np.float64) + 0.5) / ss - a[1]
        S = ((-k * e2[0]) * ys).astype(np.float32)[:, None] + s_x
        T = ((k * e1[0]) * ys).astype(np.float32)[:, None] + t_x
        U = S + T
        filled = (S >= 0) & (T >= 0) & (U <= n_cells)      # wnętrze trójkąta
        i = S.astype(np.int32)                              # = floor (dla S >= 0)
        j = T.astype(np.int32)
        # komórka „prosta” <=> frac(S)+frac(T) < 1 <=> floor(S+T) == floor(S)+floor(T)
        filled &= U.astype(np.int32) == i + j
        # Lucas: C(i+j, j) nieparzyste <=> (i & j) == 0
        np.bitwise_and(i, j, out=i)
        filled &= i == 0

        if ss > 1:
            block = filled.reshape(r1 - r0, ss, bw, ss).sum(axis=(1, 3), dtype=np.uint16)
            out[r0:r1, x0:x1] = block * np.float32(1.0 / (ss * ss))
        else:
            out[r0:r1, x0:x1] = filled
        if progress is not None:
            progress((r1 - y0) / span)
    return out


def render(s: Settings, width: int, height: int, supersample: int = 1,
           progress: Optional[Callable[[float], None]] = None) -> Image.Image:
    """Renderuje obraz RGB (tło kolorowe) lub RGBA (tło przezroczyste)."""
    cov = coverage(width, height, s.depth, s.margin, s.inverted, supersample, progress)
    alpha = np.rint(cov * s.fg_alpha).astype(np.uint8)
    mask = Image.fromarray(alpha)  # uint8 2D -> tryb "L"
    fg = hex_to_rgb(s.fg)
    if s.transparent:
        img = Image.new("RGBA", (width, height), fg + (0,))
        img.putalpha(mask)
    else:
        img = Image.new("RGB", (width, height), hex_to_rgb(s.bg))
        img.paste(fg, (0, 0, width, height), mask)
    return img


def checkerboard(width: int, height: int, cell: int = 10,
                 c1=(204, 204, 210), c2=(160, 160, 170)) -> Image.Image:
    """Szachownica sygnalizująca przezroczystość w podglądzie."""
    yy, xx = np.indices((height, width))
    pattern = ((xx // cell + yy // cell) % 2).astype(bool)
    arr = np.where(pattern[..., None], np.array(c1, np.uint8), np.array(c2, np.uint8))
    return Image.fromarray(arr.astype(np.uint8))  # (h, w, 3) uint8 -> "RGB"


# --------------------------------------------------------------------------- #
# Eksport wektorowy (SVG)
# --------------------------------------------------------------------------- #
def build_svg(s: Settings, width: int, height: int,
              min_hole: float = 0.5) -> tuple[str, int]:
    """Buduje SVG. Zwraca (tekst, efektywna głębokość).

    Dziury mniejsze niż `min_hole` jednostek są pomijane (niewidoczne,
    a mocno zwiększałyby rozmiar pliku).
    """
    a, b, c = triangle_vertices(width, height, s.margin, s.inverted)
    fmt = "M{:.2f} {:.2f}L{:.2f} {:.2f}L{:.2f} {:.2f}Z".format
    parts = [fmt(*a, *b, *c)]
    tris = np.stack([a, b, c])[None, ...]          # (m, 3, 2)
    side = float(np.hypot(*(b - a)))
    effective = 0
    for level in range(s.depth):
        if side / 2.0 < min_hole:
            break
        va, vb, vc = tris[:, 0], tris[:, 1], tris[:, 2]
        ab, bc, ca = (va + vb) / 2, (vb + vc) / 2, (vc + va) / 2
        holes = np.stack([ab, bc, ca], axis=1).reshape(-1, 6)
        parts.extend(fmt(*h) for h in holes.tolist())
        effective += 1
        side /= 2.0
        if level < s.depth - 1:
            tris = np.concatenate([
                np.stack([va, ab, ca], axis=1),
                np.stack([ab, vb, bc], axis=1),
                np.stack([ca, bc, vc], axis=1),
            ])

    opacity = s.fg_alpha / 255.0
    bg_rect = "" if s.transparent else f'  <rect width="100%" height="100%" fill="{s.bg}"/>\n'
    svg = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">\n'
        f'  <title>Trójkąt Sierpińskiego (n={effective})</title>\n'
        f'{bg_rect}'
        f'  <path fill="{s.fg}" fill-opacity="{opacity:.3f}" fill-rule="evenodd" d="'
        + "".join(parts)
        + '"/>\n</svg>\n'
    )
    return svg, effective


def save_svg(s: Settings, width: int, height: int, path: str) -> int:
    svg, effective = build_svg(s, width, height)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(svg)
    return effective
