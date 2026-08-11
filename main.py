import os
import time
import akshare as ak
import pandas as pd


# 增加失败重试功能的辅助函数
def safe_fetch(ak_func, **kwargs):
    retries = 3  # 最多重试3次
    for i in range(retries):
        try:
            return ak_func(**kwargs)
        except Exception as e:
            if i == retries - 1: # 最后一次尝试
                raise e
            print(f"网络异常，{1}秒后重试...")
            time.sleep(1) # 延时1秒
    return None


# ================= 1. 大盘环境诊断 (增加重试) =================
def get_market_report():
    try:
        # 使用安全获取函数
        df_index = safe_fetch(ak.stock_zh_index_spot_em)
        if df_index is None:
            return "### 📊 1. 每日大盘诊断\n> 数据获取为空\n"

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
        return f"### 📊 1. 每日大盘诊断\n> 获取失败: 网络连接异常或数据接口不可用\n"


# 兼容获取历史数据 (自动识别 A股 与 ETF，增加重试)
def fetch_history_data(symbol):
    symbol = str(symbol).strip()
    try:
        # 5 或 1 开头的代码通常为 ETF/基金
        if symbol.startswith(("5", "1")):
            df = safe_fetch(ak.fund_etf_hist_em, symbol=symbol, period="daily", adjust="qfq")
        else:
            df = safe_fetch(ak.stock_zh_a_hist, symbol=symbol, period="daily", adjust="qfq")
        return df.tail(30) if df is not None and not df.empty else None
    except Exception:
        return None


# ================= 2. 自选股诊断与信号 (增加默认值和重试延时) =================
def analyze_watchlist(symbols):
    # 确保 symbols 列表非空，否则跳过
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
        
        # 优化：每次个股查询后延时 0.2 秒，降低被封概率
        time.sleep(0.2)

    return "### 🎯 2. 自选股诊断与买卖点\n" + "\n".join(results) + "\n"


# ================= 3. 精选策略股票池 (增加重试) =================
def get_stock_pool():
    try:
        # 使用安全获取函数
        spot_df = safe_fetch(ak.stock_zh_a_spot_em)
        if spot_df is None:
            return "### ⭐️ 3. 今日精选策略股票池\n> 选股失败: 数据获取为空\n"

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
        return f"### ⭐️ 3. 今日精选策略股票池\n> 选股失败: 网络连接异常或接口封禁\n"


# ================= 4. 推送逻辑 (精简为只显示摘要) =================
def send_notification(title, markdown_content):
    # 1. 写入 GitHub Actions 页面摘要 (手机/网页端直接查看)
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(f"# {title}\n\n" + markdown_content)
    else:
        # 如果不是在 GitHub Actions 运行，输出到控制台
        print(f"=== {title} ===\n{markdown_content}")


# ================= 主程序入口 =================
if __name__ == "__main__":
    # 确保 STOCK_LIST 有默认值，避免空跑
    stock_env = os.getenv("STOCK_LIST", "510330,515310,561990")
    symbols = stock_env.split(",")

    part1 = get_market_report()
    part2 = analyze_watchlist(symbols)
    part3 = get_stock_pool()

    full_report = f"{part1}\n{part2}\n{part3}"
    send_notification("📈 每日量化策略复盘报告", full_report)