"""Ponto de entrada manual; importar este módulo nunca inicia treinamento."""

import argparse
import json

from .training_config import TrainingConfig
from .training_manager import TrainingManager


def main(argv=None):
    parser = argparse.ArgumentParser(description="Treina explicitamente um experimento local Nova Model")
    parser.add_argument("--config", default="training/training_config.json")
    args = parser.parse_args(argv)
    config = TrainingConfig.from_json(args.config)
    result = TrainingManager(config).run()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
