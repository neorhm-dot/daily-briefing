#!/usr/bin/env python3
"""
포트폴리오 일일 브리핑 - GitHub Actions 자동화 스크립트
매일 오전 7:30 KST 실행
"""

import os
import json
import time
import requests
import smtplib
import urllib.parse
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import xml.etree.ElementTree as ET

# ──────────────────────────────────────────────
# 환경변수
# ──────────────────────────────────────────────
KAKAO_ACCESS_TOKEN   = os.environ["KAKAO_ACCESS_TOKEN"]
KAKAO_REFRESH_TOKEN  = os.environ["KAKAO_REFRESH_TOKEN"]
KAKAO_CLIENT_ID      = os.environ["KAKAO_CLIENT_ID"]
KAKAO_CLIENT_SECRET  = os.environ["KAKAO_CLIENT_SECRET"]

GMAIL_USER           = os.environ["GMAIL_USER"]          # neorhm@gmail.com
GMAIL_APP_PASSWORD   = os.environ["GMAIL_APP_PASSWORD"]  # Gmail 앱 비밀번호
RECIPIENT_EMAIL      = os.environ.get("RECIPIENT_EMAIL", "hm.ryu@hlcompany.com")

NAVER_CLIENT_ID      = os.environ["NAVER_CLIENT_ID"]
NAVER_CLIENT_SECRET  = os.environ["NAVER_CLIENT_SECRET"]

KST = timezone(timedelta(hours=9))
TODAY = datetime.now(KST).strftime("%Y-%m-%d")
TODAY_KR = datetime.now(KST).strftime("%Y년 %m월 %d일")

# ──────────────────────────────────────────────
# 카카오 토큰 갱신
# ──────────────────────────────────────────────
def refresh_kakao_token():
    """refresh_token으로 새 access_token 발급"""
    resp = requests.post("https://kauth.kakao.com/oauth/token", data={
        "grant_type": "refresh_token",
        "client_id": KAKAO_CLIENT_ID,
        "client_secret": KAKAO_CLIENT_SECRET,
        "refresh_token": KAKAO_REFRESH_TOKEN,
    })
    data = resp.json()
    if "access_token" in data:
        return data["access_token"]
    raise Exception(f"토큰 갱신 실패: {data}")

# ──────────────────────────────────────────────
# 카카오톡 전송
# ──────────────────────────────────────────────
def send_kakao(text: str, token: str):
    resp = requests.post(
        "https://kapi.kakao.com/v2/api/talk/memo/default/send",
        headers={"Authorization": f"Bearer {token}"},
        data={
            "template_object": json.dumps({
                "object_type": "text",
                "text": text[:200],
                "link": {"web_url": "https://finance.yahoo.com"}
            })
        }
    )
    return resp.json()

# ──────────────────────────────────────────────
# 주식 가격 조회 (Yahoo Finance API)
# ──────────────────────────────────────────────
PORTFOLIO = {
    "삼성전자":  {"ticker": "005930.KS", "type": "KR"},
    "제닉스":    {"ticker": "257720.KQ", "type": "KR"},
    "한양이엔지": {"ticker": "042700.KS", "type": "KR"},
    "케이에스피": {"ticker": "451340.KQ", "type": "KR"},
    "Redwire":   {"ticker": "RDW",        "type": "US"},
    "Microsoft": {"ticker": "MSFT",       "type": "US"},
}

def get_stock_price(ticker: str) -> dict:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()
        meta = data["chart"]["result"][0]["meta"]
        price = meta.get("regularMarketPrice", 0)
        prev  = meta.get("previousClose", price)
        chg   = price - prev
        chg_pct = (chg / prev * 100) if prev else 0
        currency = meta.get("currency", "")
        return {
            "price": price,
            "change": chg,
            "change_pct": chg_pct,
            "currency": currency,
        }
    except Exception as e:
        return {"price": 0, "change": 0, "change_pct": 0, "currency": "", "error": str(e)}

def fetch_prices() -> list[dict]:
    results = []
    for name, info in PORTFOLIO.items():
        data = get_stock_price(info["ticker"])
        arrow = "▲" if data["change"] >= 0 else "▼"
        color = "#e74c3c" if data["change"] >= 0 else "#2980b9"
        if info["type"] == "KR":
            price_str = f"{data['price']:,.0f}원"
            chg_str   = f"{arrow} {abs(data['change']):,.0f}원 ({data['change_pct']:+.2f}%)"
        else:
            price_str = f"${data['price']:,.2f}"
            chg_str   = f"{arrow} ${abs(data['change']):.2f} ({data['change_pct']:+.2f}%)"
        results.append({
            "name": name,
            "ticker": info["ticker"],
            "type": info["type"],
            "price_str": price_str,
            "chg_str": chg_str,
            "change": data["change"],
            "color": color,
        })
        time.sleep(0.3)
    return results

# ──────────────────────────────────────────────
# 뉴스 조회 (Google News RSS)
# ──────────────────────────────────────────────
NEWS_QUERIES = {
    "삼성전자": "삼성전자 주식",
    "제닉스":   "제닉스",
    "한양이엔지": "한양이엔지",
    "케이에스피": "케이에스피 KSP",
    "Redwire":   "Redwire RDW stock",
    "Microsoft": "Microsoft MSFT stock",
}

def fetch_news(query: str, max_items: int = 3) -> list[dict]:
    encoded = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded}&hl=ko&gl=KR&ceid=KR:ko&tbs=qdr:d"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        root = ET.fromstring(r.content)
        items = []
        for item in root.findall(".//item")[:max_items]:
            title = item.findtext("title", "").split(" - ")[0].strip()
            link  = item.findtext("link", "")
            items.append({"title": title, "url": link})
        return items
    except Exception:
        return []

# ──────────────────────────────────────────────
# 카카오톡 메시지 구성
# ──────────────────────────────────────────────
def build_kakao_messages(prices: list, news_map: dict) -> list[str]:
    messages = []

    # 헤더
    messages.append(f"📊 포트폴리오 브리핑 {TODAY_KR}\n{'─'*25}")

    # 국내 주식
    kr = [p for p in prices if p["type"] == "KR"]
    if kr:
        msg = "🇰🇷 국내 주식\n"
        for p in kr:
            arrow = "▲" if p["change"] >= 0 else "▼"
            msg += f"• {p['name']}: {p['price_str']} {arrow} {p['chg_str']}\n"
        messages.append(msg.strip())

    # 해외 주식
    us = [p for p in prices if p["type"] == "US"]
    if us:
        msg = "🇺🇸 해외 주식\n"
        for p in us:
            arrow = "▲" if p["change"] >= 0 else "▼"
            msg += f"• {p['name']}: {p['price_str']} {arrow} {p['chg_str']}\n"
        messages.append(msg.strip())

    # 종목별 뉴스 (200자 제한 맞춰 분할)
    for name, articles in news_map.items():
        if not articles:
            continue
        msg = f"📰 {name} 뉴스\n"
        for a in articles:
            line = f"• {a['title']}\n"
            if len(msg) + len(line) > 195:
                messages.append(msg.strip())
                msg = f"📰 {name} 뉴스(계속)\n"
            msg += line
        messages.append(msg.strip())

    return messages

# ──────────────────────────────────────────────
# HTML 이메일 구성
# ──────────────────────────────────────────────
def build_html_email(prices: list, news_map: dict) -> str:
    rows = ""
    for p in prices:
        color = p["color"]
        rows += f"""
        <tr>
          <td style="padding:8px 12px;border-bottom:1px solid #eee;">{p['name']}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #eee;color:#333;">{p['ticker']}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #eee;font-weight:bold;">{p['price_str']}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #eee;color:{color};">{p['chg_str']}</td>
        </tr>"""

    news_html = ""
    for name, articles in news_map.items():
        if not articles:
            continue
        items = "".join(
            f'<li style="margin:6px 0;"><a href="{a["url"]}" style="color:#2E5FA3;text-decoration:none;">{a["title"]}</a></li>'
            for a in articles
        )
        news_html += f"""
        <div style="margin-bottom:20px;">
          <h3 style="color:#2E5FA3;border-left:4px solid #2E5FA3;padding-left:10px;margin:0 0 10px;">{name}</h3>
          <ul style="margin:0;padding-left:20px;">{items}</ul>
        </div>"""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="font-family:'Apple SD Gothic Neo',Arial,sans-serif;color:#333;max-width:700px;margin:0 auto;padding:20px;">
  <div style="background:linear-gradient(135deg,#1a3a5c,#2E5FA3);padding:24px;border-radius:12px;margin-bottom:24px;">
    <h1 style="color:#fff;margin:0;font-size:22px;">📊 포트폴리오 일일 브리핑</h1>
    <p style="color:#cce0ff;margin:6px 0 0;">{TODAY_KR}</p>
  </div>

  <h2 style="color:#1a3a5c;border-bottom:2px solid #2E5FA3;padding-bottom:8px;">주가 현황</h2>
  <table style="width:100%;border-collapse:collapse;margin-bottom:30px;">
    <thead>
      <tr style="background:#f0f4ff;">
        <th style="padding:10px 12px;text-align:left;color:#1a3a5c;">종목</th>
        <th style="padding:10px 12px;text-align:left;color:#1a3a5c;">티커</th>
        <th style="padding:10px 12px;text-align:left;color:#1a3a5c;">현재가</th>
        <th style="padding:10px 12px;text-align:left;color:#1a3a5c;">변동</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>

  <h2 style="color:#1a3a5c;border-bottom:2px solid #2E5FA3;padding-bottom:8px;">📰 종목별 뉴스</h2>
  {news_html}

  <div style="margin-top:30px;padding:12px;background:#f8f9fa;border-radius:8px;font-size:12px;color:#888;text-align:center;">
    자동 생성된 브리핑입니다 · {TODAY_KR}
  </div>
</body>
</html>"""

# ──────────────────────────────────────────────
# Gmail SMTP 발송
# ──────────────────────────────────────────────
def send_email(subject: str, html_body: str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_USER
    msg["To"]      = RECIPIENT_EMAIL
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, RECIPIENT_EMAIL, msg.as_string())
    print(f"✅ 이메일 발송 완료 → {RECIPIENT_EMAIL}")

# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────
def main():
    print(f"=== 포트폴리오 브리핑 시작 ({TODAY}) ===")

    # 1. 토큰 갱신
    print("🔑 카카오 토큰 갱신 중...")
    try:
        token = refresh_kakao_token()
        print("✅ 토큰 갱신 완료")
    except Exception as e:
        print(f"⚠️ 토큰 갱신 실패, 기존 토큰 사용: {e}")
        token = KAKAO_ACCESS_TOKEN

    # 2. 주가 조회
    print("📈 주가 조회 중...")
    prices = fetch_prices()
    for p in prices:
        print(f"  {p['name']}: {p['price_str']} {p['chg_str']}")

    # 3. 뉴스 조회
    print("📰 뉴스 조회 중...")
    news_map = {}
    for name in PORTFOLIO:
        query = NEWS_QUERIES.get(name, name)
        articles = fetch_news(query)
        news_map[name] = articles
        print(f"  {name}: {len(articles)}건")
        time.sleep(0.5)

    # 4. 카카오톡 전송
    print("💬 카카오톡 전송 중...")
    messages = build_kakao_messages(prices, news_map)
    for i, msg in enumerate(messages):
        result = send_kakao(msg, token)
        print(f"  [{i+1}/{len(messages)}] {result}")
        time.sleep(1)

    # 5. 이메일 발송
    print("📧 이메일 발송 중...")
    html = build_html_email(prices, news_map)
    subject = f"[포트폴리오 브리핑] {TODAY_KR}"
    send_email(subject, html)

    print("=== 완료 ===")

if __name__ == "__main__":
    main()
