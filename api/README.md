# API

API FastAPI qui sert a la fois les tables `Gold` stockees dans `MySQL`, les documents cartographiques stockes dans `MongoDB`, et le frontend statique.

## Lancement

### En local

```powershell
pip install -r api/requirements.txt
$env:MYSQL_HOST="127.0.0.1"
$env:MYSQL_PORT="3306"
$env:MYSQL_DATABASE="urban_data_explorer"
$env:MYSQL_USER="urban"
$env:MYSQL_PASSWORD="urban"
$env:MONGO_HOST="127.0.0.1"
$env:MONGO_PORT="27017"
$env:MONGO_DATABASE="urban_data_explorer"
uvicorn api.app.main:app --reload
```

### Avec Docker

```powershell
docker compose up --build -d api
docker compose ps
```

## Verification

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/api/meta
```

## Endpoints principaux

- `GET /health`
- `GET /sources`
- `GET /api/meta`
- `GET /api/overview?sales_year=2025`
- `GET /api/timeline?arrondissement=11`
- `GET /api/compare?left=11&right=18&sales_year=2025`
- `GET /api/quartiers?sales_year=2025`
- `GET /api/quartiers/compare?left=7510101&right=7510102&sales_year=2025`
- `GET /api/map?metric=median_price_m2&level=arrondissement&year=2025`
- `GET /api/reference/quartier`
- `GET /`

## Metriques cartographiques

`GET /api/meta` retourne aussi `spatial_sales_coverage`, qui resume le volume d'entrees, le taux de geocodage et les taux de rattachement quartier, IRIS, rue et batiment proxy.

Les niveaux `quartier`, `street` et `building` exposent toutes les metriques de vente disponibles a leur maille:

- `median_price_m2`
- `transactions`
- `median_sale_value_eur`
- `median_surface_m2`
- `median_rooms`
- `apartment_share_pct`
- `house_share_pct`

Le selecteur d'annee pilote les metriques issues des ventes. Les indicateurs de contexte par arrondissement, comme revenu, loyer, logement social et qualite de vie, utilisent les derniers millesimes agreges disponibles dans la table de synthese.

Les composantes environnementales suivantes sont disponibles au niveau arrondissement:

- `quality_of_life_score`
- `environmental_pressure_index`
- `high_noise_share_pct`
- `noise_score`
- `air_score`
