# Calcul distribue (competence C2.2)

Ce document decrit la brique de calcul distribue ajoutee au pipeline, la facon
de la lancer, et la lecture honnete des resultats a presenter en soutenance.

## Pourquoi

Le referentiel Bloc 1 attend explicitement la mise en oeuvre d'un systeme
distribue (competence C2.2). L'agregation des transactions DVF par maille
geographique (`aggregate_sales_metrics`) est le coeur calculatoire du build :
elle execute des `groupBy` massifs appeles cinq fois (arrondissement, quartier,
IRIS, rue, batiment). C'est donc l'etape naturelle a distribuer.

## Architecture

Le meme calcul existe en trois implementations interchangeables, qui renvoient
un resultat strictement identique :

| Moteur | Execution | Usage |
| --- | --- | --- |
| `pandas` | mono-machine, en memoire | defaut du build, le plus rapide sur le volume reel |
| `dask` | cluster Dask local (scheduler + workers) | calcul distribue sans JVM |
| `spark` | cluster Spark (local ou Docker, master + workers) | demonstration distribuee complete |

Le moteur est selectionnable sans modifier le code appelant :

```python
aggregate_sales_metrics(data, ["arrondissement", "year"])                 # pandas (defaut)
aggregate_sales_metrics(data, ["arrondissement", "year"], engine="spark") # Spark
```

Ou via variable d'environnement, pour piloter tout le build :

```bash
UDE_AGG_ENGINE=spark python pipeline/run_imports.py build
```

Pandas reste le defaut : le comportement du build existant n'est jamais modifie.

## Cluster Spark dockerise

Un cluster Spark complet est fourni en complement de la stack existante
(`mysql`, `mongo`, `api`). Il comprend un master et deux workers scalables.

```bash
# Demarrer le cluster Spark
docker compose -f docker-compose.yml -f docker-compose.spark.yml up -d \
  spark-master spark-worker-1 spark-worker-2

# UI du master Spark
# http://localhost:8080  (on y voit les workers et les jobs s'executer)

# Soumettre le job d'agregation distribuee au cluster
docker compose -f docker-compose.yml -f docker-compose.spark.yml run --rm spark-submit
```

Scalabilite horizontale : ajouter un `spark-worker-3` dans
`docker-compose.spark.yml`, ou augmenter `SPARK_WORKER_CORES` /
`SPARK_WORKER_MEMORY` pour scaler verticalement. C'est l'argument
d'architecture scalable et resiliente (competence C1.4).

## Execution locale (sans Docker)

```bash
pip install -r pipeline/requirements-distributed.txt   # dask + pyspark (necessite un JDK 17+)

# Spark en mode local multi-coeurs
UDE_SPARK_MASTER="local[*]" python pipeline/jobs/spark_aggregate_job.py

# Benchmark pandas vs distribue
python pipeline/benchmarks/aggregation_benchmark.py --rows 500000 --engines pandas spark
```

## Preuve d'equivalence

Le test `tests/test_distributed_aggregation.py` verifie que Dask et Spark
produisent exactement la meme sortie que pandas (memes colonnes, memes valeurs,
meme tri). C'est la garantie de non-regression : distribuer le calcul ne change
pas les resultats.

```bash
python -m unittest tests.test_distributed_aggregation
```

## Lecture des performances (competence C2.4)

Mesure type sur ce projet (300 000 lignes synthetiques, agregation par
arrondissement / annee) :

| Moteur | Temps | Speedup vs pandas |
| --- | --- | --- |
| pandas | ~0.1 s | x1 |
| spark (local) | ~38 s | x0.003 |

**Cette mesure est volontairement honnete et doit etre presentee telle quelle.**

Sur le volume reel du projet (DVF Paris tient en memoire), pandas est plus
rapide : l'overhead du distribue (serialisation, demarrage JVM, echanges
reseau entre workers) depasse largement le gain de parallelisme. Ce n'est pas
un defaut du code, c'est le comportement attendu de tout moteur distribue sur
de petits volumes.

L'interet du distribue n'est donc pas la vitesse ici, mais :

- la **scalabilite** : la meme architecture traite des volumes qui ne tiennent
  pas en RAM d'une seule machine, en ajoutant des workers ;
- la **resilience** : Spark relance automatiquement les taches d'un worker
  defaillant ;
- l'**architecture** : on demontre la maitrise d'un vrai cluster (master +
  workers), pas seulement d'un script local.

### Argumentaire pour le jury

> Nous avons distribue l'etape d'agregation, qui est le coeur calculatoire du
> pipeline, avec Spark sur un cluster master + workers dockerise. Le resultat
> est strictement identique a la version pandas, ce que nous prouvons par un
> test d'equivalence automatise. Sur le volume actuel, pandas reste plus rapide
> car les donnees tiennent en memoire : l'overhead du distribue domine. Nous
> assumons ce choix, car la valeur du distribue est la scalabilite et la
> resilience, pas la vitesse a petite echelle. L'architecture traiterait sans
> modification un volume national de DVF en ajoutant des workers.

C'est exactement le type de recul professionnel que le guide de soutenance
valorise (reconnaitre une limite n'est pas un echec).
