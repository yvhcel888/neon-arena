"""Built-in NEON ARENA bots.

Exports are lazy so ``python -m bots.<module>`` does not pre-import the module
being executed and trigger runpy warnings.
"""

from importlib import import_module

__all__ = ["HeuristicPolicy", "LlmPolicy", "RandomPolicy"]

_MODULES = {
    "HeuristicPolicy": ".heuristic",
    "LlmPolicy": ".llm_agent",
    "RandomPolicy": ".random_bot",
}


def __getattr__(name):
    if name not in _MODULES:
        raise AttributeError(name)
    value = getattr(import_module(_MODULES[name], __name__), name)
    globals()[name] = value
    return value
