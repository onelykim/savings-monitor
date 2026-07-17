/**
 * 적금 레이더 — 텔레그램 명령어 봇 (Cloudflare Worker)
 *
 * 봇에게 1:1 대화로 명령어를 보내면 즉시 응답합니다:
 *   /top10        최고우대금리 TOP 10
 *   /new          최근 등록된 신규 상품
 *   /은행 국민     특정 은행 상품 목록
 *   (아무 글자)    은행·상품명 검색
 */

const BOT_TOKEN = "8894314221:AAHTPo3ASo261rWBpugX3BhX8gYMrihDHoE";
const WEBHOOK_SECRET = "jeokgeum-radar-2026";
const DATA_URL = "https://onelykim.github.io/savings-monitor/data.json";
const SITE_URL = "https://onelykim.github.io/savings-monitor/";
const CHANNEL_URL = "https://t.me/heeendoong_jeokgeum";

export default {
  async fetch(request) {
    if (request.method !== "POST") {
      return new Response("적금레이더 🛰️ 적금찾는 흰둥이 작동 중! 🐶 " + SITE_URL);
    }
    if (request.headers.get("X-Telegram-Bot-Api-Secret-Token") !== WEBHOOK_SECRET) {
      return new Response("forbidden", { status: 403 });
    }
    let update;
    try { update = await request.json(); } catch { return new Response("ok"); }
    // 1:1 대화, 그룹, (채널 소유자의) 채널 게시글 모두 처리
    const msg = update.message || update.channel_post;
    if (!msg || !msg.text || !msg.chat) return new Response("ok");

    let reply;
    try {
      reply = await handleCommand(msg.text.trim());
    } catch (e) {
      reply = "⚠️ 킁킁... 데이터를 물어오다 넘어졌어요 🐶 잠시 후 다시 시도해 주세요. (" + String(e).slice(0, 80) + ")";
    }
    try {
      if (reply) await sendMessage(msg.chat.id, reply);
    } catch (e) { /* 발송 실패는 무시 (다음 요청에 영향 없도록) */ }
    return new Response("ok");
  },
};

async function loadData() {
  const res = await fetch(DATA_URL + "?t=" + Math.floor(Date.now() / 60000), {
    cf: { cacheTtl: 60, cacheEverything: true },
  });
  if (!res.ok) throw new Error("data fetch failed");
  return res.json();
}

function esc(s) {
  return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function fmt(r) { return Number(r).toFixed(2); }

function isNew(p, days) {
  if (!p.first_seen) return false;
  return (Date.now() - new Date(p.first_seen + "T00:00:00+09:00")) / 864e5 <= (days || 14);
}

function productLine(p, i) {
  const no = i != null ? `${i}. ` : "• ";
  return `${no}<b>${esc(p.bank)}</b> ${esc(p.name)}\n` +
    `   📈 최고 <b>연 ${fmt(p.best_rate)}%</b> (${p.best_term}개월, 기본 ${fmt(p.best_base_rate)}%)`;
}

function productDetail(p, all) {
  const rank = [...all].sort((a, b) => b.best_rate - a.best_rate)
    .findIndex(x => x.key === p.key) + 1;
  const opts = (p.options || []).map(o => `${o.save_trm}개월 ${fmt(o.intr_rate)}→${fmt(o.intr_rate2)}%`).join(" · ");
  return `🏦 <b>${esc(p.bank)} — ${esc(p.name)}</b>\n` +
    `📈 최고 <b>연 ${fmt(p.best_rate)}%</b> (${p.best_term}개월) · 은행권 ${rank}위/${all.length}개\n` +
    (opts ? `📆 기간별: ${esc(opts)}\n` : "") +
    `🎯 우대: ${esc((p.spcl_cnd || "없음").slice(0, 150))}\n` +
    `👥 대상: ${esc((p.join_member || "-").slice(0, 60))} · 가입: ${esc((p.join_way || "-").slice(0, 40))}\n` +
    (p.max_limit ? `💰 한도: ${Number(p.max_limit).toLocaleString()}원\n` : "") +
    `🔗 <a href="${p.naver_url}">네이버 검색</a>`;
}

async function handleCommand(text) {
  // "/top10@봇이름" 형태 정리
  const cmd = text.split(" ")[0].replace(/@\w+$/, "").toLowerCase();
  const arg = text.split(" ").slice(1).join(" ").trim();

  if (cmd === "/start" || cmd === "/help") {
    return "🐶 <b>멍멍! 나는 적금찾는 흰둥이!</b> 🛰️\n" +
      "국내 은행권 적금을 매시간 킁킁 냄새 맡으며 좋은 상품을 물어다 줘요.\n\n" +
      "이렇게 시켜보세요:\n" +
      "/top10 — 금리 제일 높은 적금 10개 물어오기 🦴\n" +
      "/new — 따끈따끈한 신상 적금 물어오기 🆕\n" +
      "/뉴스 — 최신 적금 뉴스 물어오기 📰\n" +
      "/은행 국민 — 특정 은행 적금만 보기 🏦\n" +
      "그냥 검색어만 던져줘도 잘 물어와요! (예: <code>카카오</code>, <code>청년</code>)\n\n" +
      `📊 전체 비교표: ${SITE_URL}\n📢 신상 적금 알림 채널: ${CHANNEL_URL}\n\n` +
      "새 적금이 나오면 채널에서 제일 먼저 짖어드릴게요! 🐕💨";
  }

  const data = await loadData();
  const ps = data.products || [];
  if (!ps.length) return "⏳ 아직 데이터 수집 전이에요. 잠시 후 다시 시도해 주세요.";
  const updated = data.updated_at ? `\n\n🕐 기준: ${data.updated_at} (매시간 갱신)` : "";

  if (cmd === "/top10" || cmd === "/top") {
    const top = [...ps].sort((a, b) => b.best_rate - a.best_rate).slice(0, 10);
    const newDays = data.new_badge_days || 14;
    const avg = ps.reduce((s, p) => s + p.best_rate, 0) / ps.length;
    const lines = top.map((p, i) => productLine(p, i + 1) + (isNew(p, newDays) ? " 🆕" : ""));
    return `🏆 <b>흰둥이가 물어온 최고금리 TOP 10</b> 🦴\n\n${lines.join("\n")}\n\n` +
      `📊 전체 ${ps.length}개 상품 · 평균 최고금리 ${fmt(avg)}%\n🌐 ${SITE_URL}` + updated;
  }

  if (cmd === "/new" || cmd === "/신규") {
    const days = data.new_badge_days || 14;
    const news = ps.filter(p => isNew(p, days))
      .sort((a, b) => (b.first_seen || "").localeCompare(a.first_seen || "") || b.best_rate - a.best_rate);
    if (!news.length) return `킁킁... 최근 ${days}일 내 신상 적금은 아직 없어요 🐶\n새 상품이 나오면 채널에서 제일 먼저 짖어드릴게요! 📢 ${CHANNEL_URL}` + updated;
    const body = news.slice(0, 8).map(p => productDetail(p, ps)).join("\n\n");
    return `🆕 <b>흰둥이가 물어온 신상 적금 ${news.length}건!</b> 🐕💨\n\n${body}` + updated;
  }

  if (cmd === "/뉴스" || cmd === "/news") {
    const ns = data.news || [];
    if (!ns.length) return "킁킁... 아직 물어온 적금 뉴스가 없어요 🐶 조금만 기다려 주세요!";
    const lines = ns.slice(0, 8).map(n =>
      `• <a href="${n.link}">${esc(n.title)}</a>${n.source ? ` (${esc(n.source)}${n.date ? ", " + n.date : ""})` : ""}`);
    return `📰 <b>흰둥이가 물어온 적금 뉴스</b> 🐕💨\n\n${lines.join("\n")}\n\n아직 공시 반영 전인 상품일 수 있어요!` + updated;
  }

  if (cmd === "/은행" || cmd === "/bank") {
    if (!arg) return "은행 이름을 함께 보내주세요. 예: <code>/은행 국민</code>";
    const found = ps.filter(p => p.bank.includes(arg))
      .sort((a, b) => b.best_rate - a.best_rate);
    if (!found.length) {
      const banks = [...new Set(ps.map(p => p.bank))].join(", ");
      return `"${esc(arg)}" 은행을 못 찾았어요.\n\n수집 중인 은행: ${esc(banks)}`;
    }
    const lines = found.slice(0, 15).map((p, i) => productLine(p, i + 1));
    return `🏦 <b>${esc(found[0].bank)} 적금 ${found.length}개</b>\n\n${lines.join("\n")}` + updated;
  }

  // 일반 텍스트 = 검색
  const q = (cmd.startsWith("/") ? arg : text).toLowerCase();
  if (!q) return null;
  const hits = ps.filter(p => (p.bank + p.name).toLowerCase().includes(q))
    .sort((a, b) => b.best_rate - a.best_rate);
  if (!hits.length) return `킁킁... "${esc(text)}" 는 못 찾았어요 🐶 /help 를 눌러 사용법을 확인해 보세요!`;
  if (hits.length <= 3) return hits.map(p => productDetail(p, ps)).join("\n\n") + updated;
  const lines = hits.slice(0, 12).map((p, i) => productLine(p, i + 1));
  return `🔎 <b>"${esc(text)}" 검색 결과 ${hits.length}개</b>\n\n${lines.join("\n")}\n\n상품명을 더 자세히 입력하면 상세 정보를 보여드려요.` + updated;
}

async function sendMessage(chatId, text) {
  // 텔레그램 메시지 길이 제한(4096자) 대응
  for (const chunk of splitMessage(text, 4000)) {
    const res = await fetch(`https://api.telegram.org/bot${BOT_TOKEN}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: chatId, text: chunk, parse_mode: "HTML",
        disable_web_page_preview: true,
      }),
    });
    const out = await res.json().catch(() => ({}));
    if (!out.ok) {
      // HTML 서식 문제 등으로 실패하면 서식 없이 재시도 (침묵 방지)
      await fetch(`https://api.telegram.org/bot${BOT_TOKEN}/sendMessage`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          chat_id: chatId,
          text: chunk.replace(/<[^>]+>/g, ""),
          disable_web_page_preview: true,
        }),
      });
    }
  }
}

function splitMessage(text, limit) {
  if (text.length <= limit) return [text];
  const parts = [];
  let cur = "";
  for (const para of text.split("\n\n")) {
    if ((cur + "\n\n" + para).length > limit && cur) { parts.push(cur); cur = para; }
    else cur = cur ? cur + "\n\n" + para : para;
  }
  if (cur) parts.push(cur);
  return parts;
}
