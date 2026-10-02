"""Explicit local operations. Approval has no digest or confirmation argument."""
import argparse
import json
from pathlib import Path


def main():
    from . import fixture, job, tracker, training
    parser = argparse.ArgumentParser(description="D-148 local analytic ML research")
    parser.add_argument("--workspace", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("materialize", "freeze-recipes", "init-tracker", "approve", "run", "deliver", "status"):
        commands.add_parser(name)
    for name in ("train", "record-training"):
        sub = commands.add_parser(name)
        sub.add_argument("--role", required=True, choices=("candidate", "baseline"))
    sub = commands.add_parser("prepare")
    sub.add_argument("--candidate-run-id", required=True)
    sub.add_argument("--baseline-run-id", required=True)
    args = parser.parse_args()
    root = args.workspace
    if args.command == "materialize":
        result = fixture.materialize(root)
    elif args.command == "freeze-recipes":
        result = training.freeze_recipes(root)
    elif args.command == "train":
        result = training.train(root, args.role)
    elif args.command == "init-tracker":
        result = tracker.initialize(root)
    elif args.command == "record-training":
        result = tracker.training_record(root, args.role)
    elif args.command == "prepare":
        result = job.prepare(root, args.candidate_run_id, args.baseline_run_id)
    elif args.command == "approve":
        result = job.approve(root)
    elif args.command == "run":
        result = job.run(root)
    elif args.command == "deliver":
        result = tracker.deliver(root)
    else:
        result = job.current(root)
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
