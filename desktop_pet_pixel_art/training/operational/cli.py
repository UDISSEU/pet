import argparse, json
from pathlib import Path
from .benchmark import run
from .dispatcher_benchmark import run_dispatcher_benchmark
from .storage import StorageManager

def main():
    parser=argparse.ArgumentParser(description="Benchmark operacional e controle de armazenamento")
    parser.add_argument("command",choices=("benchmark","dispatcher","storage"))
    parser.add_argument("--path",default=str(Path(__file__).parent/"data"/"benchmark.jsonl"))
    args=parser.parse_args()
    if args.command == "benchmark":
        result = run(args.path)
    elif args.command == "dispatcher":
        result = run_dispatcher_benchmark(args.path)
    else:
        result = StorageManager(Path(__file__).parent.parent).record()
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=="__main__": main()
