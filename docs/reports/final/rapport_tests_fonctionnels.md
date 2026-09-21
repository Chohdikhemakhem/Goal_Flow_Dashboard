# Rapport final - Tests fonctionnels

Date d'execution: `2026-06-02T12:20:30`

## Resume

- Suite automatisee backend: **PASS**
- Build frontend React/Vite: **PASS**
- Scenarios automatises executes: authentification cookies HttpOnly, activation de compte, logout/revocation, verrouillage login, scope GP homonyme, normalisation du nom GP, en-tetes de securite, suppression snapshots Super Admin.

## Fonctionnalite snapshots Super Admin

- Endpoint: `POST /api/v1/imports/snapshots/delete`.
- Controle d'acces: `SUPER_ADMIN` uniquement.
- Garde-fou: seuls les batches `SNAPSHOT` sont supprimables.
- Effet: suppression des lignes `LoanRaw`, suppression du batch, recalcul des agrégats journaliers impactes.
- UI: selection multiple, confirmation obligatoire, rafraichissement immediat du dashboard.

## Limites restantes

- Les parcours navigateur complets imports/exports/objectifs doivent encore etre automatises avec Playwright sur un environnement staging contenant des fichiers MCR de test.
- Les exports PDF/Excel metier doivent etre relus visuellement sur les jeux de donnees QA avant production.

## Logs

```text
C:\Users\chohd\Documents\Codex\2026-05-11\contexte-build-a-full-stack-web\backend\.venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
  from starlette.testclient import TestClient as TestClient  # noqa
test_login_rate_limiting_locks_account_after_repeated_failures (backend.tests.test_security_controls.SecurityControlsTestCase.test_login_rate_limiting_locks_account_after_repeated_failures) ... 2026-06-02 12:20:34,896 | INFO | httpx | HTTP Request: POST http://testserver/api/v1/auth/login "HTTP/1.1 401 Unauthorized"
2026-06-02 12:20:35,230 | INFO | httpx | HTTP Request: POST http://testserver/api/v1/auth/login "HTTP/1.1 401 Unauthorized"
2026-06-02 12:20:35,556 | INFO | httpx | HTTP Request: POST http://testserver/api/v1/auth/login "HTTP/1.1 401 Unauthorized"
2026-06-02 12:20:35,881 | INFO | httpx | HTTP Request: POST http://testserver/api/v1/auth/login "HTTP/1.1 401 Unauthorized"
2026-06-02 12:20:36,201 | INFO | httpx | HTTP Request: POST http://testserver/api/v1/auth/login "HTTP/1.1 401 Unauthorized"
2026-06-02 12:20:36,525 | INFO | httpx | HTTP Request: POST http://testserver/api/v1/auth/login "HTTP/1.1 401 Unauthorized"
2026-06-02 12:20:36,531 | INFO | httpx | HTTP Request: POST http://testserver/api/v1/auth/login "HTTP/1.1 429 Too Many Requests"
ok
test_login_uses_httponly_cookies_and_passwords_are_not_exposed (backend.tests.test_security_controls.SecurityControlsTestCase.test_login_uses_httponly_cookies_and_passwords_are_not_exposed) ... 2026-06-02 12:20:37,532 | INFO | httpx | HTTP Request: POST http://testserver/api/v1/auth/login "HTTP/1.1 200 OK"
2026-06-02 12:20:37,546 | INFO | httpx | HTTP Request: POST http://testserver/api/v1/users "HTTP/1.1 400 Bad Request"
2026-06-02 12:20:37,927 | INFO | httpx | HTTP Request: POST http://testserver/api/v1/users "HTTP/1.1 200 OK"
2026-06-02 12:20:38,262 | INFO | httpx | HTTP Request: POST http://testserver/api/v1/auth/set-password "HTTP/1.1 200 OK"
2026-06-02 12:20:38,268 | INFO | httpx | HTTP Request: POST http://testserver/api/v1/auth/set-password "HTTP/1.1 400 Bad Request"
2026-06-02 12:20:38,603 | INFO | httpx | HTTP Request: POST http://testserver/api/v1/auth/login "HTTP/1.1 200 OK"
ok
test_logout_invalidates_existing_access_token (backend.tests.test_security_controls.SecurityControlsTestCase.test_logout_invalidates_existing_access_token) ... 2026-06-02 12:20:39,614 | INFO | httpx | HTTP Request: POST http://testserver/api/v1/auth/login "HTTP/1.1 200 OK"
2026-06-02 12:20:39,623 | INFO | httpx | HTTP Request: GET http://testserver/api/v1/auth/me "HTTP/1.1 200 OK"
2026-06-02 12:20:39,642 | INFO | httpx | HTTP Request: POST http://testserver/api/v1/auth/logout "HTTP/1.1 200 OK"
2026-06-02 12:20:39,650 | INFO | httpx | HTTP Request: GET http://testserver/api/v1/auth/me "HTTP/1.1 401 Unauthorized"
ok
test_portfolio_manager_scope_is_bound_to_agent_id_even_for_duplicate_names (backend.tests.test_security_controls.SecurityControlsTestCase.test_portfolio_manager_scope_is_bound_to_agent_id_even_for_duplicate_names) ... 2026-06-02 12:20:40,763 | INFO | httpx | HTTP Request: POST http://testserver/api/v1/auth/login "HTTP/1.1 200 OK"
2026-06-02 12:20:40,793 | INFO | httpx | HTTP Request: GET http://testserver/api/v1/metrics/summary "HTTP/1.1 200 OK"
2026-06-02 12:20:40,826 | INFO | httpx | HTTP Request: GET http://testserver/api/v1/metrics/daily?limit=50 "HTTP/1.1 200 OK"
ok
test_portfolio_manager_scope_matches_agent_name_punctuation_variants (backend.tests.test_security_controls.SecurityControlsTestCase.test_portfolio_manager_scope_matches_agent_name_punctuation_variants) ... 2026-06-02 12:20:41,815 | INFO | httpx | HTTP Request: POST http://testserver/api/v1/auth/login "HTTP/1.1 200 OK"
2026-06-02 12:20:41,831 | INFO | httpx | HTTP Request: GET http://testserver/api/v1/metrics/summary "HTTP/1.1 200 OK"
ok
test_security_headers_are_applied (backend.tests.test_security_controls.SecurityControlsTestCase.test_security_headers_are_applied) ... 2026-06-02 12:20:42,166 | INFO | httpx | HTTP Request: GET http://testserver/health "HTTP/1.1 200 OK"
ok
test_super_admin_can_delete_snapshots_but_not_current_state (backend.tests.test_security_controls.SecurityControlsTestCase.test_super_admin_can_delete_snapshots_but_not_current_state) ... 2026-06-02 12:20:43,116 | INFO | httpx | HTTP Request: POST http://testserver/api/v1/auth/login "HTTP/1.1 200 OK"
2026-06-02 12:20:43,144 | WARNING | app.services.imports | Deleted snapshot batches ids=[1] rows=1 affected_dates=[datetime.date(2026, 5, 10)]
2026-06-02 12:20:43,144 | INFO | httpx | HTTP Request: POST http://testserver/api/v1/imports/snapshots/delete "HTTP/1.1 200 OK"
2026-06-02 12:20:43,171 | INFO | httpx | HTTP Request: POST http://testserver/api/v1/imports/snapshots/delete "HTTP/1.1 400 Bad Request"
ok

----------------------------------------------------------------------
Ran 7 tests in 9.257s

OK

```