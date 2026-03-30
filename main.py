#!/usr/bin/env python3
"""
ICT Trading Bot — Main entry point.

Usage:
    python main.py backtest              Run backtest on default symbol
    python main.py scan                  Scan all symbols for signals
    python main.py paper                 Start paper-trading loop
    python main.py live                  Start live-trading loop (real orders)
    python main.py dashboard             Launch Streamlit dashboard
    python main.py train                 Train / retrain the ML model
"""

import argparse
import logging
import subprocess
import sys
from pathlib import Path

# Ensure project root on path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from config import settings
from data.fetcher import DataFetcher
from strategy.ict_signals import ICTSignalGenerator
from engine.backtester import Backtester
from engine.live_trader import LiveTrader
from engine.risk_manager import RiskManager
from ml.model import SignalModel, generate_training_labels

# ── Logging ──────────────────────────────────────────────
LOG_FMT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
logging.basicConfig(
    level=logging.INFO,
    format=LOG_FMT,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(settings.LOG_DIR / "bot.log"),
    ],
)
logger = logging.getLogger("main")


def cmd_backtest(args):
    """Run a backtest."""
    logger.info("=== BACKTEST: %s ===", args.symbol)

    fetcher = DataFetcher()
    etf_df = fetcher.fetch_ohlc(args.symbol, args.etf, limit=args.candles)
    htf_df = fetcher.fetch_ohlc(args.symbol, args.htf, limit=args.candles // 4)
    ltf_df = fetcher.fetch_ohlc(args.symbol, args.ltf, limit=args.candles * 3)

    if etf_df is None:
        logger.error("Failed to fetch data for %s", args.symbol)
        return

    bt = Backtester(
        initial_balance=args.balance,
        min_confidence=args.confidence,
    )
    result = bt.run(etf_df, htf_df=htf_df, symbol=args.symbol, ltf_df=ltf_df)

    # Save results
    out = settings.DATA_DIR / "backtest_results.csv"
    if result.trades:
        import pandas as pd
        pd.DataFrame(result.trades).to_csv(out, index=False)
        logger.info("Trade log saved to %s", out)


def cmd_scan(args):
    """Scan symbols for ICT signals."""
    logger.info("=== SIGNAL SCAN ===")

    fetcher = DataFetcher()
    signal_gen = ICTSignalGenerator()
    symbols = settings.CRYPTO_SYMBOLS + settings.FOREX_SYMBOLS

    for symbol in symbols:
        try:
            htf_df = fetcher.fetch_ohlc(symbol, settings.HTF_TIMEFRAME, limit=200)
            etf_df = fetcher.fetch_ohlc(symbol, settings.ETF_TIMEFRAME, limit=200)
            ltf_df = fetcher.fetch_ohlc(symbol, settings.LTF_TIMEFRAME, limit=200)

            if htf_df is None or etf_df is None:
                continue

            signals = signal_gen.generate_signals(
                symbol=symbol, htf_df=htf_df, etf_df=etf_df, ltf_df=ltf_df,
            )

            if signals:
                for s in signals:
                    logger.info(
                        ">> %s %s | Entry=%.5f SL=%.5f TP=%.5f | R:R=%.1f | Conf=%.0f%% | %s",
                        s.signal_type.value, s.symbol,
                        s.entry, s.stop_loss, s.take_profit,
                        s.rr_ratio, s.confidence * 100,
                        ", ".join(s.reasons),
                    )
            else:
                logger.info("  %s -- no setups", symbol)
        except Exception:
            logger.exception("Error scanning %s", symbol)


def cmd_paper(args):
    """Start paper trading."""
    logger.info("=== PAPER TRADING ===")
    trader = LiveTrader(
        mode="paper",
        initial_balance=args.balance,
        min_confidence=args.confidence,
        use_ml=args.ml,
    )
    try:
        trader.start(interval_seconds=args.interval)
    except KeyboardInterrupt:
        trader.stop()
        summary = trader.status()
        logger.info("Final status: %s", summary)


def cmd_live(args):
    """Start live trading (real money)."""
    logger.warning("!! LIVE TRADING MODE -- REAL ORDERS WILL BE PLACED !!")
    confirm = input("Type 'CONFIRM' to proceed: ")
    if confirm != "CONFIRM":
        logger.info("Aborted.")
        return

    trader = LiveTrader(
        mode="live",
        initial_balance=args.balance,
        min_confidence=args.confidence,
        use_ml=args.ml,
    )
    try:
        trader.start(interval_seconds=args.interval)
    except KeyboardInterrupt:
        trader.stop()
        summary = trader.status()
        logger.info("Final status: %s", summary)


def cmd_dashboard(_args):
    """Launch Streamlit dashboard."""
    logger.info("Launching dashboard...")
    app_path = ROOT / "dashboard" / "app.py"
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(app_path)])


def cmd_tv(args):
    """Show live TradingView analysis for all symbols."""
    logger.info("=== TRADINGVIEW ANALYSIS ===")
    from data.tradingview import get_analysis

    symbols = settings.CRYPTO_SYMBOLS + settings.FOREX_SYMBOLS
    tf = args.timeframe if hasattr(args, "timeframe") else settings.MTF_TF

    for symbol in symbols:
        try:
            tv = get_analysis(symbol, tf)
            if tv:
                # Color-code recommendation
                rec = tv.recommendation.value
                logger.info(
                    "  %s [%s] | close=%.5f | RSI=%.1f | ADX=%.1f | "
                    "EMA20=%.5f EMA50=%.5f EMA200=%.5f | ATR=%.5f | %s",
                    symbol, tf, tv.close, tv.rsi, tv.adx,
                    tv.ema_20, tv.ema_50, tv.ema_200, tv.atr, rec,
                )

                # Summary counts
                osc = tv.summary_oscillators or {}
                ma = tv.summary_moving_avgs or {}
                logger.info(
                    "    Oscillators: BUY=%d SELL=%d NEUTRAL=%d | "
                    "Moving Avgs: BUY=%d SELL=%d NEUTRAL=%d",
                    osc.get("BUY", 0), osc.get("SELL", 0), osc.get("NEUTRAL", 0),
                    ma.get("BUY", 0), ma.get("SELL", 0), ma.get("NEUTRAL", 0),
                )
            else:
                logger.info("  %s -- no TV data", symbol)
            import time
            time.sleep(0.5)  # rate limit
        except Exception:
            logger.exception("Error fetching TV data for %s", symbol)


def cmd_train(args):
    """Train ML signal-confirmation model from backtest data."""
    logger.info("=== ML TRAINING ===")

    fetcher = DataFetcher()
    signal_gen = ICTSignalGenerator()

    symbols = settings.CRYPTO_SYMBOLS[:3]  # Use top 3 for training
    all_X, all_y = [], []

    for symbol in symbols:
        logger.info("Generating training data for %s ...", symbol)
        etf_df = fetcher.fetch_ohlc(symbol, settings.ETF_TIMEFRAME, limit=2000)
        htf_df = fetcher.fetch_ohlc(symbol, settings.HTF_TIMEFRAME, limit=500)

        if etf_df is None:
            continue

        signals = signal_gen.generate_signals(symbol=symbol, htf_df=htf_df or etf_df, etf_df=etf_df)
        if not signals:
            continue

        X, y = generate_training_labels(etf_df, signals)
        if len(X) > 0:
            all_X.append(X)
            all_y.append(y)

    if not all_X:
        logger.error("No training data collected")
        return

    import pandas as pd
    X = pd.concat(all_X, ignore_index=True)
    y = pd.concat(all_y, ignore_index=True)

    logger.info("Training on %d samples (%.0f%% wins)", len(X), y.mean() * 100)

    model = SignalModel()
    model.train(X, y)
    model.save()

    # Show feature importance
    imp = model.feature_importance()
    logger.info("Top features:\n%s", imp.head(10).to_string())


# ── CLI ──────────────────────────────────────────────────
def build_parser():
    parser = argparse.ArgumentParser(
        description="ICT Trading Bot — Forex & Crypto Expert System",
    )
    sub = parser.add_subparsers(dest="command")

    # backtest
    bt = sub.add_parser("backtest", help="Run historical backtest")
    bt.add_argument("--symbol", default="BTC/USDT")
    bt.add_argument("--etf", default=settings.ETF_TIMEFRAME)
    bt.add_argument("--htf", default=settings.HTF_TIMEFRAME)
    bt.add_argument("--ltf", default=settings.LTF_TIMEFRAME)
    bt.add_argument("--candles", type=int, default=1000)
    bt.add_argument("--balance", type=float, default=10_000)
    bt.add_argument("--confidence", type=float, default=0.5)

    # scan
    sub.add_parser("scan", help="Scan all symbols for signals")

    # paper
    pp = sub.add_parser("paper", help="Paper trading loop")
    pp.add_argument("--balance", type=float, default=10_000)
    pp.add_argument("--confidence", type=float, default=0.5)
    pp.add_argument("--interval", type=int, default=60)
    pp.add_argument("--ml", action="store_true", help="Enable ML filter")

    # live
    lv = sub.add_parser("live", help="Live trading (real orders)")
    lv.add_argument("--balance", type=float, default=10_000)
    lv.add_argument("--confidence", type=float, default=0.6)
    lv.add_argument("--interval", type=int, default=60)
    lv.add_argument("--ml", action="store_true", help="Enable ML filter")

    # dashboard
    sub.add_parser("dashboard", help="Launch Streamlit dashboard")

    # tv (TradingView analysis)
    tv = sub.add_parser("tv", help="Show live TradingView analysis")
    tv.add_argument("--timeframe", default=settings.MTF_TF,
                     help="Timeframe for analysis (default: MTF)")

    # train
    sub.add_parser("train", help="Train ML model")

    return parser


if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()

    commands = {
        "backtest": cmd_backtest,
        "scan": cmd_scan,
        "paper": cmd_paper,
        "live": cmd_live,
        "dashboard": cmd_dashboard,
        "tv": cmd_tv,
        "train": cmd_train,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()
