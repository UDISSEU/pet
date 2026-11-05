"""Ferramentas explícitas para preparar e treinar o Nova Model localmente."""

__all__ = ["DatasetBuilder", "TrainingConfig", "TrainingManager"]


def __getattr__(name):
    if name == "DatasetBuilder":
        from .dataset_builder import DatasetBuilder
        return DatasetBuilder
    if name == "TrainingConfig":
        from .training_config import TrainingConfig
        return TrainingConfig
    if name == "TrainingManager":
        from .training_manager import TrainingManager
        return TrainingManager
    raise AttributeError(name)
