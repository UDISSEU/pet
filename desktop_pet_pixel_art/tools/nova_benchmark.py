"""Compatibility entry point for the former benchmark tool name."""

if __name__ == "__main__":
    import runpy

    runpy.run_module("tools.aurova_benchmark", run_name="__main__")
else:
    from tools.aurova_benchmark import *  # noqa: F401,F403
