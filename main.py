import os
import time
import akshare as ak
import baostock as bs
import pandas as pd
import yfinance as yf


# ================= 辅助函数：格式转换与多源降级获取 =================
def parse_code(symbol):
    symbol = str(symbol).strip()
    # 6开头的A股、5/9开头的ETF归属沪市(sh/.SS)，其余(0/3/1)归属深市(sz/.SZ)
    if symbol.startswith(("6", "5", "9")):
        market = "sh"
        yf_market = "SS"
    else:
        market = "sz"
        yf_market = "SZ"

    return {
        "raw": symbol,
        "bs": f"{market}.{symbol}",
        "yf": f"{symbol}.{yf_market}",
    }


def fetch_history_data(symbol):
    code_info = parse_code(symbol)
    raw_code = code_info["raw"]

    # --- 1. 优先尝试 AKShare ---
    try:
        if raw_code.startswith(("5", "1")):
            df = ak.fund_etf_hist_em(
                symbol=raw_code, period="daily", adjust="qfq"
            )
        else:
            df = ak.stock_zh_a_hist(
                symbol=raw_code, period="daily", adjust="qfq"
            )

        if df is not None and not df.empty:
            df = df.tail(30)[["日期", "收盘", "成交量"]]
            df.columns = ["date", "close", "volume"]
            # 确保类型转换
            df["close"] = df["close"].astype(float)
            df["volume"] = df["volume"].astype(float)
            return df
    except Exception:
        print(f"[{raw_code}] AKShare 获取失败，正在切换至 BaoStock...")

    # --- 2. 次选尝试 BaoStock ---
    try:
        lg = bs.login()
        rs = bs.query_history_k_data_plus(
            code_info["bs"],
            "date,close,volume",
            start_date="2026-01-01",
            adjustflag="3",
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
                print(f"[{raw_code}] 通过 BaoStock 成功获取数据")
                return df.tail(30)
    except Exception:
        print(f"[{raw_code}] BaoStock 获取失败，正在切换至 yfinance...")

    # --- 3. 终极保底 yfinance ---
    try:
        ticker = yf.Ticker(code_info["yf"])
        df = ticker.history(period="2m")
        if df is not None and not df.empty:
            df = df.reset_index()
            df = df[["Date", "Close", "Volume"]]
            df.columns = ["date", "close", "volume"]
            print(f"[{raw_code}] 通过 yfinance 成功获取数据")
            return df.tail(30)
    except Exception as e:
        print(f"[{raw_code}] 所有数据源均获取失败: {e}")

    return None


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

        return (
            f"### 📊 1. 每日大盘诊断\n"
            f"- **市场环境**：{status}\n"
            f"- **上证指数**：{sh_idx['最新价']} ({sh_change:+}%)\n"
            f"- **深证成指**：{sz_idx['最新价']} ({sz_idx['涨跌幅']:+}%)\n"
            f"- **创业板指**：{cy_idx['最新价']} ({cy_idx['涨跌幅']:+}%)\n"
        )
    except Exception:
        return "### 📊 1. 每日大盘诊断\n> 大盘接口响应超时，跳过大盘看板\n"


# ================= 2. 自选股诊断与买卖点 =================
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
        time.sleep(0.2)

    return "### 🎯 2. 自选股诊断与买卖点\n" + "\n".join(results) + "\n"


# ================= 3. 精选策略股票池 =================
def get_stock_pool():
    try:
        spot_df = ak.stock_zh_a_spot_em()
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
            return "### ⭐️ 3. 今日精选策略股票池\n> 今日全市场无符合放量突破条件的标的\n"

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


# ================= 4. 输出至控制台日志与 Summary =================
def send_notification(title, markdown_content):
    # 1. 重点：直接打印到控制台日志，方便在 Run Script 界面直接阅读
    print("\n" + "=" * 50)
    print(f"       {title}")
    print("=" * 50 + "\n")
    print(markdown_content)
    print("=" * 50 + "\n")

    # 2. 保留 Summary 写入逻辑
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(f"# {title}\n\n" + markdown_content)


if __name__ == "__main__":
    stock_env = os.getenv("STOCK_LIST", "510330,515310,561990")
    symbols = stock_env.split(",")

    part1 = get_market_report()
    part2 = analyze_watchlist(symbols)
    part3 = get_stock_pool()

    full_report = f"{part1}\n{part2}\n{part3}"
    send_notification("📈 每日量化策略复盘报告", full_report)
