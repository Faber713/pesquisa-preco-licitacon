# Migrations

Esta pasta guarda migracoes graduais de schema e dados.

Ordem recomendada nesta fase:

1. Inicializar `database/app/app.sqlite` pelo `app_storage.py`.
2. Migrar dados legados de `database/app/app.sqlite` somente se necessario.
3. Recriar RAW enxuto em `database/raw/licitacon_raw.sqlite`.
4. Recriar operacional em `database/operational/licitacon_search.sqlite`.

Evite colocar dumps grandes nesta pasta. Scripts pequenos, SQL versionado e notas de migracao sao suficientes.

Para copiar o banco APP legado:

```powershell
python -m database.migrations.migrate_app_db
```
