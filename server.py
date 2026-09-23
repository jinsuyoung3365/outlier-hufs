#!/usr/bin/env python3
"""
아웃라이어 로컬 서버
 - 이 폴더의 사이트(index.html)를 http://localhost:3000 으로 보여줍니다.
 - /api/directions 로 들어온 요청을 카카오모빌리티 길찾기 API로 대신 보냅니다.
   (REST API 키는 secret.env 에만 있고 브라우저로는 절대 전달되지 않습니다.)

실행:  python3 server.py
종료:  터미널에서 Ctrl + C
추가 설치 필요 없음 (파이썬 기본 라이브러리만 사용)
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PORT", 3000))  # 배포 환경은 PORT를 지정해 줌
BASE = os.path.dirname(os.path.abspath(__file__))

REALTIME_URL = "https://apis-navi.kakaomobility.com/v1/directions"
FUTURE_URL = "https://apis-navi.kakaomobility.com/v1/future/directions"


def load_key():
    key = os.environ.get("KAKAO_REST_KEY")
    if key:
        return key.strip()
    path = os.path.join(BASE, "secret.env")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("KAKAO_REST_KEY="):
                    return line.split("=", 1)[1].strip()
    return None


KEY = load_key()


def call_kakao(url, params):
    query = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        f"{url}?{query}",
        headers={"Authorization": f"KakaoAK {KEY}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as res:
        return json.loads(res.read().decode("utf-8"))


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE, **kwargs)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/directions":
            return self.handle_directions(urllib.parse.parse_qs(parsed.query))
        # secret.env 는 브라우저에서 절대 열리지 않게 차단
        if parsed.path.endswith(".env") or parsed.path.endswith(".py"):
            return self.send_json(403, {"error": "forbidden"})
        return super().do_GET()

    def send_json(self, status, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_directions(self, qs):
        if not KEY:
            return self.send_json(500, {"error": "secret.env 에 KAKAO_REST_KEY 가 없습니다."})

        origin = (qs.get("origin") or [None])[0]
        destination = (qs.get("destination") or [None])[0]
        departure = (qs.get("departure") or [None])[0]
        if not origin or not destination:
            return self.send_json(400, {"error": "origin, destination 이 필요합니다."})

        params = {"origin": origin, "destination": destination, "priority": "RECOMMEND"}
        mode = "realtime"
        try:
            if departure:
                # 선택한 요일·시각의 '예측 교통'으로 계산. 실패하면 실시간으로 대체.
                try:
                    data = call_kakao(FUTURE_URL, {**params, "departure_time": departure})
                    mode = "future"
                except urllib.error.HTTPError:
                    data = call_kakao(REALTIME_URL, params)
                    mode = "realtime-fallback"
            else:
                data = call_kakao(REALTIME_URL, params)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            return self.send_json(e.code, {"error": f"카카오모빌리티 응답 오류 ({e.code})", "detail": detail})
        except Exception as e:  # 네트워크 등
            return self.send_json(502, {"error": f"카카오모빌리티 연결 실패: {e}"})

        route = (data.get("routes") or [{}])[0]
        if route.get("result_code", -1) != 0:
            return self.send_json(200, {"error": route.get("result_msg", "경로를 찾지 못했습니다.")})

        summary = route["summary"]
        roads = []
        for section in route.get("sections", []):
            for road in section.get("roads", []):
                roads.append({
                    "state": road.get("traffic_state", 0),
                    "d": road.get("distance", 0),
                    "v": road.get("vertexes", []),
                })

        return self.send_json(200, {
            "mode": mode,
            "distance": summary.get("distance", 0),   # m
            "duration": summary.get("duration", 0),   # 초
            "roads": roads,
        })


def main():
    if not KEY:
        print("⚠️  secret.env 에 KAKAO_REST_KEY 가 없어 길찾기는 추정치로만 동작합니다.")
    try:
        server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    except OSError:
        print(f"❌ {PORT}번 포트가 이미 사용 중입니다.")
        print("   예전에 켜둔 터미널에서 Ctrl + C 로 먼저 꺼주세요.")
        print("   또는: lsof -ti:%d | xargs kill" % PORT)
        sys.exit(1)
    print(f"✅ 아웃라이어 서버 실행 중 → http://localhost:{PORT}")
    print("   종료하려면 Ctrl + C")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n서버를 종료했습니다.")


if __name__ == "__main__":
    main()
