import akshare as ak
import pandas as pd


# 1. 每日大盘分析
def get_market_report():
    df_index = ak.stock_zh_index_spot_em()
    sh_index = df_index[df_index["名称"] == "上证指数"].iloc[0]
    sh_change = sh_index["涨跌幅"]

    status = "多头安全" if sh_change > 0 else "空头防守"
    return f"【大盘报告】上证指数：{sh_index['最新价']} ({sh_change}%) | 市场环境：{status}"


# 2. 自选股分析与买卖点
def analyze_watchlist(symbols):
    results = []
    for code in symbols:
        # 获取日线历史数据
        df = ak.stock_zh_a_hist(
            symbol=code, period="daily", adjust="qfq"
        ).tail(30)
        if len(df) < 20:
            continue

        latest = df.iloc[-1]
        prev = df.iloc[-2]
        ma20 = df["收盘"].rolling(20).mean().iloc[-1]

        # 趋势与量能判断
        trend = "多头" if latest["收盘"] > ma20 else "空头"
        vol_ratio = round(latest["成交量"] / df["成交量"].tail(5).mean(), 2)

        # 信号生成逻辑
        signal = "观望"
        if (
            latest["收盘"] > ma20
            and prev["收盘"] <= ma20
            and vol_ratio > 1.3
        ):
            signal = "🔴 出现买点 (突破20日线+放量)"
        elif latest["收盘"] < ma20 and prev["收盘"] >= ma20:
            signal = "🟢 出现卖点 (跌破20日线)"

        results.append(
            f"标的 [{code}] | 趋势: {trend} | 量比: {vol_ratio} | 信号: {signal}"
        )

    return "\n".join(results)


# 3. 选股池过滤（推荐 3-5 只）
def get_stock_pool():
    spot_df = ak.stock_zh_a_spot_em()

    # 硬条件筛选：非ST、涨幅 3%~7%、换手率 3%~10%、量比 > 1.5
    filtered = spot_df[
        (~spot_df["名称"].str.contains("ST|退"))
        & (spot_df["涨跌幅"] >= 3.0)
        & (spot_df["涨跌幅"] <= 7.0)
        & (spot_df["换手率"] >= 3.0)
        & (spot_df["换手率"] <= 10.0)
        & (spot_df["量比"] >= 1.5)
    ].copy()

    # 按换手率降序，取前 3~5 只
    top_stocks = filtered.sort_values(by="换手率", ascending=False).head(5)

    pool_list = []
    for _, row in top_stocks.iterrows():
        pool_list.append(
            f"⭐️ {row['名称']} ({row['代码']}) - 涨幅: {row['涨跌幅']}% | 换手: {row['换手率']}%"
        )

    return "\n".join(pool_list)


# 执行主程序
if __name__ == "__main__":
    print(get_market_report())
    print("\n【自选股诊断】")
    print(analyze_watchlist(["510330", "515310"]))
    print("\n【精选策略股票池 (3-5只)】")
    print(get_stock_pool())
