// SSE 클라이언트 — 실시간 이벤트 수신
const SSE = {
    source: null,
    handlers: {},

    connect() {
        if (this.source) this.source.close();
        this.source = new EventSource('/api/events');

        this.source.onerror = () => {
            console.log('SSE reconnecting...');
            setTimeout(() => this.connect(), 3000);
        };

        // 등록된 모든 이벤트 핸들러 연결
        for (const [type, fn] of Object.entries(this.handlers)) {
            this.source.addEventListener(type, (e) => {
                try { fn(JSON.parse(e.data)); } catch(err) { console.error(err); }
            });
        }
    },

    on(eventType, handler) {
        this.handlers[eventType] = handler;
        if (this.source) {
            this.source.addEventListener(eventType, (e) => {
                try { handler(JSON.parse(e.data)); } catch(err) { console.error(err); }
            });
        }
    },

    disconnect() {
        if (this.source) { this.source.close(); this.source = null; }
    }
};

// 페이지 로드 시 자동 연결
document.addEventListener('DOMContentLoaded', () => SSE.connect());

// API 호출 헬퍼
async function api(url, options = {}) {
    const resp = await fetch(url, {
        headers: { 'Content-Type': 'application/json' },
        ...options,
    });
    return resp.json();
}
