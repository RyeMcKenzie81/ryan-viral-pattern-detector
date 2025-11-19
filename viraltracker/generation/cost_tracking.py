"""
Cost Tracking for Gemini API Usage

Tracks token usage and calculates costs for comment generation.
Provides transparency into API spending and budget monitoring.

V1.2 Feature 4.1: Cost Tracking
"""

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Gemini Flash pricing (as of 2024)
# Source: https://ai.google.dev/pricing
GEMINI_FLASH_INPUT_COST_PER_1M = 0.075  # $0.075 per 1M input tokens
GEMINI_FLASH_OUTPUT_COST_PER_1M = 0.30   # $0.30 per 1M output tokens


@dataclass
class TokenUsage:
    """
    Token usage from Gemini API response.

    Attributes:
        prompt_tokens: Number of tokens in the input prompt
        completion_tokens: Number of tokens in the generated output
        total_tokens: Total tokens (prompt + completion)
    """
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass
class APICost:
    """
    API cost calculation with breakdown.

    Attributes:
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        input_cost_usd: Cost of input tokens in USD
        output_cost_usd: Cost of output tokens in USD
        total_cost_usd: Total cost in USD
    """
    input_tokens: int
    output_tokens: int
    input_cost_usd: float
    output_cost_usd: float
    total_cost_usd: float

    def __str__(self) -> str:
        """Human-readable cost breakdown"""
        return (
            f"${self.total_cost_usd:.6f} "
            f"({self.input_tokens} in + {self.output_tokens} out)"
        )


def extract_token_usage(response) -> Optional[TokenUsage]:
    """
    Extract token usage from Gemini API response.

    Args:
        response: Gemini API GenerateContentResponse object

    Returns:
        TokenUsage object or None if not available

    Example:
        >>> response = model.generate_content(prompt)
        >>> usage = extract_token_usage(response)
        >>> if usage:
        ...     print(f"Used {usage.total_tokens} tokens")
    """
    try:
        # Access usage_metadata from response
        usage = response.usage_metadata

        return TokenUsage(
            prompt_tokens=usage.prompt_token_count,
            completion_tokens=usage.candidates_token_count,
            total_tokens=usage.total_token_count
        )
    except (AttributeError, TypeError, KeyError) as e:
        logger.warning(f"Failed to extract token usage from API response: {e}")
        return None


def calculate_cost(token_usage: TokenUsage) -> APICost:
    """
    Calculate API cost from token usage.

    Uses Gemini Flash pricing:
    - Input: $0.075 per 1M tokens
    - Output: $0.30 per 1M tokens

    Args:
        token_usage: Token counts from Gemini API

    Returns:
        APICost object with breakdown

    Example:
        >>> usage = TokenUsage(prompt_tokens=500, completion_tokens=150, total_tokens=650)
        >>> cost = calculate_cost(usage)
        >>> print(f"Total cost: ${cost.total_cost_usd:.6f}")
        Total cost: $0.000083
    """
    # Calculate costs (divide by 1 million to get cost per token)
    input_cost = (token_usage.prompt_tokens / 1_000_000) * GEMINI_FLASH_INPUT_COST_PER_1M
    output_cost = (token_usage.completion_tokens / 1_000_000) * GEMINI_FLASH_OUTPUT_COST_PER_1M

    return APICost(
        input_tokens=token_usage.prompt_tokens,
        output_tokens=token_usage.completion_tokens,
        input_cost_usd=input_cost,
        output_cost_usd=output_cost,
        total_cost_usd=input_cost + output_cost
    )


def extract_and_calculate_cost(response) -> Optional[APICost]:
    """
    Convenience function to extract token usage and calculate cost in one step.

    Args:
        response: Gemini API GenerateContentResponse object

    Returns:
        APICost object or None if token usage not available

    Example:
        >>> response = model.generate_content(prompt)
        >>> cost = extract_and_calculate_cost(response)
        >>> if cost:
        ...     print(f"API call cost: {cost}")
    """
    token_usage = extract_token_usage(response)
    if token_usage:
        return calculate_cost(token_usage)
    return None


def format_cost_summary(total_cost_usd: float, num_tweets: int) -> str:
    """
    Format cost summary for CLI output.

    Args:
        total_cost_usd: Total cost in USD
        num_tweets: Number of tweets processed

    Returns:
        Formatted cost summary string

    Example:
        >>> summary = format_cost_summary(0.0341, 426)
        >>> print(summary)
        💰 API Cost: $0.0341 USD (avg $0.00008 per tweet)
    """
    avg_cost = total_cost_usd / num_tweets if num_tweets > 0 else 0

    # Format with appropriate precision
    if total_cost_usd < 0.01:
        total_str = f"${total_cost_usd:.6f}"
    elif total_cost_usd < 1.0:
        total_str = f"${total_cost_usd:.4f}"
    else:
        total_str = f"${total_cost_usd:.2f}"

    avg_str = f"${avg_cost:.5f}" if avg_cost < 0.01 else f"${avg_cost:.4f}"

    return f"💰 API Cost: {total_str} USD (avg {avg_str} per tweet)"


# For backward compatibility and easy imports
__all__ = [
    'TokenUsage',
    'APICost',
    'extract_token_usage',
    'calculate_cost',
    'extract_and_calculate_cost',
    'format_cost_summary',
    'GEMINI_FLASH_INPUT_COST_PER_1M',
    'GEMINI_FLASH_OUTPUT_COST_PER_1M'
]
