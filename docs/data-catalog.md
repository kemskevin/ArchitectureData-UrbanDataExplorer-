# Mini Data Catalog

## Objectif

Ce document explique:

- quelles sources ouvertes sont mobilisees
- pourquoi elles ont ete retenues
- a quelle maille elles sont exploitees
- quelles limites ou biais elles introduisent

L'idee n'est pas seulement de lister des datasets, mais de justifier leur usage analytique dans le projet.

## Criteres de selection des sources

Les sources ont ete choisies selon quatre criteres:

- pertinence metier pour expliquer le logement parisien
- granularite suffisante pour produire une demo convaincante
- accessibilite en open data et reproductibilite du telechargement
- compatibilite geographique avec des jointures a Paris

## Sources principales

| Source | Usage | Niveau geographique | Format | Pourquoi ce choix |
| --- | --- | --- | --- | --- |
| DVF 2023-2025 | Transactions immobilieres, prix au m2, volumes, surfaces | adresse / mutation | TXT ZIP | reference publique la plus naturelle pour observer les ventes reelles |
| INSEE Filosofi 2021 | Revenus, niveau de vie, part imposable, pauvrete | IRIS | CSV ZIP | apporte le contexte socio-economique necessaire pour relier prix et pouvoir d'achat |
| Paris Data - Encadrement des loyers | Loyers de reference et effort locatif | quartier | CSV | permet de comparer achat et location avec une source officielle parisienne |
| Paris Data - Logements sociaux finances | Effort annuel de production sociale | arrondissement / programme | CSV | ajoute une lecture d'offre publique et de politique du logement |
| Bruitparif 2024 | Composantes du score de qualite de vie | couche SIG / zone | XLSX + ZIP | apporte la dimension environnementale que n'offrent pas les sources immobilieres classiques |
| Adresses BAN Paris | Geolocalisation des ventes DVF | adresse | CSV | necessaire pour passer d'une lecture par arrondissement a des mailles plus fines |

## Sources de reference geographique

| Source | Usage | Niveau geographique | Format | Pourquoi ce choix |
| --- | --- | --- | --- | --- |
| Arrondissements de Paris | Fond cartographique principal | arrondissement | GeoJSON | unite administrative la plus lisible pour le dashboard principal |
| Quartiers administratifs de Paris | Aggregation fine des prix | quartier | GeoJSON | niveau plus fin que l'arrondissement, tout en restant lisible en presentation |
| Voies de Paris | Representation lineaire des rues | rue | GeoJSON | evite de reduire la rue a un point et renforce la qualite visuelle de la carte |
| IRIS Paris | Enrichissements statistiques fins | IRIS | CSV avec geometries | indispensable pour relier Filosofi a des zones coherentes |

## Service complementaire

| Source | Usage | Pourquoi ce choix |
| --- | --- | --- |
| BAN Plus - lien adresse parcelle | fallback de geocodage | permet de rattraper une partie des ventes DVF non matchees directement avec `adresses-ban` |

## Justification par besoin analytique

### 1. Mesurer les prix et les dynamiques du marche

Source cle:

- `DVF`

Pourquoi:

- donne des ventes observees et non des annonces
- permet de calculer `median_price_m2`, `transactions`, `median_surface_m2`
- fournit une vraie serie temporelle 2023-2025

Limites:

- bruit sur certaines mutations atypiques
- necessite un filtrage fort
- couverture limitee au marche de vente

### 2. Relier le logement au niveau de vie

Source cle:

- `INSEE Filosofi`

Pourquoi:

- fournit un contexte socio-economique robuste
- permet des indicateurs lisibles pour la narration: revenu median, pauvrete, part imposable
- fait le lien entre accessibilite du logement et structure sociale des quartiers

Limites:

- millesime non synchrone avec toutes les autres sources
- lecture statique plutot que pleinement temporelle

### 3. Comparer achat et location

Source cle:

- `Paris Data - Encadrement des loyers`

Pourquoi:

- source officielle adaptee au contexte parisien
- utile pour construire un indicateur d'effort locatif simple a expliquer

Limites:

- loyers de reference administratifs, pas loyers de marche observes
- maille quartier, donc moins fine que certaines sorties DVF

### 4. Ajouter la dimension d'action publique

Source cle:

- `Paris Data - Logements sociaux finances`

Pourquoi:

- apporte une lecture de production sociale, absente des datasets prix / loyers
- utile pour comparer dynamiques de marche et effort d'investissement public

Limites:

- mesure des logements finances, pas du stock total de parc social
- interpretation necessite prudence d'une annee a l'autre

### 5. Ajouter la qualite de vie environnementale

Source cle:

- `Bruitparif`

Pourquoi:

- apporte des signaux differenciants pour la demo
- permet de sortir d'un dashboard purement prix / revenu
- justifie un indicateur composite `quality_of_life_score`

Limites:

- indicateur derive, avec ponderations assumees
- forte dimension methodologique a expliciter pendant la presentation

### 6. Descendre a des mailles fines

Sources cles:

- `adresses-ban`
- `BAN Plus`
- `quartier_paris`
- `voie_paris`
- `iris_paris`

Pourquoi:

- rendent possible une carte plus ambitieuse qu'un simple choropleth par arrondissement
- permettent de produire des vues `quartier`, `street`, `building`
- renforcent l'effet de demo live

Limites:

- geocodage imparfait par nature
- le niveau `building` reste un proxy d'adresse / batiment, pas une reference fonciere parfaite

## Indicateurs exposes et mode de calcul

Le dashboard expose les indicateurs suivants. Leur calcul repose sur les artefacts `Gold` produits par le pipeline.

| Indicateur | Mode de calcul | Source principale |
| --- | --- | --- |
| `median_price_m2` | mediane de `valeur fonciere / surface batie` apres filtrage des ventes DVF et regroupement par maille / annee | DVF |
| `transactions` | nombre de `transaction_id` uniques retenus dans le groupe | DVF |
| `median_sale_value_eur` | mediane de `valeur fonciere` dans le groupe | DVF |
| `median_surface_m2` | mediane de `surface batie` dans le groupe | DVF |
| `median_rooms` | mediane du nombre de pieces principales dans le groupe | DVF |
| `apartment_share_pct` | part des ventes de type appartement dans le groupe | DVF |
| `house_share_pct` | part des ventes de type maison dans le groupe | DVF |
| `median_income_eur` | mediane de `DEC_MED21` sur les IRIS rattaches a l'arrondissement | INSEE Filosofi |
| `reference_rent_majorated_eur_m2` | moyenne des loyers de reference majores des quartiers appartenant a l'arrondissement, par annee | Encadrement des loyers |
| `social_units_financed` | somme annuelle des logements sociaux finances dans l'arrondissement | Logements sociaux finances |
| `social_units_financed_5y` | somme de `social_units_financed` sur les 5 derniers millesimes disponibles | Logements sociaux finances |
| `months_income_for_1sqm` | `median_price_m2 / (median_income_eur / 12)` | DVF + INSEE Filosofi |
| `estimated_50m2_rent_effort_pct` | `reference_rent_majorated_eur_m2 * 50 / (median_income_eur / 12) * 100` | Loyers + INSEE Filosofi |
| `quality_of_life_score` | score composite sur 10 construit a partir du bruit, de l'air et de la pression environnementale | Bruitparif |
| `environmental_pressure_index` | indice sur 100 combinant pression bruit et air avant inversion en score de qualite de vie | Bruitparif |
| `high_noise_share_pct` | part de surface exposee a la classe de bruit la plus elevee | Bruitparif |
| `noise_score` | score moyen de classe bruit pondere par surface | Bruitparif |
| `air_score` | score moyen de classe air pondere par surface | Bruitparif |

Remarque:

- les vues `quartier`, `street` et `building` exposent les metriques de vente disponibles a leur maille
- a ces niveaux cartographiques fins: `median_price_m2`, `transactions`, `median_sale_value_eur`, `median_surface_m2`, `median_rooms`, `apartment_share_pct` et `house_share_pct` sont servies sur la carte
- le dashboard principal par arrondissement reste la vue qui consolide aussi les indicateurs revenu, loyer, logement social et qualite de vie
- le selecteur d'annee de la carte pilote les metriques de vente; les indicateurs de contexte par arrondissement s'appuient sur les derniers millesimes agreges disponibles

## Detail des calculs derives

### Marche immobilier

Formules clefs:

- `price_per_m2 = sale_value_eur / built_surface_m2`
- `median_price_m2 = median(price_per_m2)`
- `median_surface_m2 = median(built_surface_m2)`
- `transactions = nunique(transaction_id)`

### Accessibilite et effort locatif

Formules clefs:

- `months_income_for_1sqm = median_price_m2 / (median_income_eur / 12)`
- `estimated_50m2_rent_effort_pct = reference_rent_majorated_eur_m2 * 50 / (median_income_eur / 12) * 100`

### Logement social

Formules clefs:

- `social_units_financed = sum(nombre total de logements finances)` a l'annee et a l'arrondissement
- `social_units_financed_5y = sum(social_units_financed)` sur les 5 derniers millesimes disponibles

### Niveau de vie

Aggregation retenue:

- `median_income_eur = median(DEC_MED21)` sur les IRIS de l'arrondissement
- `poverty_rate_pct = mean(DEC_TP6021)` sur les IRIS de l'arrondissement
- `share_taxable_pct = mean(DEC_PIMP21)` sur les IRIS de l'arrondissement

## Qualite de vie

Le dashboard expose `quality_of_life_score` comme indicateur principal et conserve les composantes suivantes pour audit et cartographie avancee:

Composantes intermediaires:

```text
noise_score = sum(classe_bruit * surface_cellule) / sum(surface_cellule)
air_score = sum(classe_air * surface_cellule) / sum(surface_cellule)
high_noise_share_pct = surface(classe_bruit = 3) / surface_totale * 100

environmental_pressure_index =
  ((noise_score - 1) / 2) * 60 +
  ((air_score - 1) / 2) * 40
```

Normalisations:

```text
noise_norm = 1 - ((noise_score - 1) / 2)
air_norm = 1 - ((air_score - 1) / 2)
high_noise_norm = 1 - (high_noise_share_pct / 100)
env_norm = 1 - (environmental_pressure_index / 100)
```

```text
quality_of_life_score = 10 * (
  0.30 * noise_norm +
  0.30 * air_norm +
  0.25 * high_noise_norm +
  0.15 * env_norm
)
```

Lecture du score:

- `0` proche d'une situation environnementale tres defavorable
- `10` proche d'une situation environnementale tres favorable

Pourquoi ce choix:

- simplifier la lecture pour l'utilisateur final
- garder une methode explicable pendant la presentation
- permettre une lecture detaillee quand l'utilisateur veut auditer le score

## Couverture spatiale

Le build produit aussi `gold_sales_spatial_coverage`, expose dans `/api/meta` via `spatial_sales_coverage`.

Indicateurs principaux:

- `input_rows` et `input_transactions`: volume DVF retenu apres filtrage
- `geocoded_rows` et `geocoded_rate_pct`: couverture geographique globale
- `adresses_ban_rate_pct` et `ban_plus_rate_pct`: repartition des sources de geocodage
- `quartier_rate_pct` et `iris_rate_pct`: taux de rattachement aux mailles polygonales
- `street_rate_pct` et `building_rate_pct`: taux de rattachement aux mailles micro-geographiques
- `street_count` et `building_count`: nombre de rues et batiments proxy presents dans les sorties fines

## Remarques finales

- `DVF` reste la source la plus structurante du projet
- `Filosofi` donne la profondeur socio-economique necessaire au storytelling
- `Bruitparif` rend la demo plus originale et plus complete
- `BAN` et les referentiels geographiques donnent au projet sa finesse spatiale

L'ensemble forme un compromis realiste entre robustesse analytique, disponibilite open data et qualite de demonstration.
