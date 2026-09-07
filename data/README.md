# data/

- **`data/raw/`** — insumos externos (dados oficiais baixados/buscados). Veja
  [`data/raw/README.md`](raw/README.md) para as fontes e como regerá-los.
- **`data/*.csv`** (neste diretório, fora de `raw/`) — trilha de auditoria:
  o que `etl.py` efetivamente carregou no banco na última execução,
  exportado automaticamente. Não é lido de volta por nada — serve só para
  conferir a carga sem abrir o `govtech_ms.db`. Também gerado
  automaticamente e ignorado pelo git.

Resumindo o fluxo:

```
fetch_dados_oficiais.py  ─┐
processar_censo_escolar.py ─┴─▶ data/raw/*.csv ──▶ etl.py ──▶ govtech_ms.db ──▶ data/*.csv (auditoria)
                                                      ▲
                              (se data/raw/ não existir, usa amostra sintética)
```

Nenhuma mudança é necessária em `logic.py` ou `app.py` para essa troca de
fonte: eles operam sobre o esquema do banco, não sobre a origem dos dados.
