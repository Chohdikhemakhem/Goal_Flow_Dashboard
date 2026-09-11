# Livrables QA finaux Metrics/GP/MCR

Generation: `2026-06-02T12:20:30`

## Resume

- Tests automatises backend: **PASS**
- Build frontend: **PASS**
- Audit npm production: **PASS**
- Audit Python: **PASS**
- Controles HTTP locaux: **PASS**
- Concurrence HTTP locale maximale validee: **50**

## Fonctionnalite ajoutee

Le Super Admin peut supprimer une ou plusieurs snapshots erronees depuis le dashboard. La confirmation est obligatoire et le backend refuse la suppression des batches CURRENT_STATE ou HISTORICAL_MONTH.

## Usage local

Utiliser `http://localhost:5173` pour le frontend local. Ne pas alterner entre `localhost` et `127.0.0.1`: les cookies d'authentification SameSite sont volontairement stricts.

## Limites

Ce lot constitue une validation applicative locale automatisee. Une recette staging reste obligatoire pour les parcours navigateur complets, les fichiers MCR representatifs, les exports visuels et la capacite production.

## Capture QA

- `captures/login.png`: ouverture locale sur formulaire de connexion vide, sans preconnexion automatique.