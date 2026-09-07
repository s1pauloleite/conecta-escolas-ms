# data/raw/

Insumos externos usados por `etl.py`, obtidos de fontes oficiais. Nada
aqui é versionado (são arquivos grandes e/ou fáceis de regerar) exceto
este README — veja `.gitignore`.

## Como (re)gerar tudo

```bash
# 1. Municípios de MS: código IBGE, população (IBGE) e investimento em
#    educação (Siconfi/RREO). ~1-2 min, faz ~80 chamadas de API pública.
python fetch_dados_oficiais.py
#   -> gera municipios_oficiais.csv

# 2. Baixe o microdado do Censo Escolar (INEP) — ~512 MB — e salve com
#    exatamente este nome:
#    https://www.gov.br/inep/pt-br/acesso-a-informacao/dados-abertos/microdados/censo-escolar
#    -> data/raw/microdados_censo_escolar_2025.zip

# 3. Baixe as coordenadas de referência dos municípios brasileiros
#    (usadas só para aproximar a posição das escolas — ver nota abaixo):
#    https://raw.githubusercontent.com/kelvins/municipios-brasileiros/main/csv/municipios.csv
#    -> data/raw/municipios_brasileiros_coords.csv

# 4. Filtra o Censo Escolar para as escolas de MS em atividade:
python processar_censo_escolar.py
#   -> gera escolas_censo_ms.csv

# 5. Baixe os tiles de banda larga fixa do Ookla Speedtest (~350 MB) —
#    escolha o trimestre mais recente disponível em
#    https://github.com/teamookla/ookla-open-data (padrão de URL abaixo)
#    e salve com exatamente este nome:
#    https://ookla-open-data.s3.amazonaws.com/parquet/performance/type=fixed/year=2026/quarter=2/2026-04-01_performance_fixed_tiles.parquet
#    -> data/raw/ookla_fixed_tiles_2026q2.parquet

# 6. Calcula a velocidade média real por município de MS:
python processar_ookla.py
#   -> gera conectividade_municipio_ookla.csv

# 7. (Opcional, mas recomendado) exporte manualmente a planilha de
#    medições SIMET reais em
#    https://conectividadenaeducacao.nic.br/#mapa-escolas
#    (não tem API — ver DownloadManual/README.md) e salve em:
#    ../../DownloadManual/base-escolas-simet-<data-do-export>.xlsx

# 8. Filtra a planilha do NIC.br para MS:
python processar_nicbr_simet.py
#   -> gera medicoes_reais_nicbr.csv
```

Depois disso, `python etl.py` detecta os arquivos e carrega dado oficial
em vez da amostra sintética — sem precisar repetir os passos acima a cada
execução do ETL (por isso eles não são o próprio `etl.py`: são uma busca
de dados, não uma carga de banco).

## Arquivos

| Arquivo | Gerado por | Conteúdo |
|---|---|---|
| `municipios_oficiais.csv` | `fetch_dados_oficiais.py` | 79 municípios de MS: código IBGE, população (IBGE), investimento em educação per capita (Siconfi/RREO 2025 ou 2024) |
| `microdados_censo_escolar_2025.zip` | baixado manualmente (INEP) | Microdado nacional completo do Censo Escolar — usado só como fonte para o passo 4 |
| `municipios_brasileiros_coords.csv` | baixado manualmente ([kelvins/municipios-brasileiros](https://github.com/kelvins/municipios-brasileiros)) | Coordenadas de referência (sede) de todos os municípios do Brasil |
| `escolas_censo_ms.csv` | `processar_censo_escolar.py` | Escolas de MS em atividade: localização urbana/rural, internet (geral e para alunos), banda larga, rede local (wifi/cabo), matrículas, latitude/longitude aproximada |
| `ookla_fixed_tiles_2026q2.parquet` | baixado manualmente ([teamookla/ookla-open-data](https://github.com/teamookla/ookla-open-data)) | Tiles globais de banda larga fixa (download/upload/latência médios, ~600m x 600m), trimestre 2026-Q2 |
| `conectividade_municipio_ookla.csv` | `processar_ookla.py` | Velocidade/latência média REAL por município de MS, usada para calibrar a simulação por escola em `etl.py` |
| `medicoes_reais_nicbr.csv` | `processar_nicbr_simet.py` | Geolocalização e medição SIMET REAIS por escola pública de MS (fonte: planilha manual em `../../DownloadManual/`) |

## ⚠️ Limitações que ficaram documentadas em vez de contornadas

- **Geolocalização por escola**: o Censo Escolar aberto não publica
  latitude/longitude por escola (removido por proteção de dados). Para as
  1.377 escolas públicas cobertas pela planilha do NIC.br
  (`medicoes_reais_nicbr.csv`), usamos a geolocalização real de lá. Para
  as demais (privadas, ou fora daquela planilha), `processar_censo_escolar.py`
  posiciona a escola nas proximidades da sede do seu município (com um
  pequeno deslocamento aleatório só para não empilhar tudo no mesmo
  ponto) e marca `geo_aproximada = 1` no banco — o mapa em `app.py` deixa
  isso explícito no popup de cada marcador.
- **Velocidade por escola**: o NIC.br mede isso de verdade (SIMET) e expõe
  em dois painéis — `conectividadenaeducacao.nic.br` (por escola: download,
  upload, latência, jitter, perda de pacotes) e `qualidadedainternet.nic.br`
  (agregado por estado). Nenhum dos dois tem API pública ou download em
  massa: inspecionamos os scripts carregados por ambos e são apps **R
  Shiny** com sessão via WebSocket — o botão de download de cada um só
  ativa dentro de uma sessão de navegador ao vivo, filtro por filtro
  (confirmado: o botão `baixe_medicoes` existe no HTML do primeiro painel,
  mas vem desabilitado e com `href=""` até haver interação numa sessão
  real). Automatizar isso via navegador (Selenium/Playwright) para
  extrair as ~1.860 escolas de MS uma a uma seria frágil, sem termo de uso
  publicado autorizando extração em massa, e uma dependência pesada nova
  — decidimos não fazer isso.

  Em vez disso, a equipe **exportou a planilha manualmente**, uma única
  vez, interagindo com o painel como qualquer usuário faria (ver
  `DownloadManual/README.md`) — isso deu medição SIMET real para 1.105
  escolas públicas de MS (`fonte_medicao = 'nicbr_simet_real'` no banco).
  Para as demais (sem medidor instalado, ou privadas — fora do escopo
  daquela planilha), `etl.py` simula uma leitura ANCORADA na velocidade
  média REAL do Ookla Speedtest para o município
  (`fonte_medicao = 'ookla'`) — dado real da região, não uma medição da
  escola em si. Sem baseline Ookla nem medição NIC.br, recua para uma
  faixa genérica (`fonte_medicao = 'sintetico_generico'`). Licença do
  Ookla: CC BY-NC-SA 4.0 (uso não comercial, com atribuição).

  O caminho correto para automatizar o dado real do SIMET por escola (sem
  depender de um export manual a cada atualização) é uma solicitação
  formal de parceria acadêmica ao NIC.br — o mesmo canal que eles já usam
  para compartilhar esse dado com a Giga (UNICEF/ITU, cuja API própria —
  `datasharing.giga.global` — também exige cadastro e permissão por
  país, não é self-serve) e para a pesquisa TIC Educação/Cetic.br.
- **Nota de transparência (CGU/Escala Brasil Transparente)**: o Mapa
  Brasil Transparente estava fora do ar para manutenção (checado em
  06/09/2026, retorno previsto para 11/2026) e a metodologia só avalia
  municípios com mais de 50 mil habitantes — a maioria dos municípios de
  MS ficaria de fora de qualquer forma. Fica `NULL`/"N/D".
- **Conselho municipal de educação ativo (IBGE/MUNIC)**: publicado como
  base de microdados completa, não uma tabela simples de API — fica para
  uma próxima iteração. Fica `NULL`/"N/D".
