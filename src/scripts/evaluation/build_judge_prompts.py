#!/usr/bin/env python3
"""Build a JSONL manifest of physical safety prompts from the authored criteria."""
import argparse

from workflow import PROMPT_PATH, add_config_argument, artifact_path, engine, load_config, prompt_rows, write_jsonl


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_config_argument(parser)
    args = parser.parse_args()
    config = load_config(args.config)
    template = PROMPT_PATH.read_text(encoding='utf-8')
    rows = list(prompt_rows(config, template))
    manifest = artifact_path(config, 'judge_prompts.jsonl')
    write_jsonl(manifest, rows)
    engine.atomic_json(artifact_path(config, 'build_report.json'), {
        'dataset_root': str(config.root),
        'prompt_version': engine.VERSION,
        'prompt_template_sha256': engine.digest(template.encode()),
        'cases': len(rows),
    })
    print(f'Built {len(rows)} prompts at {manifest}')


if __name__ == '__main__':
    main()
