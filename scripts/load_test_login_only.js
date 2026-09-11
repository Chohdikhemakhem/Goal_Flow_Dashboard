import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend, Rate } from 'k6/metrics';

// ============================================================
// Test isole du LOGIN uniquement.
// Objectif : confirmer que le goulot d'etranglement identifie
// precedemment (p95 ~60s sous charge) est resolu par :
//   - 8 workers Uvicorn (au lieu d'1 seul avec --reload)
//   - pool_size=8 / max_overflow=2 par worker (au lieu des
//     valeurs par defaut SQLAlchemy 5/10)
//
// Monte progressivement jusqu'a 200 VUs, tous en train de se
// (re)logger en boucle -- scenario volontairement plus dur que
// l'usage reel, pour bien faire ressortir la limite du login.
// ============================================================

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const TEST_EMAIL = __ENV.TEST_USER_EMAIL;
const TEST_PASSWORD = __ENV.TEST_USER_PASSWORD;

const loginDuration = new Trend('login_duration');
const errorRate = new Rate('login_errors');

export const options = {
  scenarios: {
    login_only: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '30s', target: 20 },
        { duration: '1m', target: 20 },
        { duration: '30s', target: 50 },
        { duration: '1m', target: 50 },
        { duration: '30s', target: 100 },
        { duration: '1m', target: 100 },
        { duration: '30s', target: 150 },
        { duration: '1m', target: 150 },
        { duration: '30s', target: 200 },
        { duration: '1m', target: 200 },
        { duration: '30s', target: 0 },
      ],
    },
  },
  thresholds: {
    // Seuils volontairement stricts : un login doit rester rapide
    // meme a 200 utilisateurs simultanes.
    login_duration: ['p(95)<1500', 'p(99)<3000'],
    login_errors: ['rate<0.01'],
  },
};

export default function () {
  const res = http.post(
    `${BASE_URL}/api/v1/auth/login`,
    JSON.stringify({ email: TEST_EMAIL, password: TEST_PASSWORD }),
    { headers: { 'Content-Type': 'application/json' }, tags: { name: 'login' } }
  );
  loginDuration.add(res.timings.duration);
  const ok = check(res, {
    'login -> 200': (r) => r.status === 200,
    'login -> reponse sous 3s': (r) => r.timings.duration < 3000,
  });
  errorRate.add(!ok);

  sleep(Math.random() * 1 + 0.5);
}
