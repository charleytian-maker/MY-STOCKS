import os
import requests
import smtplib
from email.mime.text import MIMEText
import akshare as ak
import pandas as pd


# ================= 1. 大盘环境诊断 =================
def get_market_report():
    try:
        df_index = ak.stock_zh_index_spot_em()
        sh_idx = df_index[df_index["名称"] == "上证指数"].iloc[0]
        sz_idx = df_index[df_index["名称"] == "深证成指"].iloc[0]
        cy_idx = df_index[df_index["名称"] == "创业板指"].iloc[0]

        sh_change = float(sh_idx["涨跌幅"])

        if sh_change >= 0.5:
            status = "🔴 多头强势 (适合积极操作)"
        elif sh_change > -0.5:
            status = "🟡 震荡盘整 (控制仓位)"
        else:
            status = "🟢 空头防守 (谨慎观望)"

        report = (
            f"### 📊 1. 每日大盘诊断\n"
            f"- **市场环境**：{status}\n"
            f"- **上证指数**：{sh_idx['最新价']} ({sh_change:+}%)\n"
            f"- **深证成指**：{sz_idx['最新价']} ({sz_idx['涨跌幅']:+}%)\n"
            f"- **创业板指**：{cy_idx['最新价']} ({cy_idx['涨跌幅']:+}%)\n"
        )
        return report
    except Exception as e:
        return f"### 📊 1. 每日大盘诊断\n> 获取失败: {e}\n"


# 兼容获取历史数据（自动识别 A股 与 ETF）
def fetch_history_data(symbol):
    symbol = str(symbol).strip()
    try:
        # 5 或 1 开头的代码通常为 ETF/基金
        if symbol.startswith(("5", "1")):
            df = ak.fund_etf_hist_em(
                symbol=symbol, period="daily", adjust="qfq"
            )
        else:
            df = ak.stock_zh_a_hist(symbol=symbol, period="daily", adjust="qfq")
        return df.tail(30) if df is not None and not df.empty else None
    except Exception:
        return None


# ================= 2. 自选股诊断与信号 =================
def analyze_watchlist(symbols):
    results = []
    for code in symbols:
        code = code.strip()
        if not code:
            continue

        df = fetch_history_data(code)
        if df is None or len(df) < 20:
            results.append(f"- **[{code}]**：获取历史数据失败或数据不足")
            continue

        latest = df.iloc[-1]
        prev = df.iloc[-2]

        # 计算 5日、20日均线
        df["MA5"] = df["收盘"].rolling(5).mean()
        df["MA20"] = df["收盘"].rolling(20).mean()

        close = latest["收盘"]
        ma5 = df["MA5"].iloc[-1]
        ma20 = df["MA20"].iloc[-1]

        # 趋势判断
        trend = "📈 多头" if close > ma20 else "📉 空头"

        # 量能分析 (对比前5日均量)
        avg_vol5 = df["成交量"].tail(6).iloc[:-1].mean()
        vol_ratio = (
            round(latest["成交量"] / avg_vol5, 2) if avg_vol5 > 0 else 1.0
        )
        vol_status = (
            "放量" if vol_ratio >= 1.3 else ("缩量" if vol_ratio <= 0.7 else "平量")
        )

        # 买卖点信号
        signal = "观望"
        if close > ma20 and prev["收盘"] <= ma20 and vol_ratio >= 1.2:
            signal = "🔴 **强力买点** (突破20日线+放量)"
        elif close > ma5 and prev["收盘"] <= ma5:
            signal = "🔴 **弱买点** (站上5日线)"
        elif close < ma5 and prev["收盘"] >= ma5:
            signal = "🟢 **短线离场** (跌破5日线)"
        elif close < ma20 and prev["收盘"] >= ma20:
            signal = "🟢 **强力止损** (跌破20日线)"

        results.append(
            f"- **[{code}]** 现价: `{close}` | 趋势: {trend} | 量能: `{vol_status}(量比{vol_ratio})` | 信号: {signal}"
        )

    return "### 🎯 2. 自选股诊断与买卖点\n" + "\n".join(results) + "\n"


# ================= 3. 精选策略股票池 =================
def get_stock_pool():
    try:
        spot_df = ak.stock_zh_a_spot_em()

        # 过滤条件: 非ST、非退市、涨幅 3%~7%、换手率 3%~10%、量比 > 1.3
        filtered = spot_df[
            (~spot_df["名称"].str.contains("ST|退", na=False))
            & (spot_df["涨跌幅"] >= 3.0)
            & (spot_df["涨跌幅"] <= 7.0)
            & (spot_df["换手率"] >= 3.0)
            & (spot_df["换手率"] <= 10.0)
            & (spot_df["量比"] >= 1.3)
        ].copy()

        top_stocks = filtered.sort_values(by="换手率", ascending=False).head(5)

        if top_stocks.empty:
            return "### ⭐️ 3. 今日精选策略股票池\n> 今日全市场无符合多重放量突破条件的标的\n"

        pool_list = []
        for _, row in top_stocks.iterrows():
            pool_list.append(
                f"- **{row['名称']}** (`{row['代码']}`) | 现价: `{row['最新价']}` | 涨幅: `+{row['涨跌幅']}%` | 换手率: `{row['换手率']}%`"
            )

        return (
            "### ⭐️ 3. 今日精选策略股票池 (放量突破型)\n"
            + "\n".join(pool_list)
            + "\n"
        )
    except Exception as e:
        return f"### ⭐️ 3. 今日精选策略股票池\n> 选股失败: {e}\n"


# ================= 4. 多渠道推送逻辑 =================
def send_notification(title, markdown_content):
    # 1. 写入 GitHub Actions 页面日志
    print(f"=== {title} ===\n{markdown_content}")
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(f"# {title}\n\n" + markdown_content)

    # 2. PushPlus 微信推送 (可选)
    pushplus_token = os.getenv("PUSHPLUS_TOKEN")
    if pushplus_token:
        try:
            requests.post(
                "http://www.pushplus.plus/send",
                json={
                    "token": pushplus_token,
                    "title": title,
                    "content": markdown_content,
                    "template": "markdown",
                },
                timeout=10,
            )
        except Exception as e:
            print(f"PushPlus 发送失败: {e}")

    # 3. 邮件推送 (可选)
    email_sender = os.getenv("EMAIL_SENDER")
    email_password = os.getenv("EMAIL_PASSWORD")
    email_receivers = os.getenv("EMAIL_RECEIVERS")

    if email_sender and email_password and email_receivers:
        try:
            receivers_list = [
                r.strip() for r in email_receivers.split(",") if r.strip()
            ]
            msg = MIMEText(markdown_content, "plain", "utf-8")
            msg["Subject"] = title
            msg["From"] = email_sender
            msg["To"] = ", ".join(receivers_list)

            with smtplib.SMTP_SSL("smtp.qq.com", 465) as server:
                server.login(email_sender, email_password)
                server.sendmail(email_sender, receivers_list, msg.as_string())
            print("邮件发送成功！")
        except Exception as e:
            print(f"邮件发送失败: {e}")


# ================= 主程序入口 =================
if __name__ == "__main__":
    stock_env = os.getenv("STOCK_LIST", "510330,515310,561990")
    symbols = stock_env.split(",")

    part1 = get_market_report()
    part2 = analyze_watchlist(symbols)
    part3 = get_stock_pool()

    full_report = f"{part1}\n{part2}\n{part3}"
    send_notification("📈 每日量化策略复盘报告", full_report)
