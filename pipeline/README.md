# Pipeline

Le pipeline gere l'ingestion des sources ouvertes et prepare les traitements Bronze/Silver/Gold, avec ecriture des tables analytiques dans `MySQL` et des documents `GeoJSON/JSON` dans `MongoDB`.

## Commandes

### Premier lancement depuis un clone Git

Depuis la racine du depot, le script suivant prepare les bases Docker, telecharge les sources ouvertes, construit les sorties `Silver/Gold`, puis lance la validation:

```powershell
.\scripts\first-run.ps1
```

Si PowerShell bloque l'execution des scripts:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\first-run.ps1
```

Variantes utiles:

```powershell
.\scripts\first-run.ps1 -StartApi
.\scripts\first-run.ps1 -ForceDownload
.\scripts\first-run.ps1 -SkipNoise
.\scripts\first-run.ps1 -Sources dvf_2025_paris bruitparif_sig_2024
```

### En local

```powershell
pip install -r pipeline/requirements.txt
$env:MYSQL_HOST="127.0.0.1"
$env:MYSQL_PORT="3306"
$env:MYSQL_DATABASE="urban_data_explorer"
$env:MYSQL_USER="urban"
$env:MYSQL_PASSWORD="urban"
$env:MONGO_HOST="127.0.0.1"
$env:MONGO_PORT="27017"
$env:MONGO_DATABASE="urban_data_explorer"
python pipeline/run_imports.py list
python pipeline/run_imports.py download
python pipeline/run_imports.py build
python pipeline/run_imports.py validate
python pipeline/run_imports.py run
```

### Avec Docker

```powershell
docker compose run --rm pipeline python pipeline/run_imports.py list
docker compose run --rm pipeline python pipeline/run_imports.py download
docker compose run --rm pipeline python pipeline/run_imports.py build
docker compose run --rm pipeline python pipeline/run_imports.py validate
docker compose run --rm pipeline python pipeline/run_imports.py run
```

Si aucun nom n'est passe a `download`, toutes les sources declarees dans `config/sources.yaml` sont telechargees.

La commande `run` est prevue pour les executions planifiees: elle enchaine `download`, `build` et `validate`.

Options utiles:

- `--skip-download`: reutilise les fichiers `Bronze` deja presents
- `--force-download`: retelecharge les sources avant le build
- `--skip-noise`: accelere le build en utilisant les valeurs environnementales neutres
- `--skip-validate`: ignore la verification finale des tables et documents `Gold`

Exemple Windows Task Scheduler:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "cd C:\path\to\UrbanDataExplorer; .\.venv\Scripts\python.exe pipeline\run_imports.py run --skip-download --skip-noise"
```

Exemple cron:

```bash
0 3 * * 1 cd /path/to/UrbanDataExplorer && .venv/bin/python pipeline/run_imports.py run --skip-download --skip-noise
```

Les jeux `DVF` sont filtres automatiquement sur le departement `75`.
Le build enrichit ensuite les ventes avec `adresses-ban`, un fallback `BAN PLUS`, puis les rattache aux `quartiers administratifs` et aux `IRIS` de Paris.

## Sorties produites

- `MySQL` pour les tables `Silver` et `Gold`
- `MongoDB` pour les couches `GeoJSON` et les metadonnees `JSON`
- `Bronze` conserve les fichiers bruts telecharges localement

## Validation et tests

```powershell
python pipeline/run_imports.py validate
python -m unittest discover -s tests
```

`validate` verifie notamment la presence des tables `Gold`, les colonnes attendues, le catalogue de metriques et les documents MongoDB du dashboard.
