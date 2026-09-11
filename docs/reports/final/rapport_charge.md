# Rapport final - Test de charge local

Date d'execution: `2026-06-02T12:20:30`
Cible: `http://127.0.0.1:8000/health`

Concurrence maximale validee localement: **50**

> Cette mesure est une baseline HTTP locale, pas une certification de capacite production. Les parcours authentifies, la base de test representative et la supervision infrastructure doivent etre testes en staging.

| Concurrence | Requetes | Succes | Erreurs | Taux erreur | Debit req/s | p50 ms | p95 ms | max ms |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 100 | 100 | 0 | 0.0% | 127.24 | 5.68 | 24.01 | 29.21 |
| 5 | 100 | 100 | 0 | 0.0% | 403.07 | 11.23 | 16.52 | 28.08 |
| 10 | 100 | 100 | 0 | 0.0% | 281.09 | 26.1 | 113.51 | 127.96 |
| 25 | 100 | 100 | 0 | 0.0% | 341.47 | 68.97 | 78.77 | 81.31 |
| 50 | 100 | 100 | 0 | 0.0% | 337.71 | 124.96 | 145.01 | 146.75 |

## Recommandations staging

- Rejouer les memes paliers sur login, dashboard, recherche, import controle et exports avec comptes QA temporaires.
- Capturer CPU, RAM, connexions PostgreSQL et latence DB pendant chaque palier.
- Arreter l'augmentation de charge des que le taux d'erreur depasse 1% ou que le p95 depasse le SLO defini.