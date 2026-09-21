# Rapport final - Tests de securite applicative

Date d'execution: `2026-06-02T12:20:30`

## Resume executif

- Tests de controles applicatifs: **PASS**
- Audit dependances frontend production: **PASS**
- Audit dependances Python: **PASS**
- Portee: securite applicative locale uniquement. Aucun audit infrastructure, reseau ou certification ASVS complete n'est revendique.

## Controles dynamiques locaux

| Controle | Attendu | Observe | Resultat |
|---|---:|---:|---|
| `http://127.0.0.1:8000/health` | 200 | 200 | PASS |
| `http://127.0.0.1:8000/api/v1/auth/me` | 401 | 401 | PASS |
| `http://127.0.0.1:8000/api/v1/metrics/summary` | 401 | 401 | PASS |
| `http://127.0.0.1:8000/api/v1/imports/snapshots/delete` | 401 | 401 | PASS |

## Protections verifiees automatiquement

- JWT transportes par cookies HttpOnly et non retournes dans le JSON de login.
- Rotation/revocation: le token d'acces reutilise apres logout est refuse.
- Activation de compte par jeton a usage unique, sans exposition d'un mot de passe initial.
- Blocage du compte apres tentatives de connexion invalides repetees.
- En-tetes `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy` et CSP.
- Isolation GP liee a `agent_id`, y compris lorsque deux agents portent le meme nom.
- Suppression snapshots protegee par role et type de batch.

## Limites et actions avant production

- Executer OWASP ZAP ou Burp Suite sur un staging dedie avec authentification par role.
- Executer une revue ASVS Level 3 controle par controle; la suite locale n'est pas une certification.
- Refaire les audits de dependances dans la CI et traiter toute vulnerabilite detectee.
- Tester la stack `docker-compose.prod.yml` avec `ENVIRONMENT=production` afin de confirmer la fermeture de `/docs` et `/openapi.json`.

## Audit frontend

```text
{
  "auditReportVersion": 2,
  "vulnerabilities": {},
  "metadata": {
    "vulnerabilities": {
      "info": 0,
      "low": 0,
      "moderate": 0,
      "high": 0,
      "critical": 0,
      "total": 0
    },
    "dependencies": {
      "prod": 44,
      "dev": 48,
      "optional": 33,
      "peer": 1,
      "peerOptional": 0,
      "total": 92
    }
  }
}

```

## Audit Python

```text
No known vulnerabilities found

```