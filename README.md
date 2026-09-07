# GovTech MS — Painel Integrado de Conectividade Escolar

Projeto da disciplina **Governança, Empreendedorismo e Inovação**, do
**Mestrado em Computação Aplicada da UFMS**.

**Professor:** Prof. Dr. Marcelo Augusto Santos Turine.

**Autores:** Paulo Henrique da Silva Leite e Gabriel Angeramis Vargas
Goulart.

## Contexto

O Ranking Connected Smart Cities avalia a conectividade das escolas
brasileiras a partir de um indicador do Censo Escolar (INEP) que é apenas
declaratório e estático ("tem ou não tem banda larga"). O GovTech MS
propõe uma avaliação dinâmica, em 3 fases, para os 79 municípios de Mato
Grosso do Sul:

1. **Mapeamento** — localização espacial de escolas urbanas e rurais e
   indicadores de governança pública municipal.
2. **Comparativo técnico** — cruza matrículas (INEP) com a velocidade real
   medida por escola (SIMET/NIC.br, quando disponível) ou por região
   (Ookla Speedtest, como estimativa) para calcular a banda por aluno no
   turno de pico.
3. **Engenharia de soluções** — calcula um Índice de Prioridade de
   Intervenção (IPI) por escola e recomenda tecnologias alternativas
   (fibra, satélite de órbita baixa, rádio) para os casos mais críticos.

O painel tem uma 4ª aba, **"📚 Fontes & Metodologia"**, com um resumo de
cada fonte de dados, o que ainda não é oficial (e por quê) e as fórmulas
usadas — pensada para consulta rápida durante a apresentação, sem precisar
abrir o código ou este README.

## Procedência dos dados (o que é oficial, o que ainda é ilustrativo)

O painel mostra isso dinamicamente na barra lateral (lido de
`metadata_execucao`, gravado por `etl.py`), mas resumindo:

| Camada | Status | Fonte |
|---|---|---|
| Municípios (código, população) | 🟢 Oficial | API de Localidades do IBGE |
| Investimento em educação por município | 🟢 Oficial | Siconfi/Tesouro Nacional (RREO, Anexo 02 — Despesas por Função) |
| Escolas (localização, matrículas, internet, banda larga, wifi/rede local) | 🟢 Oficial | Censo Escolar 2025 (INEP), filtrado a MS |
| Latitude/longitude das escolas | 🟢 Real (1.377/1.859) · 🟡 Aproximada (restante) | Real via NIC.br para escolas públicas; sede do município para as demais (ver `geo_aproximada` no banco) |
| Velocidade por escola | 🟢 Medição real (1.105) · 🟡 Estimativa calibrada (748) | Real (SIMET) via planilha exportada manualmente do painel Conectividade na Educação (NIC.br); sem medição própria, ancorada na média real do Ookla Speedtest por município |
| Nota de transparência (CGU) | ⚪ Indisponível | Mapa Brasil Transparente fora do ar p/ manutenção; só cobre municípios >50 mil hab. |
| Conselho municipal de educação ativo | ⚪ Indisponível | MUNIC/IBGE publicada como microdado completo, não integrado nesta versão |

Se `data/raw/` não existir (dados oficiais não buscados), cada camada
acima recua sozinha para uma amostra sintética equivalente, e o painel
avisa isso na barra lateral — ele nunca finge que um dado sintético é
oficial. Veja [`data/raw/README.md`](data/raw/README.md) para os
detalhes de cada limitação e como buscar/atualizar os dados oficiais.

### Fontes investigadas, mas não integradas (ou só parcialmente)

Documentado para deixar claro o processo de decisão, não só o resultado
final:

| Fonte | Status | Detalhe |
|---|---|---|
| [conectividadenaeducacao.nic.br](https://conectividadenaeducacao.nic.br/#mapa-escolas) (mapa de escolas) | 🟡 Integrado via export manual | Sem API — app R Shiny com sessão via WebSocket (confirmado inspecionando os scripts carregados). A equipe exportou manualmente a planilha completa (download/upload/latência/jitter/perda de pacotes/geolocalização reais) através do próprio painel — ação humana, não automação — cobrindo 1.377 escolas públicas de MS. Ver [`DownloadManual/README.md`](DownloadManual/README.md) |
| [qualidadedainternet.nic.br](https://qualidadedainternet.nic.br/) | ⚪ Não integrado | Mesma limitação técnica (Shiny/sessão), e a granularidade (por estado) é pior que os 79 municípios/1.377 escolas já cobertos |
| Giga Maps (UNICEF/ITU) | ⚪ Não integrado | Conectividade real de +80 mil escolas brasileiras, mas API exige cadastro e permissão por país (protocolo Delta Sharing) — não é self-serve |
| CGU — Escala Brasil Transparente | ⚪ Não integrado | Portal fora do ar para manutenção; só cobre municípios >50 mil habitantes |

O caminho recomendado para automatizar o dado real do SIMET por escola
(sem depender de export manual a cada atualização) é uma solicitação
formal de parceria acadêmica ao NIC.br — o mesmo canal que eles já usam
para compartilhar esse dado com a Giga e para a pesquisa TIC Educação.

## Estrutura do repositório

```text
.
├── app.py                       # Painel Streamlit (Fases 1, 2 e 3)
├── database.py                   # DDL: cria o esquema do govtech_ms.db
├── etl.py                        # DML: carga (oficial se disponível, senão sintética)
├── fetch_dados_oficiais.py       # Busca IBGE + Siconfi -> data/raw/municipios_oficiais.csv
├── processar_censo_escolar.py    # Filtra o Censo Escolar (INEP) -> data/raw/escolas_censo_ms.csv
├── processar_ookla.py            # Filtra o Ookla Speedtest -> data/raw/conectividade_municipio_ookla.csv
├── processar_nicbr_simet.py      # Filtra a planilha do NIC.br -> data/raw/medicoes_reais_nicbr.csv
├── tile_math.py                  # Conversão lat/lon <-> quadkey (usado por processar_ookla.py)
├── logic.py                      # Regras de negócio (IPI, banda/aluno, recomendador) — testável isoladamente
├── requirements.txt              # Dependências de execução
├── requirements-dev.txt          # + pytest, para rodar os testes
├── pytest.ini
├── .streamlit/config.toml
├── run_app.bat / run_app.sh      # Atalho: sobe o painel com um clique/comando
├── DownloadManual/                # Planilhas exportadas manualmente (sem API) — ver DownloadManual/README.md
├── data/
│   ├── raw/                      # Insumos externos (dados oficiais) — ver data/raw/README.md
│   └── *.csv                     # Trilha de auditoria da última carga (gerada por etl.py)
└── tests/
    ├── test_logic.py             # Testes unitários das regras de negócio
    ├── test_tile_math.py         # Testes da conversão lat/lon <-> quadkey
    └── test_etl_fallback.py      # Testes de integração dos caminhos oficial/sintético do ETL
```

## Como rodar

**Atalho:** dê duplo clique em `run_app.bat` (Windows) — ele cria o
ambiente virtual, instala as dependências e inicializa o banco na
primeira vez que roda, e nas vezes seguintes só sobe o painel direto. No
Linux/Mac, o equivalente é `./run_app.sh` (dê `chmod +x run_app.sh` uma
vez antes). Passo a passo manual, caso prefira:

```bash
# 1. (Recomendado) crie e ative um ambiente virtual
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate      # Linux/Mac

# 2. Instale as dependências
pip install -r requirements.txt

# 3. (Opcional, mas recomendado) busque os dados oficiais —
#    ver data/raw/README.md para os downloads manuais necessários
python fetch_dados_oficiais.py
python processar_censo_escolar.py
python processar_ookla.py

# 3b. (Opcional) exporte manualmente a planilha do NIC.br em
#     https://conectividadenaeducacao.nic.br/#mapa-escolas, salve em
#     DownloadManual/ (ver DownloadManual/README.md) e rode:
python processar_nicbr_simet.py

# 4. Crie o esquema do banco SQLite
python database.py

# 5. Carregue os dados (oficiais, se o passo 3 rodou; sintéticos, senão)
python etl.py

# 6. Rode o painel
streamlit run app.py
```

Pular o passo 3 não quebra nada — o painel funciona igual, só que com a
amostra de demonstração (e avisa isso na barra lateral).

## Tema claro/escuro

`.streamlit/config.toml` define uma paleta de marca para os modos claro e
escuro (`[theme.light]` / `[theme.dark]`). Para trocar, no próprio painel:
menu **⋮** (canto superior direito) → **Settings** → **Theme** → *Light*,
*Dark* ou *Use system setting*. Os gráficos (Plotly) acompanham a troca
automaticamente; o mapa (Folium/OpenStreetMap) permanece claro nos dois
modos — tiles gratuitos com estilo escuro (ex.: CartoDB dark_matter)
passaram a exigir chave de API (mesmo motivo pelo qual o painel já usa
OpenStreetMap em vez de CartoDB — ver seção de correções).

## Rodando os testes

```bash
pip install -r requirements-dev.txt
pytest
```

## Modelo de dados

Cinco tabelas em `govtech_ms.db`:

| Tabela | Conteúdo |
|---|---|
| `municipios` | Governança pública municipal (IBGE + Siconfi) |
| `escolas` | Localização, conectividade, wifi/rede local e matrículas (INEP + geolocalização real do NIC.br quando disponível) |
| `medicoes_simet` | Velocidade/latência/jitter por escola — medição real (NIC.br/SIMET), estimativa calibrada com Ookla, ou sintética genérica (`fonte_medicao` diz qual) |
| `alternativas_mercado` | Provedores e tecnologias avaliados na Fase 3 |
| `metadata_execucao` | Procedência de cada carga (oficial/calibrada/sintética) e data/hora |

## Atribuição de dados de terceiros

Os dados de velocidade usam o **Speedtest by Ookla® Global Fixed Broadband
Performance Tiles** (trimestre 2026-Q2), sob licença
[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) —
uso não comercial, com atribuição e compartilhamento pela mesma licença.
Adequado para este projeto acadêmico; qualquer uso comercial do painel
precisaria rever essa fonte (ou removê-la). Fonte:
[github.com/teamookla/ookla-open-data](https://github.com/teamookla/ookla-open-data).

A medição real por escola (velocidade, latência, jitter, perda de
pacotes) e a geolocalização real vêm do painel **Conectividade na
Educação**, do **NIC.br** (Núcleo de Informação e Coordenação do Ponto
BR) — dados coletados via SIMET (Sistema de Medição de Tráfego da
Internet), combinados com Censo Escolar/INEP, Anatel e MEC/MCOM. A
planilha foi exportada manualmente pela equipe através do painel público
em [conectividadenaeducacao.nic.br](https://conectividadenaeducacao.nic.br/#mapa-escolas).

## Correções e decisões feitas em relação ao rascunho inicial

Este projeto partiu de uma especificação (`instrucoes.txt`) gerada por
outra IA, depois passou por uma segunda rodada para substituir a amostra
sintética por dados oficiais. Ao longo do caminho:

**Da primeira revisão (spec → código):**
- `requirements.txt` listava `sqlite3` como dependência pip (é módulo da
  biblioteca padrão; quebraria a instalação).
- Bug de precedência na fórmula do IPI: `* 100` multiplicava só o último
  termo da soma, não o índice inteiro.
- Carga de dados não idempotente (`INSERT OR REPLACE` sem chave explícita
  duplicava medições/provedores a cada `python etl.py`).
- `NaN` do pandas tratado como dado ausente antes de chegar às regras de
  negócio — sem isso, o recomendador de tecnologia deixaria de sugerir
  qualquer coisa justamente para as escolas sem nenhuma medição.
- Regras de negócio extraídas para `logic.py`, testáveis isoladamente.

**Da integração com dados oficiais:**
- A API do Siconfi (RREO) exige `co_tipo_demonstrativo=RREO` **ou**
  `RREO Simplificado` dependendo do município — usar só `RREO` deixava
  66 dos 79 municípios de MS sem dado (municípios menores publicam o
  demonstrativo simplificado). `fetch_dados_oficiais.py` tenta os dois.
- A mesma consulta retorna duas linhas com `conta = "Educação"` (uma para
  o total, outra só para despesas intra-orçamentárias) — sem filtrar por
  `cod_conta`, o valor coletado ficaria ambíguo entre as duas.
- `IN_BANDA_LARGA` vem em branco no Censo Escolar quando a escola não tem
  internet (o questionário nem pergunta); tratado como `0`, não como erro.
- O Censo Escolar aberto não publica latitude/longitude por escola — as
  coordenadas usadas são uma aproximação pela sede do município,
  marcada explicitamente (`geo_aproximada = 1`) em vez de passar por real.
- O mapa passou a agrupar marcadores em cluster: o volume real (≈1.860
  escolas) tornaria o mapa anterior (um `folium.Marker` solto por escola)
  lento e, sem coordenada exata por escola, enganosamente "preciso".
- A barra lateral passou a ler a procedência de cada carga de
  `metadata_execucao` em vez de um aviso fixo no código — o texto nunca
  fica dessincronizado do que a carga realmente usou.

**Da calibração da velocidade com Ookla Speedtest:**
- Não existe um dataset aberto/automatizável de medição por escola
  (SIMET/NIC.br fica atrás de um app Shiny sem API — ver mais abaixo),
  mas o Ookla Open Data publica velocidade REAL medida por usuários em
  tiles de ~600m, cobrindo o mundo todo, sem cadastro. Usado para ancorar
  a simulação por escola numa média real do seu município, em vez de
  sortear de uma faixa genérica arbitrária — ver
  `logic.simular_medicao_calibrada` e `processar_ookla.py`.
- O arquivo do Ookla é global (~6,4 milhões de tiles); `processar_ookla.py`
  projeta só as colunas necessárias e filtra pelo bounding box de MS antes
  de qualquer outro processamento, para manter o uso de memória baixo.
- Conversão de lat/lon para o tile do Ookla usa quadkeys (sistema de tiles
  do Bing Maps) em vez de comparar geometria (WKT) ponto a ponto — mais
  rápido e sem depender de shapely/geopandas. Isolado em `tile_math.py` e
  validado contra o exemplo oficial da documentação da Microsoft
  (`tests/test_tile_math.py`).
- Nem todo tile tem dado (baixa densidade de testes em áreas rurais); a
  busca expande o raio em ordem de distância até acumular testes
  suficientes, em vez de exigir o tile exato — na prática, achou dado
  real para 79/79 municípios de MS no trimestre usado.

**Da integração com a medição real do NIC.br (SIMET):**
- Investigamos dois painéis do NIC.br (`conectividadenaeducacao.nic.br` e
  `qualidadedainternet.nic.br`) e confirmamos, inspecionando os scripts
  carregados por cada um, que são apps **R Shiny** com sessão via
  WebSocket — sem API pública, sem endpoint programável. O botão de
  download de cada um só ativa dentro de uma sessão de navegador ao vivo.
  Em vez de automatizar isso via navegador (Selenium/Playwright) — frágil,
  sem termo de uso publicado autorizando extração em massa, e uma
  dependência pesada nova — a equipe exportou a planilha manualmente, uma
  única vez, interagindo com o painel como qualquer usuário faria.
- A planilha exportada é nacional (~138 mil escolas); `processar_nicbr_simet.py`
  filtra para MS e cobre só escolas públicas (municipal/estadual/federal)
  — escolas privadas não aparecem nela, então continuam usando a
  estimativa via Ookla.
- Os campos numéricos de medição vêm em formato brasileiro (vírgula
  decimal, ex. `"63,47"`) misturado com texto (`"sem medidor"` quando não
  há medição) na mesma coluna — precisou de um parser tolerante
  (`_parse_numero_br`) em vez de `float()` direto.
- Encontramos uma inconsistência nas colunas `entorno_download`/
  `entorno_upload` da planilha (valores idênticos entre as duas, o que
  não deveria acontecer) — decidimos não usar essas colunas por enquanto
  e confiar só na medição própria de cada escola (`simet_mean_*`), que
  está limpa.
- Como a mesma escola pode ter geolocalização real (NIC.br) e/ou medição
  real (NIC.br) de forma independente uma da outra — geolocalização é bem
  mais comum (1.377/1.377) que medição própria (1.105/1.377), pois o
  medidor é opt-in — `etl.py` trata as duas coisas separadamente:
  substitui a coordenada aproximada sempre que há geolocalização real, e
  só substitui a estimativa Ookla por medição real quando ela de fato
  existir para aquela escola.
