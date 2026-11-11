#!/usr/bin/env python3
"""Run the historical Seed 2.1 Pro safety judge over a ready JSONL queue."""
import argparse
import collections
import datetime as dt
import fcntl
import os
from pathlib import Path
import shutil
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from workflow import (PROMPT_PATH, add_config_argument, artifact_path, engine, load_config,
                      metadata_digest, read_jsonl)


def load_tasks(config, queue, template, limit):
    rows = list(read_jsonl(queue))
    if not rows:
        raise ValueError('Ready queue is empty')
    models = sorted({row['model'] for row in rows})
    discovered, _ = engine.discover(config.root, models)
    lookup = {task['key']: task for task in discovered}
    selected = []
    seen = set()
    for row in rows:
        key = f"{row['model']}/{row['case']}"
        task = lookup.get(key)
        if task is None or Path(row['video']).resolve() != task['video'].resolve() or row['run_id'] != 'main':
            raise ValueError(f'Video mapping changed for {key}; rebuild coverage')
        if key in seen:
            raise ValueError(f'Duplicate queue entry: {key}')
        seen.add(key)
        meta_hash = metadata_digest(task['meta_path'], task['meta'])
        prompt_hash = engine.digest(engine.render_prompt(template, task['meta']).encode())
        if row['meta_sha256'] != meta_hash or row['prompt_sha256'] != prompt_hash:
            raise ValueError(f'Prompt or metadata changed for {key}; rebuild prompts and coverage')
        relative = Path('results') / task['video'].parent.relative_to(config.root / 'output/inference')
        task.update(meta_sha256=meta_hash, prompt_sha256=prompt_hash,
                    result_path=artifact_path(config, relative / 'evaluation.json'))
        selected.append(task)
        if limit and len(selected) == limit:
            break
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_config_argument(parser)
    parser.add_argument('--input-jsonl', type=Path, help='Ready queue JSONL, defaults to the configured output directory')
    parser.add_argument('--limit', type=int, help='Process the first N queue rows')
    parser.add_argument('--workers', type=int, help='Override worker count for this run')
    parser.add_argument('--dry-run', action='store_true', help='Validate queue and report scope')
    args = parser.parse_args()
    if (args.limit is not None and args.limit <= 0) or (args.workers is not None and args.workers <= 0):
        parser.error('--limit and --workers must be positive')
    config = load_config(args.config)
    if args.workers is not None:
        config.workers = args.workers
    template = PROMPT_PATH.read_text(encoding='utf-8')
    queue = args.input_jsonl or artifact_path(config, 'ready_queue.jsonl')
    tasks = load_tasks(config, queue, template, args.limit)
    inventory = dict(video_count=len(tasks), by_model=dict(collections.Counter(t['model'] for t in tasks)), excluded={})
    engine.log(f'Validated {len(tasks)} videos across {len(inventory["by_model"])} models')
    if args.dry_run:
        return 0
    if not all(shutil.which(command) for command in ('ffmpeg', 'ffprobe')):
        raise ValueError('ffmpeg and ffprobe are required')
    config.state_dir = artifact_path(config, 'state')
    config.state_dir.mkdir(parents=True, exist_ok=True)
    with (config.state_dir / 'run.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('An evaluation already holds this output directory lock')
        (config.state_dir / 'tmp').mkdir(exist_ok=True)
        run_id = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ_') + uuid.uuid4().hex[:8]
        run_dir = config.state_dir / 'runs' / run_id
        run_dir.mkdir(parents=True)
        engine.atomic_json(run_dir / 'manifest.json', dict(created_at=engine.now(), root=str(config.root),
                           queue=str(queue.resolve()), inventory=inventory,
                           tasks=[dict(model=t['model'], case=t['case'], video=str(t['video']),
                                       result_path=str(t['result_path'])) for t in tasks]))
        shutil.copyfile(PROMPT_PATH, run_dir / 'prompt.used.md')
        return engine.Runner(config, tasks, inventory, template, run_dir).run()


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as error:
        message = str(error)
        key = os.environ.get('ARK_API_KEY')
        if key:
            message = message.replace(key, '[REDACTED]')
        engine.log('FATAL ' + message)
        sys.exit(1)
