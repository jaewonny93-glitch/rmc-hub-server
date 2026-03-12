#!/usr/bin/env python3
"""
RMC Hub 통합 서버
- 포트 5060: Flutter 웹앱 정적 파일 + REST API 동시 서빙
- /api/* 경로 → REST API
- 그 외 → Flutter build/web 정적 파일
- CORS + iframe 허용 헤더 포함
"""
import cgi
import io
import json
import mimetypes
import os
import textwrap
import threading
import time
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from PIL import Image, ImageDraw, ImageFont

# Railway 환경: 현재 디렉토리 기준 상대 경로 사용
_BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR  = os.path.join(_BASE, "data")
FORMS_DIR = os.path.join(_BASE, "forms")
WEB_DIR   = os.path.join(_BASE, "web")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(FORMS_DIR, exist_ok=True)

# 서식 메타데이터 파일
FORMS_META_FILE = os.path.join(DATA_DIR, "forms.json")
if not os.path.exists(FORMS_META_FILE):
    with open(FORMS_META_FILE, "w") as f:
        json.dump([], f)

LOCK = threading.Lock()

# ── 폰트 경로 (Railway: 프로젝트 내 fonts/ 폴더 우선, 없으면 시스템 폰트)
_FONT_DIR_LOCAL  = os.path.join(_BASE, "fonts")
_FONT_DIR_SYSTEM = "/usr/share/fonts/truetype/nanum"
_FONT_DIR = _FONT_DIR_LOCAL if os.path.exists(_FONT_DIR_LOCAL) else _FONT_DIR_SYSTEM
_F_REGULAR = os.path.join(_FONT_DIR, "NanumGothic.ttf")
_F_BOLD    = os.path.join(_FONT_DIR, "NanumGothicBold.ttf")
_F_EXTRABOLD = os.path.join(_FONT_DIR, "NanumGothicExtraBold.ttf")

def _font(bold=False, size=18):
    try:
        path = _F_EXTRABOLD if (bold and size >= 24) else (_F_BOLD if bold else _F_REGULAR)
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def _num(n):
    """숫자를 천 단위 콤마 포맷 (예: 1,200,000)"""
    return f"{int(n):,}"


def generate_quote_image(order: dict) -> bytes:
    """
    PurchaseOrderModel dict → 견적서 PNG bytes 반환
    """
    # ── 기본 정보 ──
    order_id   = order.get("id", "")
    emp_id     = order.get("employeeId", "")
    affil      = order.get("affiliation", "")
    items      = order.get("items", [])
    total      = int(order.get("totalPrice", 0))
    ordered_at = order.get("orderedAt", "")
    try:
        dt = datetime.fromisoformat(ordered_at.replace("Z", "+00:00"))
        date_str = dt.strftime("%Y년 %m월 %d일")
    except Exception:
        date_str = ordered_at[:10] if ordered_at else datetime.now().strftime("%Y년 %m월 %d일")

    short_id = order_id[-6:] if len(order_id) >= 6 else order_id

    # ── 캔버스 크기 계산 ──
    W = 900
    ROW_H = 44          # 품목 행 높이
    HEADER_H = 420      # 헤더 영역 높이 (로고+제목+기본정보)
    TABLE_TOP = HEADER_H
    TABLE_HEAD_H = 48
    FOOTER_H = 160
    H = HEADER_H + TABLE_HEAD_H + ROW_H * len(items) + 10 + FOOTER_H
    H = max(H, 750)

    img = Image.new("RGB", (W, H), "#ffffff")
    draw = ImageDraw.Draw(img)

    # ── 색상 팔레트 ──
    C_PRIMARY   = "#1b4f8a"   # 헤더 딥블루
    C_ACCENT    = "#2e7dd1"   # 포인트 블루
    C_HEADER_BG = "#1b4f8a"
    C_ROW_EVEN  = "#f4f7fb"
    C_ROW_ODD   = "#ffffff"
    C_TABLE_HDR = "#2e7dd1"
    C_BORDER    = "#c8d6e8"
    C_TEXT      = "#1a1a2e"
    C_SUBTEXT   = "#5a6a7e"
    C_GOLD      = "#c9933a"
    C_WHITE     = "#ffffff"
    C_GREEN     = "#1a7a4a"
    C_TOTAL_BG  = "#e8f0fa"

    # ════════════════════════════════════════
    # ① 헤더 배경 (딥블루 그라데이션 효과)
    # ════════════════════════════════════════
    draw.rectangle([0, 0, W, 180], fill=C_HEADER_BG)
    # 서브 스트라이프
    for i in range(4):
        draw.rectangle([0, 180 - i*2, W, 181 - i*2],
                       fill="#1e5694" if i % 2 == 0 else C_HEADER_BG)

    # 왼쪽 세로 장식 바
    draw.rectangle([0, 0, 8, 180], fill=C_GOLD)

    # 병원 이름 (흰색)
    draw.text((28, 22), "분당서울대학교병원", font=_font(bold=True, size=30), fill=C_WHITE)
    draw.text((28, 62), "재생의학센터", font=_font(bold=True, size=22), fill="#a8c8f0")
    draw.text((28, 96), "Bundang Seoul National University Hospital", font=_font(size=14), fill="#7aaad0")
    draw.text((28, 116), "Regenerative Medicine Center", font=_font(size=14), fill="#7aaad0")

    # QUOTATION 레이블 (우측)
    draw.text((W - 220, 22), "견  적  서", font=_font(bold=True, size=34), fill=C_GOLD)
    draw.text((W - 210, 68), "QUOTATION", font=_font(size=16), fill="#a8c8f0")

    # ════════════════════════════════════════
    # ② 구분선 + 문서번호 영역
    # ════════════════════════════════════════
    draw.rectangle([0, 180, W, 196], fill=C_GOLD)
    draw.rectangle([0, 196, W, 220], fill="#f0f4fa")
    draw.text((28, 200), f"문서번호  RMC-Q-{short_id}",
              font=_font(size=14), fill=C_SUBTEXT)
    draw.text((W - 280, 200), f"발행일  {date_str}",
              font=_font(size=14), fill=C_SUBTEXT)

    # ════════════════════════════════════════
    # ③ 공급자 / 공급받는자 2단 박스
    # ════════════════════════════════════════
    BOX_TOP = 228
    BOX_H   = 170
    BOX_MID = W // 2

    def _info_box(x1, y1, x2, y2, title, title_color, rows):
        draw.rectangle([x1, y1, x2, y2], fill="#f8fafd", outline=C_BORDER, width=1)
        draw.rectangle([x1, y1, x2, y1 + 34], fill=title_color)
        draw.text((x1 + 14, y1 + 7), title, font=_font(bold=True, size=16), fill=C_WHITE)
        cy = y1 + 44
        for label, value in rows:
            draw.text((x1 + 14, cy), label, font=_font(size=13), fill=C_SUBTEXT)
            draw.text((x1 + 90, cy), value, font=_font(bold=True, size=13), fill=C_TEXT)
            cy += 26

    # 공급자 (판매자)
    _info_box(
        18, BOX_TOP, BOX_MID - 10, BOX_TOP + BOX_H,
        "공  급  자 (판매자)", C_PRIMARY,
        [
            ("상 호", "분당서울대학교병원 재생의학센터"),
            ("주 소", "경기도 성남시 분당구 구미로 173번길 82"),
            ("전 화", "031-787-7073"),
            ("이메일", "rmc01@snubh.org"),
        ]
    )

    # 공급받는자 (주문자)
    _info_box(
        BOX_MID + 10, BOX_TOP, W - 18, BOX_TOP + BOX_H,
        "공급받는자 (주문자)", C_ACCENT,
        [
            ("소 속", affil if affil else "-"),
            ("사 번", emp_id if emp_id else "-"),
            ("주문번호", f"#{short_id}"),
            ("주문일자", date_str),
        ]
    )

    # ════════════════════════════════════════
    # ④ 품목 테이블
    # ════════════════════════════════════════
    TABLE_Y = BOX_TOP + BOX_H + 16
    COL_X = [18, 340, 440, 560, 680, W - 18]  # 품명|단위|단가|수량|공급가
    COL_LABELS = ["품       명", "단위", "단가 (원)", "수량", "공급가액 (원)"]
    COL_ALIGN  = ["left", "center", "right", "center", "right"]

    # 테이블 헤더
    draw.rectangle([18, TABLE_Y, W - 18, TABLE_Y + TABLE_HEAD_H], fill=C_TABLE_HDR)
    for i, label in enumerate(COL_LABELS):
        cx = (COL_X[i] + COL_X[i + 1]) // 2
        draw.text((cx, TABLE_Y + 12), label,
                  font=_font(bold=True, size=14), fill=C_WHITE, anchor="mt")
    # 세로 구분선 (헤더)
    for x in COL_X[1:-1]:
        draw.line([x, TABLE_Y, x, TABLE_Y + TABLE_HEAD_H], fill="#5a9fd4", width=1)

    # 품목 행
    ry = TABLE_Y + TABLE_HEAD_H
    subtotal_check = 0
    for idx, item in enumerate(items):
        row_bg = C_ROW_EVEN if idx % 2 == 0 else C_ROW_ODD
        draw.rectangle([18, ry, W - 18, ry + ROW_H], fill=row_bg)

        name  = str(item.get("name", ""))
        unit  = str(item.get("unit", ""))
        price = int(item.get("price", 0))
        qty   = int(item.get("qty", 0))
        subtotal = price * qty
        subtotal_check += subtotal

        cells = [name, unit, _num(price), str(qty), _num(subtotal)]
        for i, val in enumerate(cells):
            cx = (COL_X[i] + COL_X[i + 1]) // 2
            anchor = "mt" if COL_ALIGN[i] == "center" else ("rt" if COL_ALIGN[i] == "right" else "lt")
            tx = cx if anchor == "mt" else (COL_X[i + 1] - 12 if anchor == "rt" else COL_X[i] + 12)
            draw.text((tx, ry + 10), val,
                      font=_font(bold=(i == 4), size=13), fill=C_TEXT, anchor=anchor)

        # 행 하단 구분선
        draw.line([18, ry + ROW_H, W - 18, ry + ROW_H], fill=C_BORDER, width=1)
        # 세로 구분선
        for x in COL_X[1:-1]:
            draw.line([x, ry, x, ry + ROW_H], fill=C_BORDER, width=1)
        ry += ROW_H

    # 테이블 외곽선
    table_bottom = ry
    draw.rectangle([18, TABLE_Y, W - 18, table_bottom], outline=C_ACCENT, width=2)

    # ════════════════════════════════════════
    # ⑤ 합계 박스
    # ════════════════════════════════════════
    SUM_Y = table_bottom + 12
    draw.rectangle([18, SUM_Y, W - 18, SUM_Y + 54], fill=C_TOTAL_BG, outline=C_ACCENT, width=2)
    draw.rectangle([18, SUM_Y, 200, SUM_Y + 54], fill=C_PRIMARY)
    draw.text((108, SUM_Y + 14), "합계금액", font=_font(bold=True, size=16), fill=C_WHITE, anchor="mt")
    total_str = f"₩ {_num(total)} 원"
    draw.text((W - 30, SUM_Y + 14), total_str,
              font=_font(bold=True, size=22), fill=C_PRIMARY, anchor="rt")

    # 부가세 안내
    vat_y = SUM_Y + 58
    draw.text((W - 30, vat_y), "※ 상기 금액은 부가세 별도 금액입니다.",
              font=_font(size=12), fill=C_SUBTEXT, anchor="rt")

    # ════════════════════════════════════════
    # ⑥ 하단 서명/직인 영역
    # ════════════════════════════════════════
    SIG_Y = vat_y + 24
    draw.line([18, SIG_Y, W - 18, SIG_Y], fill=C_BORDER, width=1)

    # 직인 박스 (오른쪽)
    seal_x, seal_y = W - 160, SIG_Y + 14
    draw.rectangle([seal_x, seal_y, seal_x + 130, seal_y + 80],
                   fill="#fff8f0", outline=C_GOLD, width=2)
    draw.ellipse([seal_x + 5, seal_y + 5, seal_x + 125, seal_y + 75],
                 outline=C_GOLD, width=2)
    draw.text((seal_x + 65, seal_y + 18), "재생의학센터",
              font=_font(bold=True, size=14), fill=C_GOLD, anchor="mt")
    draw.text((seal_x + 65, seal_y + 40), "(직  인)",
              font=_font(size=13), fill=C_GOLD, anchor="mt")
    draw.text((seal_x + 65, seal_y + 58), "OFFICIAL SEAL",
              font=_font(size=10), fill=C_GOLD, anchor="mt")

    # 문구
    draw.text((28, SIG_Y + 18),
              "위와 같이 견적서를 제출합니다.",
              font=_font(bold=True, size=15), fill=C_TEXT)
    draw.text((28, SIG_Y + 46),
              "분당서울대학교병원 재생의학센터",
              font=_font(size=13), fill=C_SUBTEXT)

    # ════════════════════════════════════════
    # ⑦ 최하단 컬러 바
    # ════════════════════════════════════════
    draw.rectangle([0, H - 18, W, H], fill=C_PRIMARY)
    draw.rectangle([0, H - 18, W // 3, H], fill=C_GOLD)
    draw.text((W // 2, H - 10),
              "Bundang Seoul National University Hospital · Regenerative Medicine Center",
              font=_font(size=11), fill=C_WHITE, anchor="mm")

    # ── PNG bytes 반환 ──
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def load(name):
    path = os.path.join(DATA_DIR, f"{name}.json")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save(name, data):
    path = os.path.join(DATA_DIR, f"{name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_forms_meta():
    if not os.path.exists(FORMS_META_FILE):
        return []
    with open(FORMS_META_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_forms_meta(data):
    with open(FORMS_META_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_DIR, **kwargs)

    def log_message(self, fmt, *args):
        pass  # 로그 억제

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("X-Frame-Options", "ALLOWALL")
        self.send_header("Content-Security-Policy", "frame-ancestors *")

    def _send_json(self, code, body):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    def _read_multipart(self):
        """multipart/form-data 파싱 → {'title','desc','filename', 'filedata': bytes}"""
        content_type = self.headers.get("Content-Type", "")
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)

        # boundary 추출
        boundary = None
        for part in content_type.split(";"):
            part = part.strip()
            if part.startswith("boundary="):
                boundary = part[9:].strip('"')
                break
        if not boundary:
            return {}

        # parts 분리
        sep = ("--" + boundary).encode()
        end = ("--" + boundary + "--").encode()
        result = {}
        for chunk in raw.split(sep):
            if not chunk or chunk.strip() == b"--" or chunk.strip() == b"" or chunk == end:
                continue
            if b"\r\n\r\n" not in chunk:
                continue
            header_part, _, body_part = chunk.partition(b"\r\n\r\n")
            # 마지막 \r\n 제거
            body_part = body_part.rstrip(b"\r\n")
            header_str = header_part.decode("utf-8", errors="ignore")
            # 필드명 추출
            name_match = None
            filename_match = None
            for line in header_str.splitlines():
                if "Content-Disposition" in line:
                    for seg in line.split(";"):
                        seg = seg.strip()
                        if seg.startswith("name="):
                            name_match = seg[5:].strip('"')
                        if seg.startswith("filename="):
                            filename_match = seg[9:].strip('"')
            if name_match == "file" and filename_match:
                result["filename"] = filename_match
                result["filedata"] = body_part
            elif name_match:
                result[name_match] = body_part.decode("utf-8", errors="ignore")
        return result

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        p = parsed.path.rstrip("/")
        qs = parse_qs(parsed.query)

        # API 라우팅
        if p.startswith("/api"):
            api_path = p[4:]  # /api 제거
            with LOCK:
                if api_path == "/sync" or api_path == "":
                    self._send_json(200, {
                        "reservations": load("reservations"),
                        "purchaseOrders": load("purchaseOrders"),
                        "notices": load("notices"),
                        "notifications": load("notifications"),
                        "visitorLogs": load("visitorLogs"),
                        "ts": int(time.time() * 1000),
                    })
                elif api_path == "/reservations":
                    self._send_json(200, load("reservations"))
                elif api_path == "/purchaseOrders":
                    self._send_json(200, load("purchaseOrders"))
                elif api_path == "/notices":
                    self._send_json(200, load("notices"))
                elif api_path == "/notifications":
                    emp = qs.get("employeeId", [""])[0]
                    notifs = load("notifications")
                    if emp:
                        notifs = [n for n in notifs if n.get("employeeId") == emp]
                    self._send_json(200, notifs)
                elif api_path == "/visitorLogs":
                    self._send_json(200, load("visitorLogs"))
                elif api_path == "/health":
                    self._send_json(200, {"ok": True, "ts": int(time.time() * 1000)})
                elif api_path == "/forms":
                    # 서식 목록 반환
                    self._send_json(200, load_forms_meta())
                elif api_path.startswith("/forms/") and api_path.endswith("/download"):
                    # 서식 파일 다운로드
                    parts = api_path.split("/")
                    form_id = parts[2] if len(parts) >= 3 else ""
                    forms = load_forms_meta()
                    form = next((f for f in forms if f.get("id") == form_id), None)
                    if form is None:
                        self._send_json(404, {"error": "form not found"})
                        return
                    file_path = os.path.join(FORMS_DIR, form.get("savedName", ""))
                    if not os.path.exists(file_path):
                        self._send_json(404, {"error": "file not found"})
                        return
                    with open(file_path, "rb") as fp:
                        file_bytes = fp.read()
                    mime = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
                    orig_name = form.get("filename", form.get("savedName", "form"))
                    self.send_response(200)
                    self.send_header("Content-Type", mime)
                    self.send_header("Content-Length", str(len(file_bytes)))
                    self.send_header("Content-Disposition",
                                     f'attachment; filename="{orig_name}"')
                    self._cors_headers()
                    self.end_headers()
                    self.wfile.write(file_bytes)
                    return
                elif api_path.startswith("/quote/"):
                    # ── 견적서 PNG 생성 ──
                    order_id = api_path[len("/quote/"):]
                    orders = load("purchaseOrders")
                    order = next((o for o in orders if o.get("id") == order_id), None)
                    if order is None:
                        self._send_json(404, {"error": "order not found"})
                    else:
                        try:
                            png_bytes = generate_quote_image(order)
                            short_id = order_id[-6:] if len(order_id) >= 6 else order_id
                            filename = f"RMC_Quotation_{short_id}.png"
                            self.send_response(200)
                            self.send_header("Content-Type", "image/png")
                            self.send_header("Content-Length", str(len(png_bytes)))
                            self.send_header("Content-Disposition",
                                             f'attachment; filename="{filename}"')
                            self._cors_headers()
                            self.end_headers()
                            self.wfile.write(png_bytes)
                        except Exception as e:
                            self._send_json(500, {"error": str(e)})
                    return
                else:
                    self._send_json(404, {"error": "not found"})
            return

        # 정적 파일 서빙 (Flutter 웹앱)
        # SPA 라우팅: 파일이 없으면 index.html 반환
        file_path = os.path.join(WEB_DIR, p.lstrip("/"))
        if p and not os.path.exists(file_path) and not p.startswith("/api"):
            self.path = "/index.html"
        
        # CORS 헤더 추가하면서 파일 서빙
        super().do_GET()

    def end_headers(self):
        # 정적 파일에도 CORS/iframe 헤더 추가
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Frame-Options", "ALLOWALL")
        self.send_header("Content-Security-Policy", "frame-ancestors *")
        super().end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        p = parsed.path.rstrip("/")
        if not p.startswith("/api"):
            self._send_json(404, {"error": "not found"})
            return
        api_path = p[4:]

        # ── 서식 파일 업로드 (multipart) ──
        if api_path == "/forms/upload":
            content_type = self.headers.get("Content-Type", "")
            if "multipart/form-data" not in content_type:
                self._send_json(400, {"error": "multipart required"})
                return
            parts = self._read_multipart()
            filename = parts.get("filename", "")
            filedata = parts.get("filedata", b"")
            title    = parts.get("title", filename)
            desc     = parts.get("desc", "")
            if not filename or not filedata:
                self._send_json(400, {"error": "no file"})
                return
            with LOCK:
                forms = load_forms_meta()
                form_id = f"form_{int(time.time()*1000)}"
                saved_name = f"{form_id}_{filename}"
                with open(os.path.join(FORMS_DIR, saved_name), "wb") as fp:
                    fp.write(filedata)
                meta = {
                    "id": form_id,
                    "title": title,
                    "desc": desc,
                    "filename": filename,
                    "savedName": saved_name,
                    "size": len(filedata),
                    "uploadedAt": datetime.now().isoformat(),
                }
                forms.append(meta)
                save_forms_meta(forms)
            self._send_json(201, meta)
            return

        body = self._body()
        with LOCK:
            if api_path == "/reservations":
                items = load("reservations")
                dup = any(
                    r["benchId"] == body.get("benchId") and
                    r["date"] == body.get("date") and
                    r["timeSlot"] == body.get("timeSlot")
                    for r in items
                )
                if dup:
                    self._send_json(409, {"error": "duplicate"})
                    return
                items.append(body)
                save("reservations", items)
                self._send_json(201, body)

            elif api_path == "/purchaseOrders":
                items = load("purchaseOrders")
                items.insert(0, body)
                save("purchaseOrders", items)
                self._send_json(201, body)

            elif api_path == "/notices":
                items = load("notices")
                # 중복 ID 체크
                if not any(n.get("id") == body.get("id") for n in items):
                    items.insert(0, body)
                    save("notices", items)
                self._send_json(201, body)

            elif api_path == "/notifications":
                items = load("notifications")
                items.insert(0, body)
                if len(items) > 1000:
                    items = items[:1000]
                save("notifications", items)
                self._send_json(201, body)

            elif api_path == "/visitorLogs":
                items = load("visitorLogs")
                items.insert(0, body)
                if len(items) > 1000:
                    items = items[:1000]
                save("visitorLogs", items)
                self._send_json(201, body)

            else:
                self._send_json(404, {"error": "not found"})

    def do_PUT(self):
        parsed = urlparse(self.path)
        p = parsed.path.rstrip("/")
        if not p.startswith("/api"):
            self._send_json(404, {"error": "not found"})
            return
        api_path = p[4:]
        body = self._body()
        parts = api_path.split("/")  # ['', 'resource', 'id', ...]

        with LOCK:
            if len(parts) == 3 and parts[1] == "purchaseOrders":
                oid = parts[2]
                items = load("purchaseOrders")
                updated_item = None
                for i, item in enumerate(items):
                    if item.get("id") == oid:
                        items[i].update(body)
                        updated_item = items[i]
                        break
                if updated_item:
                    save("purchaseOrders", items)
                    self._send_json(200, updated_item)
                else:
                    self._send_json(404, {"error": "not found"})

            elif len(parts) == 4 and parts[1] == "notifications" and parts[3] == "read":
                nid = parts[2]
                items = load("notifications")
                for item in items:
                    if item.get("id") == nid:
                        item["isRead"] = True
                save("notifications", items)
                self._send_json(200, {"ok": True})

            elif len(parts) == 3 and parts[1] == "notifications" and parts[2] == "readAll":
                emp = body.get("employeeId", "")
                items = load("notifications")
                for item in items:
                    if item.get("employeeId") == emp:
                        item["isRead"] = True
                save("notifications", items)
                self._send_json(200, {"ok": True})

            elif len(parts) == 3 and parts[1] == "notices":
                nid = parts[2]
                items = load("notices")
                for i, item in enumerate(items):
                    if item.get("id") == nid:
                        items[i].update(body)
                        save("notices", items)
                        self._send_json(200, items[i])
                        return
                self._send_json(404, {"error": "not found"})

            else:
                self._send_json(404, {"error": "not found"})

    def do_DELETE(self):
        parsed = urlparse(self.path)
        p = parsed.path.rstrip("/")
        if not p.startswith("/api"):
            self._send_json(404, {"error": "not found"})
            return
        api_path = p[4:]
        parts = api_path.split("/")

        with LOCK:
            if len(parts) == 3 and parts[1] == "reservations":
                rid = parts[2]
                items = load("reservations")
                items = [r for r in items if r.get("id") != rid]
                save("reservations", items)
                self._send_json(200, {"ok": True})

            elif len(parts) == 3 and parts[1] == "notices":
                nid = parts[2]
                items = load("notices")
                items = [n for n in items if n.get("id") != nid]
                save("notices", items)
                self._send_json(200, {"ok": True})

            elif len(parts) == 3 and parts[1] == "forms":
                fid = parts[2]
                with LOCK:
                    forms = load_forms_meta()
                    form = next((f for f in forms if f.get("id") == fid), None)
                    if form:
                        file_path = os.path.join(FORMS_DIR, form.get("savedName", ""))
                        if os.path.exists(file_path):
                            os.remove(file_path)
                        forms = [f for f in forms if f.get("id") != fid]
                        save_forms_meta(forms)
                        self._send_json(200, {"ok": True})
                    else:
                        self._send_json(404, {"error": "not found"})

            else:
                self._send_json(404, {"error": "not found"})


if __name__ == "__main__":
    # Railway는 PORT 환경변수로 포트를 지정함
    port = int(os.environ.get("PORT", 8080))
    print(f"RMC Hub Server running on port {port}")
    print(f"  Web app: http://0.0.0.0:{port}/")
    print(f"  API:     http://0.0.0.0:{port}/api/")
    print(f"  Data:    {DATA_DIR}")
    srv = HTTPServer(("0.0.0.0", port), Handler)
    srv.serve_forever()
