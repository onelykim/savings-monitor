#!/usr/bin/env python3
"""국내 은행권(시중은행+인터넷전문은행) 적금 상품 모니터.

금융감독원 금융상품통합비교공시 API에서 적금 상품을 수집해
docs/data.json 을 갱신하고, 신규 상품이 있으면 텔레그램 채널로 알린다.

환경변수:
  FSS_AUTH_KEY        금감원 오픈API 인증키 (필수)
  TELEGRAM_BOT_TOKEN  텔레그램 봇 토큰 (없으면 알림 생략)
  TELEGRAM_CHAT_ID    텔레그램 채널 아이디 (예: @mychannel)
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
API_URL = "https://finlife.fss.or.kr/finlifeapi/savingProductsSearch.json"
DATA_PATH = os.path.join(os.path.dirname(__file__), "docs", "data.json")
TOP_FIN_GRP = "020000"  # 은행권 (시중은행 + 인터넷전문은행 + 지방은행)
NEW_BADGE_DAYS = 14     # 사이트에서 NEW 배지를 유지하는 기간


def http_get_json(url, retries=3, backoff=3):
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "savings-monitor/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(backoff * (attempt + 1))
    raise RuntimeError(f"GET 실패: {url} ({last_err})")


def fetch_all_products(auth_key):
    """모든 페이지를 수집해 상품 dict 목록을 돌려준다."""
    base_items, option_items = [], []
    page = 1
    while True:
        url = f"{API_URL}?auth={auth_key}&topFinGrpNo={TOP_FIN_GRP}&pageNo={page}"
        data = http_get_json(url)
        result = data.get("result", {})
        err = result.get("err_cd")
        if err != "000":
            raise ApiError(err, result.get("err_msg", ""))
        base_items.extend(result.get("baseList") or [])
        option_items.extend(result.get("optionList") or [])
        max_page = int(result.get("max_page_no") or 1)
        if page >= max_page:
            break
        page += 1

    # 옵션(기간별 금리)을 상품에 연결
    opts_by_key = {}
    for o in option_items:
        key = f"{o.get('fin_co_no')}|{o.get('fin_prdt_cd')}"
        opts_by_key.setdefault(key, []).append({
            "save_trm": int(o.get("save_trm") or 0),
            "intr_rate_type_nm": o.get("intr_rate_type_nm") or "",
            "rsrv_type_nm": o.get("rsrv_type_nm") or "",
            "intr_rate": float(o.get("intr_rate") or 0),
            "intr_rate2": float(o.get("intr_rate2") or 0),
        })

    products = []
    for b in base_items:
        key = f"{b.get('fin_co_no')}|{b.get('fin_prdt_cd')}"
        opts = sorted(opts_by_key.get(key, []), key=lambda x: (x["save_trm"], -x["intr_rate2"]))
        best = max(opts, key=lambda x: x["intr_rate2"], default=None)
        bank = (b.get("kor_co_nm") or "").strip()
        name = (b.get("fin_prdt_nm") or "").strip()
        products.append({
            "key": key,
            "bank": bank,
            "name": name,
            "dcls_month": b.get("dcls_month") or "",
            "join_way": b.get("join_way") or "",
            "join_member": b.get("join_member") or "",
            "join_deny": b.get("join_deny") or "",  # 1:제한없음 2:서민전용 3:일부제한
            "spcl_cnd": (b.get("spcl_cnd") or "").strip(),
            "mtrt_int": (b.get("mtrt_int") or "").strip(),
            "max_limit": b.get("max_limit"),
            "etc_note": (b.get("etc_note") or "").strip(),
            "options": opts,
            "best_rate": best["intr_rate2"] if best else 0,
            "best_base_rate": best["intr_rate"] if best else 0,
            "best_term": best["save_trm"] if best else 0,
            "naver_url": "https://search.naver.com/search.naver?query="
                         + urllib.parse.quote(f"{bank} {name}"),
        })
    # 중복 키 제거(안전장치)
    seen, unique = set(), []
    for p in products:
        if p["key"] not in seen:
            seen.add(p["key"])
            unique.append(p)
    return unique


class ApiError(Exception):
    def __init__(self, code, msg):
        super().__init__(f"FSS API 오류 {code}: {msg}")
        self.code = code


# ──────────────────────── 뉴스 레이더 ────────────────────────
NEWS_QUERIES = ['"적금" 출시 when:3d', '적금 특판 when:3d']
NEWS_TITLE_KEYWORDS = ("출시", "특판", "신상", "선보", "내놓", "새로")

# 기사 제목에서 은행명을 찾기 위한 별칭 사전 (별칭 → 표준명)
BANK_ALIASES = [
    ("KB국민은행", "국민은행"), ("국민은행", "국민은행"), ("국민銀", "국민은행"), ("KB", "국민은행"),
    ("신한은행", "신한은행"), ("신한銀", "신한은행"),
    ("하나은행", "하나은행"), ("하나銀", "하나은행"),
    ("우리은행", "우리은행"), ("우리銀", "우리은행"),
    ("NH농협은행", "NH농협은행"), ("농협은행", "NH농협은행"), ("농협銀", "NH농협은행"),
    ("IBK기업은행", "IBK기업은행"), ("기업은행", "IBK기업은행"),
    ("카카오뱅크", "카카오뱅크"), ("카뱅", "카카오뱅크"),
    ("케이뱅크", "케이뱅크"), ("토스뱅크", "토스뱅크"),
    ("SC제일은행", "SC제일은행"), ("씨티은행", "한국씨티은행"),
    ("iM뱅크", "iM뱅크"), ("대구은행", "iM뱅크"),
    ("부산은행", "부산은행"), ("경남은행", "경남은행"), ("광주은행", "광주은행"),
    ("전북은행", "전북은행"), ("제주은행", "제주은행"), ("수협은행", "수협은행"),
]


def norm_name(s):
    """상품명 비교용 정규화: 공백·따옴표 제거."""
    import re
    return re.sub(r"[\s'\"‘’“”「」]", "", s or "")


def extract_news_product(title):
    """기사 제목에서 (은행 표준명, 상품명, 최고금리)를 추출. 실패 항목은 None."""
    import re
    bank = None
    for alias, canonical in BANK_ALIASES:
        if alias in title:
            bank = canonical
            break
    # 금리: '연 4.5%' 우선, 없으면 12% 이하의 일반 % 값
    rate = None
    m = re.findall(r"연\s*(\d+(?:\.\d+)?)\s*%", title)
    if not m:
        m = [x for x in re.findall(r"(\d+(?:\.\d+)?)\s*%", title) if float(x) <= 12]
    if m:
        rate = max(float(x) for x in m)
    # 상품명: 따옴표 안에 '적금/예금'이 들어간 구절
    name = None
    for span in re.findall(r"['‘\"“「]([^'’\"”」]{2,30})['’\"”」]", title):
        if "적금" in span or "예금" in span:
            name = span.strip()
            break
    if not name:
        # 따옴표 없는 경우: '○○적금' 형태의 고유명사 토큰 (일반 명사는 제외)
        generic = {"적금", "예적금", "정기적금", "자유적립적금", "특판적금", "전용적금", "신상적금"}
        for tok in re.findall(r"([가-힣A-Za-z0-9]{2,15}적금)", title.replace("·", "")):
            if tok not in generic and not tok.endswith(("의적금", "인적금", "는적금")):
                name = tok
                break
    return bank, name, rate


def cluster_news_products(prev_clusters, articles, fresh_links, products):
    """기사들을 상품 단위로 묶는다. 반환: (클러스터 목록, 새로 생긴 클러스터들)"""
    clusters = [dict(c) for c in (prev_clusters or [])]
    new_clusters = []
    prod_norms = [(norm_name(p["bank"] + p["name"]), norm_name(p["name"])) for p in products]

    for a in articles:
        bank, name, rate = extract_news_product(a["title"])
        if not bank:
            continue
        nn = norm_name(name) if name else None
        target = None
        for c in clusters:
            if c["bank"] != bank:
                continue
            if nn and (nn in c["norm"] or c["norm"] in nn):
                target = c
                break
            if not nn and rate and c.get("rate") == rate:
                target = c  # 상품명 없는 기사는 은행+금리로 기존 클러스터에 붙임
                break
        if target is None:
            if not nn:
                continue  # 은행만 있고 상품명·매칭 단서가 없으면 클러스터 안 만듦
            target = {"bank": bank, "name": name, "norm": nn, "rate": rate,
                      "first_news": a["date"] or "", "count": 0, "articles": [],
                      "in_disclosure": False}
            clusters.append(target)
            if a["link"] in fresh_links:
                new_clusters.append(target)
        target["count"] += 1
        if rate and (not target.get("rate") or rate > target["rate"]):
            target["rate"] = rate
        if a["date"] and (not target["first_news"] or a["date"] < target["first_news"]):
            target["first_news"] = a["date"]
        if len(target["articles"]) < 4 and a["link"] not in [x["link"] for x in target["articles"]]:
            target["articles"].append({"title": a["title"], "link": a["link"],
                                       "source": a["source"], "date": a["date"]})

    # 공시 목록에 이미 반영됐는지 매칭 (이름 포함 관계)
    for c in clusters:
        c["in_disclosure"] = any(
            c["norm"] in pn or pn in c["norm"] or c["norm"] in bn
            for bn, pn in prod_norms if pn
        )
    # 오래된 클러스터 정리 (기사 30일 지난 것, 최대 20개)
    clusters.sort(key=lambda c: c.get("first_news") or "", reverse=True)
    return clusters[:20], new_clusters


def fetch_news_naver():
    """네이버 뉴스 검색 API (키가 설정된 경우에만). 국내 매체 커버리지 보강."""
    import re
    from email.utils import parsedate_to_datetime
    cid = os.environ.get("NAVER_CLIENT_ID", "").strip()
    sec = os.environ.get("NAVER_CLIENT_SECRET", "").strip()
    if not cid or not sec:
        return []
    items = []
    for q in ("적금 출시", "적금 특판"):
        url = ("https://openapi.naver.com/v1/search/news.json?query="
               + urllib.parse.quote(q) + "&display=30&sort=date")
        try:
            req = urllib.request.Request(url, headers={
                "X-Naver-Client-Id": cid, "X-Naver-Client-Secret": sec})
            with urllib.request.urlopen(req, timeout=30) as r:
                res = json.loads(r.read().decode())
        except Exception as e:  # noqa: BLE001
            print(f"네이버 뉴스 수집 실패({q}): {e}")
            continue
        for it in res.get("items", []):
            title = re.sub(r"<[^>]+>", "", it.get("title", ""))
            title = (title.replace("&quot;", '"').replace("&amp;", "&")
                     .replace("&lt;", "<").replace("&gt;", ">").replace("&apos;", "'").strip())
            link = (it.get("originallink") or it.get("link") or "").strip()
            if not title or not link or "적금" not in title:
                continue
            if not any(k in title for k in NEWS_TITLE_KEYWORDS):
                continue
            try:
                date = parsedate_to_datetime(it.get("pubDate")).astimezone(KST).strftime("%Y-%m-%d")
            except Exception:  # noqa: BLE001
                date = ""
            items.append({"title": title, "link": link, "source": "네이버뉴스", "date": date})
    return items


def fetch_news():
    """구글 뉴스 RSS(+네이버 API)에서 적금 신상품·특판 기사를 수집한다."""
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime

    items, seen_links = [], set()
    for q in NEWS_QUERIES:
        url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(q)
               + "&hl=ko&gl=KR&ceid=KR:ko")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (rss-reader)"})
            with urllib.request.urlopen(req, timeout=30) as r:
                root = ET.fromstring(r.read())
        except Exception as e:  # noqa: BLE001
            print(f"뉴스 수집 실패({q}): {e}")
            continue
        for it in root.iter("item"):
            title = (it.findtext("title") or "").strip()
            link = (it.findtext("link") or "").strip()
            source = (it.findtext("source") or "").strip()
            if not title or not link or link in seen_links:
                continue
            if "적금" not in title:
                continue
            if not any(k in title for k in NEWS_TITLE_KEYWORDS):
                continue
            try:
                date = parsedate_to_datetime(it.findtext("pubDate")).astimezone(KST).strftime("%Y-%m-%d")
            except Exception:  # noqa: BLE001
                date = ""
            seen_links.add(link)
            items.append({"title": title, "link": link, "source": source, "date": date})
    # 네이버 API 결과 병합 (링크·제목 중복 제거)
    seen_titles = {norm_name(i["title"]) for i in items}
    for n in fetch_news_naver():
        if n["link"] in seen_links or norm_name(n["title"]) in seen_titles:
            continue
        seen_links.add(n["link"])
        seen_titles.add(norm_name(n["title"]))
        items.append(n)
    items.sort(key=lambda n: n["date"], reverse=True)
    return items


def update_news(prev, data, site_url):
    """새 기사 감지 → 텔레그램 속보 + data['news'] 갱신."""
    import hashlib
    seen = list(prev.get("news_seen") or [])
    seen_set = set(seen)
    seeded = bool(prev.get("news_seeded"))
    try:
        fetched = fetch_news()
    except Exception as e:  # noqa: BLE001
        fetched = []
        print(f"뉴스 레이더 오류(무시): {e}")

    fresh = []
    for n in fetched:
        h = hashlib.md5(n["link"].encode()).hexdigest()[:16]
        if h in seen_set:
            continue
        seen.append(h)
        seen_set.add(h)
        fresh.append(n)

    news_list = (fresh + (prev.get("news") or []))[:12]
    data["news"] = news_list
    data["news_seen"] = seen[-800:]
    data["news_seeded"] = True

    # ── 상품 단위 클러스터링 ──
    products = data.get("products") or []
    cluster_migrating = "news_products" not in prev
    fresh_links = set() if cluster_migrating else {n["link"] for n in fresh}
    cluster_input = (fresh + (prev.get("news") or [])) if cluster_migrating else fresh
    clusters, new_clusters = cluster_news_products(
        prev.get("news_products"), cluster_input, fresh_links, products)
    data["news_products"] = clusters
    if cluster_migrating and clusters:
        print(f"뉴스 상품 클러스터 초기화: {len(clusters)}개 (알림 생략)")

    if not fetched and not prev.get("news"):
        print("뉴스 레이더: 수집 결과 없음 (RSS 접근 실패 시 로그 확인)")

    if seeded and new_clusters:
        # 새로 감지된 '상품' 단위 알림 (같은 상품 기사 여러 건 = 알림 1건)
        for c in new_clusters[:3]:
            rate_txt = f"\n📈 기사 기준 최고 <b>연 {c['rate']:.2f}%</b>" if c.get("rate") else ""
            links = "\n".join(
                f"• <a href=\"{a['link']}\">{esc(a['title'][:70])}</a>" for a in c["articles"][:3])
            dis = "\n✅ 금감원 공시에도 등록된 상품이에요." if c["in_disclosure"] else \
                  "\n⏳ 아직 금감원 공시 반영 전 — 정확한 조건은 기사·은행 앱에서 확인!"
            send_telegram(
                f"📰🆕 <b>뉴스에서 신상품 감지!</b> 🐶\n"
                f"🏦 <b>{esc(c['bank'])} — {esc(c['name'])}</b>{rate_txt}\n"
                f"🗞️ 관련 기사 {c['count']}건 (첫 보도 {c['first_news'] or '오늘'})\n"
                f"{links}{dis}\n🌐 {site_url}"
            )
        print(f"뉴스 신상품 알림 {len(new_clusters[:3])}건 발송")

    # 클러스터에 못 묶인 새 기사(은행명 미확인)는 간단 속보로
    clustered_links = {a["link"] for c in clusters for a in c["articles"]}
    loose = [n for n in fresh if n["link"] not in clustered_links
             and extract_news_product(n["title"])[0] is None]
    if seeded and loose and not cluster_migrating:
        lines = [f"• <a href=\"{n['link']}\">{esc(n['title'][:70])}</a>" for n in loose[:3]]
        send_telegram("📰 <b>적금 뉴스 레이더</b> 🐶\n" + "\n".join(lines)
                      + f"\n\n🌐 {site_url}")
        print(f"기타 뉴스 속보 {len(loose[:3])}건 발송")
    elif fresh and not seeded:
        print(f"뉴스 기준선 저장 {len(fresh)}건 (첫 수집, 알림 생략)")


def load_prev():
    try:
        with open(DATA_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {"products": [], "baseline": False}


def send_telegram(text):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("텔레그램 설정 없음 → 알림 생략")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode()
    try:
        req = urllib.request.Request(url, data=payload)
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read().decode())
            if not resp.get("ok"):
                print(f"텔레그램 응답 오류: {resp}")
    except Exception as e:  # noqa: BLE001
        print(f"텔레그램 발송 실패: {e}")


def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def rank_of(rate, products):
    rates = sorted((p["best_rate"] for p in products), reverse=True)
    for i, r in enumerate(rates, 1):
        if rate >= r:
            return i
    return len(rates)


def build_analysis(p, products):
    n = len(products)
    rank = rank_of(p["best_rate"], products)
    pct = max(1, round(rank / n * 100))
    lines = [f"은행권 {n}개 적금 중 최고우대금리 {rank}위 (상위 {pct}%)."]
    if p["spcl_cnd"] and p["spcl_cnd"] not in ("없음", "-"):
        gap = p["best_rate"] - p["best_base_rate"]
        difficulty = "우대폭이 커서 조건 확인이 중요" if gap >= 1.0 else "우대폭이 작아 기본금리 위주로 판단 가능"
        lines.append(f"기본 {p['best_base_rate']:.2f}% + 우대 {gap:.2f}%p → {difficulty}.")
    if p["join_member"] and "제한없" not in p["join_member"].replace(" ", ""):
        lines.append(f"가입대상 제한: {p['join_member']}")
    return " ".join(lines)


def telegram_message_for_new(new_products, products, site_url):
    top5 = sorted(products, key=lambda x: -x["best_rate"])[:5]
    parts = [f"🆕 <b>신규 적금 {len(new_products)}건 등록!</b>"]
    for p in new_products[:10]:
        dm = p.get("dcls_month") or ""
        dm_txt = f" · {dm[:4]}년 {int(dm[4:6])}월 공시분" if len(dm) == 6 else ""
        parts.append(
            f"\n🏦 <b>{esc(p['bank'])} — {esc(p['name'])}</b>{dm_txt}\n"
            f"📈 최고 연 <b>{p['best_rate']:.2f}%</b>"
            f" ({p['best_term']}개월, 기본 {p['best_base_rate']:.2f}%)\n"
            f"🎯 우대: {esc(p['spcl_cnd'][:90]) or '없음'}\n"
            f"👥 대상: {esc(p['join_member'][:40])} · 가입: {esc(p['join_way'][:30])}\n"
            f"💡 {esc(build_analysis(p, products))}\n"
            f"🔗 <a href=\"{p['naver_url']}\">네이버 검색</a>"
        )
    parts.append("\n📊 <b>현재 은행권 최고금리 TOP5</b>")
    for i, t in enumerate(top5, 1):
        parts.append(f"{i}. {esc(t['bank'])} {esc(t['name'])} — {t['best_rate']:.2f}% ({t['best_term']}개월)")
    parts.append(f"\n🌐 전체 비교표: {site_url}")
    return "\n".join(parts)


def main():
    auth_key = os.environ.get("FSS_AUTH_KEY", "").strip()
    site_url = os.environ.get("SITE_URL", "").strip() or "(사이트 URL 미설정)"
    if not auth_key:
        print("FSS_AUTH_KEY 가 없습니다.")
        sys.exit(1)

    now = datetime.now(KST)
    products = None
    try:
        products = fetch_all_products(auth_key)
    except ApiError as e:
        if e.code == "010":
            print("인증키가 아직 승인되지 않았습니다(미등록 인증키). 다음 실행에서 재시도합니다.")
        else:
            print(f"금감원 API 오류: {e} — 일시적일 수 있으니 다음 실행에서 재시도합니다.")
    except Exception as e:  # noqa: BLE001
        # 심야 점검·순간 장애 등 일시적 문제: 실패로 표시하지 않고 다음 시간에 재시도
        print(f"수집 실패(일시적 장애 가능): {e} — 다음 실행에서 재시도합니다.")

    if products is None:
        # 금감원 API가 죽어 있어도 뉴스 레이더는 독립적으로 계속 돈다
        prev = load_prev()
        if not prev.get("products"):
            sys.exit(0)  # 아직 기준선도 없으면 할 일 없음
        data = dict(prev)  # 상품 데이터는 마지막 성공본 유지 (updated_at 포함)
        update_news(prev, data, os.environ.get("SITE_URL", "").strip() or "")
        os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
        with open(DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        print("상품 수집은 건너뛰고 뉴스만 갱신했습니다.")
        sys.exit(0)

    prev = load_prev()
    prev_products = {p["key"]: p for p in prev.get("products", [])}
    baseline_done = bool(prev.get("baseline"))
    # 기준선 날짜: 첫 수집일. 이 날짜에 확인된 상품은 '신규'로 취급하지 않는다.
    baseline_date = prev.get("baseline_date")
    if baseline_done and not baseline_date:
        # 구버전 데이터 마이그레이션: 가장 이른 first_seen을 기준선으로 간주
        seen_dates = [p.get("first_seen") for p in prev_products.values() if p.get("first_seen")]
        baseline_date = min(seen_dates) if seen_dates else now.strftime("%Y-%m-%d")
    if not baseline_done:
        baseline_date = now.strftime("%Y-%m-%d")

    # first_seen 유지/부여 + 기준선 소속 여부
    new_products = []
    for p in products:
        old = prev_products.get(p["key"])
        if old:
            p["first_seen"] = old.get("first_seen") or now.strftime("%Y-%m-%d")
            # 기준선 플래그 유지 (구버전 데이터는 first_seen==기준선일이면 기준선 상품으로 간주)
            p["is_baseline"] = bool(old.get("is_baseline",
                                            old.get("first_seen") == baseline_date))
        else:
            p["first_seen"] = now.strftime("%Y-%m-%d")
            p["is_baseline"] = not baseline_done  # 첫 수집 때 있던 상품만 True
            if baseline_done:
                new_products.append(p)

    for p in new_products:
        p["analysis"] = build_analysis(p, products)

    data = {
        "updated_at": now.strftime("%Y-%m-%d %H:%M"),
        "baseline": True,
        "baseline_date": baseline_date,
        "new_badge_days": NEW_BADGE_DAYS,
        "products": products,
    }
    update_news(prev, data, site_url)
    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)

    if not baseline_done:
        print(f"기준선 저장 완료: 상품 {len(products)}개")
        send_telegram(
            f"✅ <b>적금 모니터 가동 시작</b>\n"
            f"현재 은행권 적금 <b>{len(products)}개</b>를 기준선으로 저장했습니다.\n"
            f"이제 새 상품이 등록되면 바로 알려드릴게요!\n🌐 {site_url}"
        )
    elif new_products:
        names = ", ".join(f"{p['bank']} {p['name']}" for p in new_products)
        print(f"신규 {len(new_products)}건: {names}")
        send_telegram(telegram_message_for_new(new_products, products, site_url))
    else:
        print(f"변동 없음 (상품 {len(products)}개 확인)")

    removed = [k for k in prev_products if k not in {p['key'] for p in products}]
    if removed:
        print(f"판매종료로 목록에서 제외: {len(removed)}건")


if __name__ == "__main__":
    main()
