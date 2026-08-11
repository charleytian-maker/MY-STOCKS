mport os
import time
import baostock as bs
import pandas as pd
import yfinance as yf


# ================= 1. 基础数据获取：BaoStock + yfinance 保底 =================
def parse_code(symbol):
    symbol = str(symbol).strip()
    # 6/5/9开头属于沪市(sh/.SS)，其余(0/3/1)属于深市(sz/.SZ)
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
            "date,close,volume",
            start_date="2026-01-01",
            adjustflag="3",  # 前复权
        )
        data_list = []
        while (rs.error_code == "0") & rs.next():
            data_list.append(rs.get_row_data())
        bs.logout()

        if data_list:
            df = pd.DataFrame(data_list, columns=["date", "close", "volume"])
            df["close"] = df["close"].astype(float)
            df["volume"] = df["volume"].astype(float)
            if not df.empty:
                return df.tail(30)
    except Exception as e:
        print(f"[{symbol}] BaoStock 获取失败: {e}，切换至 yfinance...")

    # --- 备用尝试 yfinance ---
    try:
        ticker = yf.Ticker(yf_code)
        df = ticker.history(period="2m")
        if df is not None and not df.empty:
            df = df.reset_index()
            df = df[["Date", "Close", "Volume"]]
            df.columns = ["date", "close", "volume"]
            df["close"] = df["close"].astype(float)
            df["volume"] = df["volume"].astype(float)
            return df.tail(30)
    except Exception as e:
        print(f"[{symbol}] yfinance 获取失败: {e}")

    return None


# ================= 2. 大盘诊断 (通过 BaoStock 获取上证指数) =================
def get_market_report():
    try:
        df = fetch_history_data("600519")  # 以大盘代表标的查看整体动向
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
    except Exception as e:
        pass
    return "### 📊 1. 每日大盘诊断\n> 大盘数据暂不可用\n"


# ================= 3. 自选股诊断与买卖点 =================
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

        df["MA5"] = df["close"].rolling(5).mean()
        df["MA20"] = df["close"].rolling(20).mean()

        close = latest["close"]
        ma5 = df["MA5"].iloc[-1]
        ma20 = df["MA20"].iloc[-1]

        trend = "📈 多头" if close > ma20 else "📉 空头"

        avg_vol5 = df["volume"].tail(6).iloc[:-1].mean()
        vol_ratio = (
            round(latest["volume"] / avg_vol5, 2) if avg_vol5 > 0 else 1.0
        )
        vol_status = (
            "放量" if vol_ratio >= 1.3 else ("缩量" if vol_ratio <= 0.7 else "平量")
        )

        signal = "观望"
        if close > ma20 and prev["close"] <= ma20 and vol_ratio >= 1.2:
            signal = "🔴 **强力买点** (突破20日线+放量)"
        elif close > ma5 and prev["close"] <= ma5:
            signal = "🔴 **弱买点** (站上5日线)"
        elif close < ma5 and prev["close"] >= ma5:
            signal = "🟢 **短线离场** (跌破5日线)"
        elif close < ma20 and prev["close"] >= ma20:
            signal = "🟢 **强力止损** (跌破20日线)"

        results.append(
            f"- **[{code}]** 现价: `{close}` | 趋势: {trend} | 量能: `{vol_status}(量比{vol_ratio})` | 信号: {signal}"
        )

    return "### 🎯 2. 自选股诊断与买卖点\n" + "\n".join(results) + "\n"


# ================= 4. 输出至 Run Script 日志与 Summary =================
def send_notification(title, markdown_content):
    # 打印到日志末尾，方便在 Run Script 里直接看
    print("\n" + "=" * 50)
    print(f"       {title}")
    print("=" * 50 + "\n")
    print(markdown_content)
    print("=" * 50 + "\n")

    # 写入 Summary
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
