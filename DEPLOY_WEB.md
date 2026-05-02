# Hospedagem web

Este projeto ja pode ser testado como app Streamlit com login simples.

## Variaveis e secrets

Configure as chaves no ambiente da hospedagem, nunca no codigo:

```text
SERPAPI_KEY=sua_chave_serpapi
APP_AUTH_ENABLED=1
APP_ADMIN_EMAIL=seu_email
APP_ADMIN_PASSWORD=sua_senha_forte
APP_ADMIN_NAME=Administrador
```

Se `APP_ADMIN_EMAIL` e `APP_ADMIN_PASSWORD` nao forem informados e ainda nao
existir usuario no banco `pesquisa_precos_app.sqlite`, a primeira tela permite
criar o administrador inicial.

## Rodar local

```powershell
.\.venv\Scripts\python.exe -m streamlit run app_web.py
```

## Observacoes para hospedagem

- O arquivo `licitacon.sqlite` e muito grande para plataformas gratuitas comuns.
  Para o primeiro teste web, suba a aplicacao sem essa base e use CSV manual,
  PNCP, Internet e Fornecedores.
- Em Streamlit Community Cloud, coloque as variaveis acima em `secrets`.
- O banco `pesquisa_precos_app.sqlite` guarda usuarios, fornecedores, cotacoes e
  pesquisas salvas. Em hospedagem sem disco persistente, esses dados podem sumir
  a cada reinicio; depois vale migrar para Postgres/Supabase.
- O arquivo `.env` local esta no `.gitignore`; mantenha assim para nao publicar
  chaves.
