"""
Forecasting Engine — Task 2.2
Detects time-series questions and generates 30/60/90-day forecasts.
Methods: Holt-Winters (seasonal), linear regression (trending), moving average (noisy).
No heavy ML required — uses numpy + basic statistics.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

MIN_POINTS = 7   # Minimum data points required


@dataclass
class ForecastPoint:
    date: str           # ISO date string
    value: float
    lower: float        # 95% CI lower bound
    upper: float        # 95% CI upper bound
    is_forecast: bool = True

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "value": round(self.value, 4),
            "lower": round(self.lower, 4),
            "upper": round(self.upper, 4),
            "is_forecast": self.is_forecast,
        }


@dataclass
class ForecastResult:
    method: str                              # linear | holt_winters | moving_average
    horizon: int                             # days forecasted
    r_squared: float                         # goodness of fit (0–1)
    historical: list[ForecastPoint] = field(default_factory=list)
    predictions: list[ForecastPoint] = field(default_factory=list)
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "horizon": self.horizon,
            "r_squared": round(self.r_squared, 4),
            "historical": [p.to_dict() for p in self.historical],
            "predictions": [p.to_dict() for p in self.predictions],
            "message": self.message,
        }


# ── Intent detection keywords ─────────────────────────────────────────────

FORECAST_KEYWORDS = [
    "predict", "forecast", "will", "next month", "next quarter", "next year",
    "by q", "going forward", "trend", "projection", "expected", "future",
    "30 days", "60 days", "90 days", "estimate",
]


def is_forecast_question(question: str) -> bool:
    """Check if the question is asking for a forecast."""
    q = (question or "").lower()
    return any(kw in q for kw in FORECAST_KEYWORDS)


def detect_horizon(question: str) -> int:
    """Extract forecast horizon in days from the question text."""
    import re
    q = (question or "").lower()
    m = re.search(r"(\d+)\s*days?", q)
    if m:
        return min(365, max(7, int(m.group(1))))
    if "30 day" in q or "month" in q:
        return 30
    if "60 day" in q:
        return 60
    if "90 day" in q or "quarter" in q:
        return 90
    if "year" in q:
        return 365
    return 30  # default


class ForecastEngine:
    """
    Lightweight time-series forecaster using only numpy.
    Chooses the best method based on data characteristics.
    """

    def forecast(
        self,
        dates: list[str],
        values: list[float],
        horizon: int = 30,
    ) -> Optional[ForecastResult]:
        """
        Args:
            dates: list of ISO date strings (sorted ascending)
            values: corresponding numeric values
            horizon: number of future days to predict
        Returns ForecastResult or None if data insufficient.
        """
        if len(values) < MIN_POINTS:
            logger.info(f"Insufficient data for forecast: {len(values)} points (need {MIN_POINTS})")
            return ForecastResult(
                method="none",
                horizon=horizon,
                r_squared=0.0,
                message=f"Insufficient data for forecasting. Need at least {MIN_POINTS} data points, got {len(values)}.",
            )

        try:
            import numpy as np
            vals = np.array(values, dtype=float)
            n = len(vals)

            # Select method
            method = self._select_method(vals)

            if method == "linear":
                preds, r2, ci_half = self._linear_regression(vals, horizon)
            elif method == "holt_winters":
                preds, r2, ci_half = self._holt_winters(vals, horizon)
            else:
                preds, r2, ci_half = self._moving_average(vals, horizon)

            # Build historical points
            historical = []
            for i, (d, v) in enumerate(zip(dates, values)):
                fitted = float(preds[i]) if i < len(preds) - horizon else v
                historical.append(ForecastPoint(
                    date=str(d),
                    value=float(v),
                    lower=float(v),
                    upper=float(v),
                    is_forecast=False,
                ))

            # Build forecast points
            import datetime
            try:
                last_date = datetime.date.fromisoformat(str(dates[-1]).split("T")[0])
            except Exception:
                last_date = datetime.date.today()

            future_points = []
            for i in range(horizon):
                future_date = last_date + datetime.timedelta(days=i + 1)
                pred_val = float(preds[n + i]) if (n + i) < len(preds) else float(preds[-1])
                ci = float(ci_half)
                future_points.append(ForecastPoint(
                    date=future_date.isoformat(),
                    value=pred_val,
                    lower=pred_val - ci,
                    upper=pred_val + ci,
                    is_forecast=True,
                ))

            return ForecastResult(
                method=method,
                horizon=horizon,
                r_squared=float(r2),
                historical=historical,
                predictions=future_points,
                message=f"Forecast generated using {method.replace('_', ' ')} method with R²={r2:.3f}.",
            )
        except Exception as e:
            logger.warning(f"Forecast failed: {e}")
            return None

    @staticmethod
    def _select_method(vals) -> str:
        import numpy as np
        n = len(vals)
        # Check seasonality heuristic (weekly = period 7)
        if n >= 21:
            try:
                # Simple autocorrelation at lag 7
                mean = np.mean(vals)
                ac7 = np.corrcoef(vals[:-7] - mean, vals[7:] - mean)[0, 1]
                if ac7 > 0.5:
                    return "holt_winters"
            except Exception:
                pass
        # Check for trend (linear correlation with time index)
        x = np.arange(n, dtype=float)
        try:
            r = np.corrcoef(x, vals)[0, 1]
            if abs(r) > 0.6:
                return "linear"
        except Exception:
            pass
        return "moving_average"

    @staticmethod
    def _linear_regression(vals, horizon: int):
        import numpy as np
        n = len(vals)
        x = np.arange(n, dtype=float)
        slope, intercept = np.polyfit(x, vals, 1)
        x_full = np.arange(n + horizon, dtype=float)
        preds = slope * x_full + intercept
        # R²
        fitted = slope * x + intercept
        ss_res = np.sum((vals - fitted) ** 2)
        ss_tot = np.sum((vals - np.mean(vals)) ** 2)
        r2 = max(0.0, 1 - ss_res / ss_tot) if ss_tot > 0 else 0.0
        # CI: ±1.96 * residual std
        std = np.std(vals - fitted) if n > 2 else abs(np.mean(vals)) * 0.1
        ci_half = 1.96 * std
        return preds, r2, ci_half

    @staticmethod
    def _holt_winters(vals, horizon: int, alpha: float = 0.3, beta: float = 0.1):
        """Simple double exponential smoothing (linear Holt's method)."""
        import numpy as np
        n = len(vals)
        level = vals[0]
        trend = (vals[1] - vals[0]) if n > 1 else 0.0
        smoothed = []
        for v in vals:
            prev_level = level
            level = alpha * v + (1 - alpha) * (level + trend)
            trend = beta * (level - prev_level) + (1 - beta) * trend
            smoothed.append(level)
        # Forecast
        preds = list(smoothed)
        for h in range(1, horizon + 1):
            preds.append(level + h * trend)
        preds = np.array(preds)
        # R²
        ss_res = np.sum((vals - np.array(smoothed)) ** 2)
        ss_tot = np.sum((vals - np.mean(vals)) ** 2)
        r2 = max(0.0, 1 - ss_res / ss_tot) if ss_tot > 0 else 0.0
        std = float(np.std(vals - np.array(smoothed))) if n > 2 else abs(np.mean(vals)) * 0.1
        ci_half = 1.96 * std * (1 + 0.01 * horizon)   # widen CI for longer horizons
        return preds, r2, ci_half

    @staticmethod
    def _moving_average(vals, horizon: int, window: int = 7):
        import numpy as np
        n = len(vals)
        w = min(window, n)
        smoothed = np.convolve(vals, np.ones(w) / w, mode="valid")
        last_ma = float(smoothed[-1])
        preds = np.concatenate([vals[:len(smoothed)], np.full(n - len(smoothed) + horizon, last_ma)])
        # R²: not meaningful for MA; approximate
        r2 = 0.5
        std = float(np.std(vals[-w:])) if len(vals) >= w else abs(np.mean(vals)) * 0.1
        ci_half = 1.96 * std * (1 + 0.02 * horizon)
        return preds, r2, ci_half


# Module-level singleton
_forecast_engine = ForecastEngine()


def run_forecast(
    dates: list[str],
    values: list[float],
    horizon: int = 30,
) -> Optional[ForecastResult]:
    """Public API: run a forecast and return ForecastResult or None."""
    return _forecast_engine.forecast(dates=dates, values=values, horizon=horizon)
