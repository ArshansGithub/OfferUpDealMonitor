import asyncio

def exponential_backoff(attempt: int, base: float = 0.5, factor: float = 2.0, max_delay: float = 60.0) -> float:
    """
    Calculate exponential backoff delay.

    :param attempt: Current retry attempt.
    :param base: Base delay in seconds.
    :param factor: Multiplication factor.
    :param max_delay: Maximum delay in seconds.
    :return: Delay in seconds.
    """
    delay = base * (factor ** attempt) # Base times factor to the power of attempt
    return min(delay, max_delay) # Return the minimum of delay and max_delay
