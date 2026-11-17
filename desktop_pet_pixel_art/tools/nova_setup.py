"""Compatibility entry point for the former setup tool name."""

if __name__ == "__main__":
    import runpy

    runpy.run_module("tools.aurova_setup", run_name="__main__")
else:
    from tools.aurova_setup import *  # noqa: F401,F403
