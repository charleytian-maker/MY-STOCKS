import os
import time
import baostock as bs
import pandas as pd
import yfinance as yf


# ================= 1. 基础数据获取 =================
def parse_code(symbol):
    symbol = str(symbol).strip()
    if symbol.startswith(("6", "5", "9")):
        bs_code = f"sh.{symbol}"
        yf_code = f"{symbol}.SS"
    else:
        bs_code = f"sz.{symbol}"
        yf_code = f"{symbol}.SZ"
    return bs_code, yf_code


def fetch_history_data(symbol):
    symbol = str(symbol).strip()
    bs_code, yf_code = parse_code(symbol)

    # --- 优先尝试 BaoStock ---
    try:
        lg = bs.login()
        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,close,volume,turn,peTTM",
            start_date="2026-01-01",
            adjustflag="3",  # 前复权
        )
        data_list = []
        while (rs.error_code == "0") & rs.next():
            data_list.append(rs.get_row_data())
        bs.logout()

        if data_list:
            df = pd.DataFrame(
                data_list, columns=["date", "close", "volume", "turn", "peTTM"]
            )
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
            df["turn"] = pd.to_numeric(df["turn"], errors="coerce").fillna(0.0)
            df["peTTM"] = pd.to_numeric(df["peTTM"], errors="coerce").fillna(
                0.0
            )

            if not df.empty:
                return df.tail(40)  # 保留40条以计算完整的RSI14
    except Exception as e:
        print(f"[{symbol}] BaoStock 获取失败: {e}，切换至 yfinance...")

    # --- 备用尝试 yfinance ---
    try:
        ticker = yf.Ticker(yf_code)
        df = ticker.history(period="3m")
        if df is not None and not df.empty:
            df = df.reset_index()
            df = df[["Date", "Close", "Volume"]]
            df.columns = ["date", "close", "volume"]
            df["close"] = df["close"].astype(float)
            df["volume"] = df["volume"].astype(float)
            df["turn"] = 0.0
            df["peTTM"] = 0.0
            return df.tail(40)
    except Exception as e:
        print(f"[{symbol}] yfinance 获取失败: {e}")

    return None


# ================= 2. 大盘诊断 =================
def get_market_report():
    try:
        lg = bs.login()
        rs = bs.query_history_k_data_plus(
            "sh.000001", "date,close,pctChg", start_date="2026-01-01"
        )
        data_list = []
        while (rs.error_code == "0") & rs.next():
            data_list.append(rs.get_row_data())
        bs.logout()

        if data_list:
            df_sh = pd.DataFrame(data_list, columns=["date", "close", "pctChg"])
            latest = df_sh.iloc[-1]
            sh_change = float(latest["pctChg"])
            sh_close = float(latest["close"])

            if sh_change >= 0.5:
                status = "🔴 多头强势 (适合积极操作)"
            elif sh_change > -0.5:
                status = "🟡 震荡盘整 (控制仓位)"
            else:
                status = "🟢 空头防守 (谨慎观望)"

            return (
                f"### 📊 1. 每日大盘诊断\n"
                f"- **市场环境**：{status}\n"
                f"- **上证指数**：`{sh_close}` ({sh_change:+}%)\n"
            )
    except Exception:
        pass
    return "### 📊 1. 每日大盘诊断\n> 大盘数据暂不可用\n"


# ================= 3. 自选股诊断与全面量化指标 =================
def analyze_watchlist(symbols):
    if not symbols or (len(symbols) == 1 and not symbols[0]):
        return "### 🎯 2. 自选股诊断与买卖点\n> 未配置自选股列表 (STOCK_LIST)\n"

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

        # 1. 均线计算
        df["MA5"] = df["close"].rolling(5).mean()
        df["MA6"] = df["close"].rolling(6).mean()
        df["MA20"] = df["close"].rolling(20).mean()

        close = latest["close"]
        ma5 = df["MA5"].iloc[-1]
        ma6 = df["MA6"].iloc[-1]
        ma20 = df["MA20"].iloc[-1]

        # 2. 乖离率 BIAS(6) 计算
        bias6 = (
            round(((close - ma6) / ma6) * 100, 2) if ma6 and ma6 > 0 else 0.0
        )

        # 3. RSI(14) 计算
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        df["RSI14"] = 100 - (100 / (1 + rs))
        rsi14 = round(df["RSI14"].iloc[-1], 1) if not pd.isna(df["RSI14"].iloc[-1]) else "N/A"

        # 4. 支撑位与压力位 (近期20日最低/最高价)
        support_price = round(df["close"].tail(20).min(), 2)
        resistance_price = round(df["close"].tail(20).max(), 2)

        # 5. 趋势判断
        trend = "📈 多头" if close > ma20 else "📉 空头"

        # 6. 量能 (量比) 计算
        avg_vol5 = df["volume"].tail(6).iloc[:-1].mean()
        vol_ratio = (
            round(latest["volume"] / avg_vol5, 2) if avg_vol5 > 0 else 1.0
        )
        vol_status = (
            "放量" if vol_ratio >= 1.3 else ("缩量" if vol_ratio <= 0.7 else "平量")
        )

        # 7. 换手率与动态市盈率
        turn_str = f"{latest['turn']:.2f}%" if latest["turn"] > 0 else "N/A"
        pe_str = f"{latest['peTTM']:.1f}" if latest["peTTM"] > 0 else "N/A"

        # 8. 买卖点与风控预警信号
        signal = "观望"
        if close > ma20 and prev["close"] <= ma20 and vol_ratio >= 1.2:
            signal = "🔴 **强力买点** (突破20日线+放量)"
        elif close > ma5 and prev["close"] <= ma5:
            signal = "🔴 **弱买点** (站上5日线)"
        elif close < ma5 and prev["close"] >= ma5:
            signal = "🟢 **短线离场** (跌破5日线)"
        elif close < ma20 and prev["close"] >= ma20:
            signal = "🟢 **强力止损** (跌破20日线)"

        # 辅助风控预警
        if bias6 >= 6.0 or (isinstance(rsi14, float) and rsi14 >= 75):
            signal += " | ⚠️ **超买预警** (谨防回调)"
        elif bias6 <= -6.0 or (isinstance(rsi14, float) and rsi14 <= 25):
            signal += " | 💡 **超跌预警** (关注反弹)"

        # 输出美化行
        results.append(
            f"- **[{code}]** 现价: `{close}` | 趋势: {trend}\n"
            f"  - 📊 指标: 量能:`{vol_status}(量比{vol_ratio})` | 换手:`{turn_str}` | BIAS6:`{bias6}%` | RSI14:`{rsi14}` | PE(TTM):`{pe_str}`\n"
            f"  - 🛡️ 风控: 支撑位:`{support_price}` | 压力位:`{resistance_price}`\n"
            f"  - 💡 信号: {signal}"
        )

    return "### 🎯 2. 自选股诊断与买卖点\n" + "\n\n".join(results) + "\n"


# ================= 4. 输出至 Run Script 日志与 Summary =================
def send_notification(title, markdown_content):
    print("\n" + "=" * 50)
    print(f"       {title}")
    print("=" * 50 + "\n")
    print(markdown_content)
    print("=" * 50 + "\n")

    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(f"# {title}\n\n" + markdown_content)


if __name__ == "__main__":
    stock_env = os.getenv("STOCK_LIST", "510330,515310,561990")
    symbols = stock_env.split(",")

    part1 = get_market_report()
    part2 = analyze_watchlist(symbols)

    full_report = f"{part1}\n{part2}"
    send_notification("📈 每日量化策略复盘报告", full_report)