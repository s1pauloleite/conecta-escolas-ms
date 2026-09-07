"""
tile_math.py
-------------
Conversão entre coordenadas geográficas (WGS84) e o sistema de tiles Web
Mercator usado pelo Ookla Open Data (e pelo Bing Maps, de onde vem o
formato de "quadkey"). Só matemática, sem dependências — por isso fica
separado do processamento em si, e é fácil de testar isoladamente.

Referência: https://learn.microsoft.com/en-us/bingmaps/articles/bing-maps-tile-system
"""

from __future__ import annotations

import math

TILE_SIZE_PX = 256


def lat_lon_para_tile_xy(latitude: float, longitude: float, zoom: int) -> tuple[int, int]:
    """Converte uma coordenada WGS84 em coordenadas de tile (x, y) num dado zoom."""
    latitude = max(min(latitude, 85.05112878), -85.05112878)
    longitude = max(min(longitude, 180.0), -180.0)

    x = (longitude + 180.0) / 360.0
    seno_lat = math.sin(latitude * math.pi / 180.0)
    y = 0.5 - math.log((1 + seno_lat) / (1 - seno_lat)) / (4 * math.pi)

    tamanho_mapa = TILE_SIZE_PX << zoom
    pixel_x = int(min(max(x * tamanho_mapa, 0), tamanho_mapa - 1))
    pixel_y = int(min(max(y * tamanho_mapa, 0), tamanho_mapa - 1))

    return pixel_x // TILE_SIZE_PX, pixel_y // TILE_SIZE_PX


def tile_xy_para_quadkey(tile_x: int, tile_y: int, zoom: int) -> str:
    """Converte coordenadas de tile (x, y) na quadkey (formato Bing/Ookla)."""
    digitos = []
    for i in range(zoom, 0, -1):
        digito = 0
        mascara = 1 << (i - 1)
        if (tile_x & mascara) != 0:
            digito += 1
        if (tile_y & mascara) != 0:
            digito += 2
        digitos.append(str(digito))
    return "".join(digitos)


def lat_lon_para_quadkey(latitude: float, longitude: float, zoom: int) -> str:
    """Atalho: converte direto de lat/lon para a quadkey do tile correspondente."""
    tile_x, tile_y = lat_lon_para_tile_xy(latitude, longitude, zoom)
    return tile_xy_para_quadkey(tile_x, tile_y, zoom)


def quadkeys_vizinhos_por_distancia(tile_x: int, tile_y: int, zoom: int, raio_tiles: int) -> list[str]:
    """Quadkeys num raio (em tiles) ao redor de (tile_x, tile_y), do mais perto ao mais longe.

    Usado para achar o tile Ookla com dado mais próximo quando o tile
    exato de um município não tiver nenhuma medição registrada (comum em
    áreas de baixa densidade de testes).
    """
    candidatos = []
    for dx in range(-raio_tiles, raio_tiles + 1):
        for dy in range(-raio_tiles, raio_tiles + 1):
            distancia2 = dx * dx + dy * dy
            candidatos.append((distancia2, tile_xy_para_quadkey(tile_x + dx, tile_y + dy, zoom)))
    candidatos.sort(key=lambda item: item[0])
    return [quadkey for _, quadkey in candidatos]
