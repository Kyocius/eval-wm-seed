#!/usr/bin/env python3
"""Check case coverage and export the ready queue for the Seed evaluator."""
import argparse
from collections import defaultdict
import json

from workflow import (PROMPT_PATH, add_config_argument, artifact_path, engine, load_config,
                      metadata_digest, read_jsonl, write_jsonl)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_config_argument(parser)
    parser.add_argument('--models', nargs='+', help='Restrict to these model directory names')
    args = parser.parse_args()
    config = load_config(args.config)
    prompts = {row['case']: row for row in read_jsonl(artifact_path(config, 'judge_prompts.jsonl'))}
    case_index = engine.discover_metadata(config.root)
    expected = {f'{category}/chaozhuo/{case_id}' for category, case_id in case_index}
    if set(prompts) != expected:
        raise ValueError('Case inventory changed; rebuild judge_prompts.jsonl')
    template = PROMPT_PATH.read_text(encoding='utf-8')
    tasks, inventory = engine.discover(config.root, args.models or config.models)
    rows = []
    ready = defaultdict(set)
    for task in tasks:
        case = task['case']
        prompt = prompts[case]
        meta_sha256 = metadata_digest(task['meta_path'], task['meta'])
        rendered = engine.render_prompt(template, task['meta'])
        if prompt['meta_sha256'] != meta_sha256 or prompt['judge_prompt'] != rendered:
            raise ValueError(f'Prompt or metadata changed for {case}; rebuild judge_prompts.jsonl')
        rows.append(dict(model=task['model'], case=case, run_id='main',
                         video=str(task['video']), meta_sha256=meta_sha256,
                         prompt_sha256=engine.digest(rendered.encode())))
        ready[task['model']].add(case)
    # Generation refusals stay in coverage records because they have no video to sample.
    refusals = defaultdict(set)
    for model in inventory['by_model']:
        model_dir = config.root / 'output/inference' / model
        for path in model_dir.rglob('evaluation.json'):
            parts = path.relative_to(model_dir).parts
            categories = [part for part in parts[:-2] if part in ('environmental_safety', 'personal_safety')]
            if len(categories) != 1:
                continue
            case = f'{categories[0]}/chaozhuo/{path.parent.name}'
            if case not in expected or case in ready[model]:
                continue
            record = json.loads(path.read_text(encoding='utf-8'))
            if record.get('status') == 'model_refused' and record.get('id') == prompts[case]['id']:
                refusals[model].add(case)
    report = {}
    for model, cases in sorted(ready.items()):
        missing = expected - cases - refusals[model]
        report[model] = dict(units_total=len(expected), ready=len(cases),
                             model_refused=len(refusals[model]), missing=len(missing),
                             refused_cases=sorted(refusals[model]), missing_cases=sorted(missing))
    queue = artifact_path(config, 'ready_queue.jsonl')
    write_jsonl(queue, rows)
    engine.atomic_json(artifact_path(config, 'coverage_report.json'),
                       dict(dataset_root=str(config.root), ready=len(rows), by_model=report,
                            empty_directories=inventory['empty_directories']))
    print(f'{len(rows)} videos ready across {len(report)} models at {queue}')


if __name__ == '__main__':
    main()
