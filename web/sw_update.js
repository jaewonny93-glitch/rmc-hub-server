/**
 * RMC Hub - 자동 업데이트 Service Worker
 * 전략: Network-First (항상 서버에서 최신 파일 우선 로드)
 * 업데이트 감지 시 즉시 새 SW 활성화 → 페이지 자동 새로고침
 */

const CACHE_VERSION = 'rmc-hub-v' + Date.now(); // 빌드마다 고유 버전
const CACHE_NAME = CACHE_VERSION;

// 캐시할 핵심 파일 목록
const CORE_ASSETS = [
  '/',
  '/index.html',
  '/flutter.js',
  '/flutter_bootstrap.js',
  '/manifest.json',
];

// ── Install: 새 SW 설치 즉시 활성화 대기 없이 바로 skipWaiting ──
self.addEventListener('install', (event) => {
  console.log('[SW] Installing new version:', CACHE_VERSION);
  // 대기 없이 즉시 활성화
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(CORE_ASSETS).catch(() => {
        // 캐시 실패해도 설치는 계속
      });
    })
  );
});

// ── Activate: 구 버전 캐시 전부 삭제 + 모든 클라이언트 즉시 제어 ──
self.addEventListener('activate', (event) => {
  console.log('[SW] Activating new version:', CACHE_VERSION);
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((name) => name !== CACHE_NAME) // 현재 버전 외 모두 삭제
          .map((name) => {
            console.log('[SW] Deleting old cache:', name);
            return caches.delete(name);
          })
      );
    }).then(() => {
      // 모든 열린 탭/창을 즉시 새 SW로 제어
      return self.clients.claim();
      // ※ 클라이언트에 새로고침 메시지 안 보냄 - 방문자 입력 루프 방지
      // 새 버전은 다음 앱 실행 시 자연스럽게 적용됨
    })
  );
});

// ── Fetch: Network-First 전략 ──
self.addEventListener('fetch', (event) => {
  // POST 등 GET 이외 요청은 무시
  if (event.request.method !== 'GET') return;
  
  const url = new URL(event.request.url);
  
  // API 요청 (Railway 서버) → 항상 네트워크 직접 요청, 캐시 안 함
  if (url.pathname.startsWith('/api/')) return;
  
  // 외부 도메인 → 무시
  if (url.origin !== self.location.origin) return;

  event.respondWith(networkFirst(event.request));
});

async function networkFirst(request) {
  try {
    // 1순위: 네트워크에서 최신 파일 가져오기
    const networkResponse = await fetch(request, {
      cache: 'no-store', // 브라우저 HTTP 캐시도 우회
    });

    if (networkResponse && networkResponse.ok) {
      // 성공하면 캐시에 저장
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, networkResponse.clone());
      return networkResponse;
    }
    throw new Error('Network response not ok');
  } catch (error) {
    // 2순위: 네트워크 실패 시 캐시에서 반환 (오프라인 대비)
    const cachedResponse = await caches.match(request);
    if (cachedResponse) {
      return cachedResponse;
    }
    // 캐시도 없으면 에러
    throw error;
  }
}

// ── Message: 수동 업데이트 명령 수신 ──
self.addEventListener('message', (event) => {
  if (event.data === 'skipWaiting') {
    self.skipWaiting();
  }
  if (event.data === 'forceUpdate') {
    // 모든 캐시 삭제 후 재활성화
    caches.keys().then((names) => Promise.all(names.map((n) => caches.delete(n))));
    self.skipWaiting();
  }
});
