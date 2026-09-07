# DownloadManual/

Arquivos que **não têm como ser baixados automaticamente** (sem API
pública) e por isso foram exportados manualmente por alguém da equipe,
interagindo de verdade com a ferramenta original — diferente de
`data/raw/`, que guarda insumos baixados por script ou download direto
documentado. Nada aqui é versionado (ver `.gitignore`) exceto este README.

## Arquivos esperados

| Arquivo | De onde vem | Usado por |
|---|---|---|
| `base-escolas-simet-YYYY-MM-DD.xlsx` | Exportado manualmente de [conectividadenaeducacao.nic.br/#mapa-escolas](https://conectividadenaeducacao.nic.br/#mapa-escolas) (painel R Shiny sem API — ver README.md do projeto) | `processar_nicbr_simet.py` |

`processar_nicbr_simet.py` pega automaticamente o arquivo mais recente
que casar com `base-escolas-simet-*.xlsx` nesta pasta (o nome já vem com
a data do export) — não precisa editar código para atualizar, só exportar
uma planilha nova e rodar o script de novo.

## Conteúdo da planilha do NIC.br

Duas abas: `base_dados` (uma linha por escola pública brasileira,
combinando Censo Escolar/INEP, medições SIMET/NIC.br, dados de provedores/
Anatel e conectividade via satélite/MEC) e `dicionario` (o que cada coluna
significa e de qual fonte vem — documentado dentro do próprio arquivo).

Cobre só escolas **públicas** (municipal/estadual/federal); escolas
privadas não aparecem — por isso `etl.py` sempre trata isso como um
complemento ao Censo Escolar completo (`data/raw/escolas_censo_ms.csv`),
nunca como substituto.
