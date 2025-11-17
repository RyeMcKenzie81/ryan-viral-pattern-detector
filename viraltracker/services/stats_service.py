"""
StatsService - Statistical calculations for outlier detection and analysis.

Provides pure statistical functions with no side effects.
"""

import statistics
from typing import List, Tuple
import numpy as np
from scipy import stats as scipy_stats


class StatsService:
    """
    Statistical calculations service.

    Provides statistical methods for:
    - Z-score outlier detection
    - Percentile-based outlier detection
    - Trimmed mean and standard deviation
    - Percentile calculations
    """

    @staticmethod
    def calculate_zscore_outliers(
        values: List[float],
        threshold: float = 2.0,
        trim_percent: float = 10.0
    ) -> List[Tuple[int, float]]:
        """
        Calculate Z-score outliers using trimmed mean/std.

        Args:
            values: List of values to analyze
            threshold: Z-score threshold (e.g., 2.0 = 2 SDs above mean)
            trim_percent: Percent to trim from each end (default: 10%)

        Returns:
            List of (index, zscore) tuples for outliers

        Example:
            >>> values = [10, 12, 15, 11, 13, 100, 120]
            >>> outliers = StatsService.calculate_zscore_outliers(values, threshold=2.0)
            >>> # Returns [(5, 2.5), (6, 3.2)] for the high values
        """
        if len(values) < 2:
            return []

        # Convert to numpy array
        scores = np.array(values)

        # Compute trimmed mean
        trim_fraction = trim_percent / 100.0
        trimmed_mean = scipy_stats.trim_mean(scores, trim_fraction)

        # Compute trimmed std
        sorted_scores = np.sort(scores)
        n = len(sorted_scores)
        lower_cut = int(n * trim_fraction)
        upper_cut = n - lower_cut
        trimmed_scores = sorted_scores[lower_cut:upper_cut]
        trimmed_std = np.std(trimmed_scores, ddof=1)

        if trimmed_std == 0:
            return []

        # Compute z-scores
        z_scores = (scores - trimmed_mean) / trimmed_std

        # Find outliers
        outliers = []
        for i, zscore in enumerate(z_scores):
            if zscore >= threshold:
                outliers.append((i, float(zscore)))

        return outliers

    @staticmethod
    def calculate_percentile_outliers(
        values: List[float],
        threshold: float = 5.0
    ) -> List[Tuple[int, float, float]]:
        """
        Calculate percentile-based outliers.

        Args:
            values: List of values to analyze
            threshold: Percentile threshold (e.g., 5.0 for top 5%)

        Returns:
            List of (index, value, percentile) tuples for outliers

        Example:
            >>> values = [10, 12, 15, 11, 13, 100, 120]
            >>> outliers = StatsService.calculate_percentile_outliers(values, threshold=5.0)
            >>> # Returns outliers in top 5%
        """
        if len(values) < 2:
            return []

        # Convert to numpy array
        scores = np.array(values)

        # Compute percentile cutoff
        percentile_cutoff = np.percentile(scores, 100 - threshold)

        # Find outliers
        outliers = []
        for i, value in enumerate(scores):
            if value >= percentile_cutoff:
                # Calculate exact percentile for this value
                percentile = (np.sum(scores <= value) / len(scores)) * 100
                outliers.append((i, float(value), float(percentile)))

        return outliers

    @staticmethod
    def calculate_percentile(value: float, values: List[float]) -> float:
        """
        Calculate percentile rank of a value.

        Args:
            value: Value to rank
            values: List of all values

        Returns:
            Percentile (0-100)

        Example:
            >>> values = [10, 20, 30, 40, 50]
            >>> percentile = StatsService.calculate_percentile(40, values)
            >>> # Returns 80.0 (40 is in the 80th percentile)
        """
        if not values:
            return 0.0

        sorted_values = sorted(values)
        rank = sum(1 for v in sorted_values if v <= value)
        return (rank / len(values)) * 100

    @staticmethod
    def calculate_zscore(value: float, values: List[float], use_trimmed: bool = True, trim_percent: float = 10.0) -> float:
        """
        Calculate z-score for a single value.

        Args:
            value: Value to calculate z-score for
            values: List of all values
            use_trimmed: Whether to use trimmed mean/std (default: True)
            trim_percent: Percent to trim if use_trimmed=True

        Returns:
            Z-score

        Example:
            >>> values = [10, 12, 15, 11, 13, 100]
            >>> zscore = StatsService.calculate_zscore(100, values)
            >>> # Returns high z-score (100 is an outlier)
        """
        if len(values) < 2:
            return 0.0

        scores = np.array(values)

        if use_trimmed:
            # Trimmed mean and std
            trim_fraction = trim_percent / 100.0
            mean = scipy_stats.trim_mean(scores, trim_fraction)

            sorted_scores = np.sort(scores)
            n = len(sorted_scores)
            lower_cut = int(n * trim_fraction)
            upper_cut = n - lower_cut
            trimmed_scores = sorted_scores[lower_cut:upper_cut]
            std = np.std(trimmed_scores, ddof=1)
        else:
            # Regular mean and std
            mean = np.mean(scores)
            std = np.std(scores, ddof=1)

        if std == 0:
            return 0.0

        return float((value - mean) / std)

    @staticmethod
    def calculate_summary_stats(values: List[float]) -> dict:
        """
        Calculate summary statistics for a dataset.

        Args:
            values: List of values

        Returns:
            Dictionary with summary statistics:
            - mean: Arithmetic mean
            - median: Median value
            - std: Standard deviation
            - min: Minimum value
            - max: Maximum value
            - count: Number of values
            - q25: 25th percentile
            - q75: 75th percentile

        Example:
            >>> values = [10, 20, 30, 40, 50]
            >>> stats = StatsService.calculate_summary_stats(values)
            >>> print(stats['mean'])  # 30.0
        """
        if not values:
            return {
                "mean": 0.0,
                "median": 0.0,
                "std": 0.0,
                "min": 0.0,
                "max": 0.0,
                "count": 0,
                "q25": 0.0,
                "q75": 0.0
            }

        scores = np.array(values)

        return {
            "mean": float(np.mean(scores)),
            "median": float(np.median(scores)),
            "std": float(np.std(scores, ddof=1) if len(scores) > 1 else 0.0),
            "min": float(np.min(scores)),
            "max": float(np.max(scores)),
            "count": len(scores),
            "q25": float(np.percentile(scores, 25)),
            "q75": float(np.percentile(scores, 75))
        }
