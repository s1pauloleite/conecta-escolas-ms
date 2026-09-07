"""Testes de `tile_math.py` contra o exemplo de referência da Microsoft
para o sistema de tiles do Bing Maps (mesmo formato usado pelo Ookla)."""

from tile_math import (
    lat_lon_para_quadkey,
    quadkeys_vizinhos_por_distancia,
    tile_xy_para_quadkey,
)


def test_tile_xy_para_quadkey_exemplo_de_referencia():
    # Exemplo oficial da documentação do Bing Maps Tile System:
    # tile (3, 5) no nível 3 -> quadkey "213".
    assert tile_xy_para_quadkey(3, 5, zoom=3) == "213"


def test_quadkey_tem_o_comprimento_do_zoom():
    quadkey = lat_lon_para_quadkey(-20.4697, -54.6201, zoom=16)  # Campo Grande
    assert len(quadkey) == 16
    assert set(quadkey) <= {"0", "1", "2", "3"}


def test_quadkeys_vizinhos_inclui_o_proprio_tile_primeiro():
    vizinhos = quadkeys_vizinhos_por_distancia(100, 200, zoom=16, raio_tiles=2)
    assert vizinhos[0] == tile_xy_para_quadkey(100, 200, zoom=16)
    # (2*raio+1)^2 tiles no total, incluindo o próprio
    assert len(vizinhos) == 25
