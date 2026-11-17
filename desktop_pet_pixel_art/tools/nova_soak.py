"""Compatibility entry point for the former soak tool name."""

if __name__ == "__main__":
    import runpy

    runpy.run_module("tools.aurova_soak", run_name="__main__")
else:
    from tools.aurova_soak import *  # noqa: F401,F403
