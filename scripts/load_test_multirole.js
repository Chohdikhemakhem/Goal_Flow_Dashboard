import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Trend, Rate } from 'k6/metrics';

// ============================================================
// Test de charge multi-roles - endpoints en LECTURE (GET)
// 6 profils : superadmin, admin, support, chef_agence,
// portefeuille_manager, membre_comite
//
// Chaque role a son propre scenario k6 avec son propre volume
// d'utilisateurs virtuels, proportionnel a son poids d'usage
// reel estime. Total = 100 VUs au pic.
// ============================================================

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';

// Identifiants de test par role -- creez ces 6 comptes dedies
// sur l'environnement de staging avant de lancer le test.
//
// ATTENTION SECURITE : si vous renseignez les mots de passe en dur
// ci-dessous plutot que via --env, ne committez JAMAIS ce fichier
// avec des vrais identifiants. Ajoutez-le a .gitignore, ou remettez
// des valeurs vides avant tout commit/push.
const CREDENTIALS = {
  superadmin: {
    email: __ENV.SUPERADMIN_EMAIL || 'superadmin.test@microcred.com.tn',
    password: __ENV.SUPERADMIN_PASSWORD || '22775520Ch++',
  },
  admin: {
    email: __ENV.ADMIN_EMAIL || 'admin.test@microcred.com.tn',
    password: __ENV.ADMIN_PASSWORD || '22775520Ch++',
  },
  support: {
    email: __ENV.SUPPORT_EMAIL || 'support.test@microcred.com.tn',
    password: __ENV.SUPPORT_PASSWORD || '22775520Ch++',
  },
  chef_agence: {
    email: __ENV.CHEF_AGENCE_EMAIL || 'chefagence.test@microcred.com.tn',
    password: __ENV.CHEF_AGENCE_PASSWORD || '22775520Ch++',
  },
  portefeuille_manager: {
    email: __ENV.PM_EMAIL || 'nour.derbel@microcred.com.tn',
    password: __ENV.PM_PASSWORD || '22775520Ch++',
  },
  membre_comite: {
    email: __ENV.COMITE_EMAIL || 'comite.test@microcred.com.tn',
    password: __ENV.COMITE_PASSWORD || '22775520Ch++',
  },
};

// Poids d'usage reel estime (doit sommer a 100)
const WEIGHTS = {
  superadmin: 5,
  admin: 10,
  support: 20,
  chef_agence: 30,
  portefeuille_manager: 20,
  membre_comite: 15,
};

// Palier de charge de reference, en % du pic. Montee etalee sur
// plusieurs minutes pour simuler un afflux realiste d'utilisateurs
// (ex: debut de journee), pas un pic instantane improbable.
const BASE_STAGES = [
  { duration: '1m', pct: 0.10 },
  { duration: '2m', pct: 0.10 },
  { duration: '1m', pct: 0.30 },
  { duration: '2m', pct: 0.30 },
  { duration: '1m', pct: 0.60 },
  { duration: '2m', pct: 0.60 },
  { duration: '2m', pct: 1.00 },
  { duration: '3m', pct: 1.00 },
  { duration: '1m', pct: 0 },
];

const PEAK_TOTAL_VUS = Number(__ENV.PEAK_VUS || 100);

function stagesForRole(weightPct) {
  const roleShare = weightPct / 100;
  return BASE_STAGES.map((s) => ({
    duration: s.duration,
    target: Math.max(1, Math.round(PEAK_TOTAL_VUS * roleShare * s.pct)) || 0,
  }));
}

const errorRate = new Rate('errors');
const loginDuration = new Trend('login_duration');

export const options = {
  scenarios: Object.fromEntries(
    Object.entries(WEIGHTS).map(([role, weight]) => [
      role,
      {
        executor: 'ramping-vus',
        exec: 'runRole',
        startVUs: 0,
        stages: stagesForRole(weight),
        env: { ROLE: role },
        tags: { role },
      },
    ])
  ),
  thresholds: {
    http_req_duration: ['p(95)<1000', 'p(99)<2500'],
    http_req_failed: ['rate<0.02'],
    errors: ['rate<0.02'],
    // Seuils specifiques par role, utile pour reperer si un role
    // en particulier degrade plus vite que les autres
    'http_req_duration{role:superadmin}': ['p(95)<1500'],
    'http_req_duration{role:chef_agence}': ['p(95)<800'],
  },
};

function login(role) {
  const creds = CREDENTIALS[role];
  if (!creds || !creds.email) {
    console.error(`Identifiants manquants pour le role ${role} - verifiez les variables d'environnement`);
    return false;
  }
  const res = http.post(
    `${BASE_URL}/api/v1/auth/login`,
    JSON.stringify({ email: creds.email, password: creds.password }),
    { headers: { 'Content-Type': 'application/json' }, tags: { role, name: 'login' } }
  );
  loginDuration.add(res.timings.duration, { role });
  const ok = check(res, { [`${role} login -> 200`]: (r) => r.status === 200 });
  errorRate.add(!ok, { role });
  return ok;
}

// Restrictions d'acces CONFIRMEES comme normales (403 attendu, pas une
// panne). Base sur les resultats du test precedent. A completer si
// d'autres restrictions legitimes sont identifiees.
const EXPECTED_403 = new Set([
  'support:GET /metrics/summary',
  'support:GET /metrics/daily',
  'support:GET /metrics/current-credits',
  'support:GET /complaints',
  'portefeuille_manager:GET /bonus/results',
  'membre_comite:GET /metrics/snapshots',
  'superadmin:GET /bonus/rules',
  'admin:GET /users',
  'admin:GET /imports/batches',
  'admin:GET /bonus/rules',
]);

function checkGet(role, name, path, params = '') {
  const expectedStatus = EXPECTED_403.has(`${role}:${name}`) ? 403 : 200;
  const res = http.get(`${BASE_URL}${path}${params}`, { tags: { role, name } });
  const ok = check(res, {
    [`${role} ${name} -> ${expectedStatus}`]: (r) => r.status === expectedStatus,
  });
  errorRate.add(!ok, { role });
  return res;
}

// Parcours commun a tous les roles : ecrans consultes le plus
// souvent au quotidien (dashboard, listes, metrics)
function commonReadFlow(role) {
  group('auth', () => {
    checkGet(role, 'GET /auth/me', '/api/v1/auth/me');
  });

  group('metrics', () => {
    checkGet(role, 'GET /metrics/summary', '/api/v1/metrics/summary');
    checkGet(role, 'GET /metrics/daily', '/api/v1/metrics/daily', '?limit=50&offset=0');
    checkGet(role, 'GET /metrics/current-credits', '/api/v1/metrics/current-credits', '?limit=50&offset=0');
  });

  sleep(0.5);
}

// Parcours specifiques par role, sur les ecrans qu'un role donne
// consulte typiquement plus que les autres
function roleSpecificFlow(role) {
  switch (role) {
    case 'superadmin':
    case 'admin':
      group('admin_only', () => {
        checkGet(role, 'GET /users', '/api/v1/users');
        checkGet(role, 'GET /imports/batches', '/api/v1/imports/batches');
        checkGet(role, 'GET /bonus/rules', '/api/v1/bonus/rules');
      });
      break;

    case 'support':
      group('support_only', () => {
        checkGet(role, 'GET /complaints', '/api/v1/complaints');
        checkGet(role, 'GET /users', '/api/v1/users');
      });
      break;

    case 'chef_agence':
      group('chef_agence_only', () => {
        checkGet(role, 'GET /metrics/charts', '/api/v1/metrics/charts', '?months=6');
        checkGet(role, 'GET /targets', '/api/v1/targets', '?limit=50&offset=0');
      });
      break;

    case 'portefeuille_manager':
      group('portefeuille_manager_only', () => {
        checkGet(role, 'GET /metrics/portfolio-performance', '/api/v1/metrics/portfolio-performance');
        checkGet(role, 'GET /metrics/charts', '/api/v1/metrics/charts', '?months=12');
        checkGet(role, 'GET /bonus/results', '/api/v1/bonus/results');
      });
      break;

    case 'membre_comite':
      group('membre_comite_only', () => {
        checkGet(role, 'GET /metrics/snapshots', '/api/v1/metrics/snapshots');
        checkGet(role, 'GET /metrics/charts', '/api/v1/metrics/charts', '?months=12');
      });
      break;
  }
}

// Suivi de l'etat de connexion par VU -- un utilisateur reel se
// connecte UNE FOIS en debut de session, pas a chaque action.
// k6 reutilise les VUs entre iterations et conserve automatiquement
// leur cookie jar, donc on se contente de ne relancer le login que
// si ce VU ne s'est pas encore connecte (ou si sa session a expire).
const loggedInVUs = {};

// Simule l'expiration de session : force un nouveau login toutes les
// ~40 iterations pour un VU donne (approx. equivalent a un cycle de
// refresh token realiste), plutot que de rester connecte a l'infini.
const SESSION_REFRESH_EVERY_N_ITERATIONS = 40;
const vuIterationCounts = {};

export function runRole() {
  const role = __ENV.ROLE;
  const vuKey = `${__VU}`;

  vuIterationCounts[vuKey] = (vuIterationCounts[vuKey] || 0) + 1;
  const needsLogin =
    !loggedInVUs[vuKey] ||
    vuIterationCounts[vuKey] % SESSION_REFRESH_EVERY_N_ITERATIONS === 0;

  if (needsLogin) {
    if (!login(role)) {
      sleep(1);
      return;
    }
    loggedInVUs[vuKey] = true;
  }

  commonReadFlow(role);
  roleSpecificFlow(role);
  // Pause realiste entre actions d'un utilisateur actif (il ne
  // spam pas l'API en continu, il lit, reflechit, clique ailleurs)
  sleep(Math.random() * 3 + 2);
}

// ============================================================
// NON INCLUS -- toujours a tester manuellement, sur base dediee :
//   POST/PUT/DELETE targets, POST bonus/rules, POST bonus/calculate,
//   POST users, POST complaints, POST imports/*
//   + endpoints restructures/recalcul (chemins a fournir)
// ============================================================
