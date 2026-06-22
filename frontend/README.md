# Frontend

Frontend statique en JavaScript servi directement par FastAPI.

## Experience utilisateur

- un panneau haut pour choisir la vue cartographique: metrique, niveau et annee
- un panneau de comparaison unique pour choisir `Arrondissement A` et `Arrondissement B`
- un switch dans le comparateur pour basculer entre comparaison `arrondissement` et `quartier`
- des listes de quartiers qui suivent automatiquement les arrondissements selectionnes
- une interface epuree, sans blocs d'aide longs dans les panneaux principaux

## Stack

- HTML / CSS / JavaScript natifs
- MapLibre GL via CDN
- API FastAPI pour les donnees

## Lancement

Le frontend n'est pas lance separement: il est servi par l'API FastAPI.

```powershell
uvicorn api.app.main:app --reload
```

Ou avec Docker:

```powershell
docker compose up --build -d api
```

## Acces

- page principale: `http://127.0.0.1:8000/`
- donnees: `http://127.0.0.1:8000/api/meta`

## Ce que le frontend consomme

- `GET /api/meta`
- `GET /api/overview`
- `GET /api/timeline`
- `GET /api/compare`
- `GET /api/quartiers`
- `GET /api/quartiers/compare`
- `GET /api/map`
- `GET /api/reference/{level}`

`/api/meta` fournit aussi `spatial_sales_coverage`, utilise comme metadonnee de qualite pour documenter la couverture geographique du build.
