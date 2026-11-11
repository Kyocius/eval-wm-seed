"""Configuration and JSONL helpers for the physical safety evaluation."""
import argparse
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

from vlm import seed21_engine as engine

EVALUATION_DIR = Path(__file__).resolve().parent
PACKAGE_ROOT = EVALUATION_DIR.parents[2]
DEFAULT_CONFIG = PACKAGE_ROOT / 'configs/seed21_pro_rubric.json'
PROMPT_PATH = EVALUATION_DIR / 'prompts/seed21_pro_rubric/common.md'


def add_config_argument(parser):
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG, help='Evaluation configuration JSON')


def load_config(path):
    data = json.loads(path.read_text(encoding='utf-8'))
    root = (PACKAGE_ROOT / data['dataset_root']).resolve()
    output = (PACKAGE_ROOT / data['output_dir']).resolve()
    protected = [root / 'task', root / 'output/inference']
    for directory in protected:
        directory = directory.resolve()
        if output == directory or directory in output.parents or output in directory.parents:
            raise ValueError('Set output_dir outside the source task and inference trees')
    judge, sampling, execution = data['judge'], data['sampling'], data['execution']
    if judge['model'] != engine.MODEL or sampling['video_fps'] != 1:
        raise ValueError('This release uses Seed 2.1 Pro and 1 FPS')
    if judge['thinking'] not in ('enabled', 'disabled'):
        raise ValueError('Invalid thinking setting')
    models = data['models']
    if not isinstance(models, list) or any(not isinstance(model, str) or not model for model in models):
        raise ValueError('models must be an array of model directory names')
    values = dict(max_tokens=judge['max_tokens'], timeout=judge['timeout'],
                  max_side=sampling['image_max_side'], **execution)
    for name in ('workers', 'retries', 'max_tokens', 'max_side'):
        if type(values[name]) is not int or values[name] <= 0:
            raise ValueError(f'{name} must be a positive integer')
    for name in ('rpm', 'timeout', 'progress_interval'):
        if type(values[name]) not in (int, float) or not 0 < values[name] < float('inf'):
            raise ValueError(f'{name} must be positive and finite')
    return SimpleNamespace(root=root, output_dir=output, models=models,
                           judge_model=engine.MODEL, api_url=engine.API_URL,
                           thinking=judge['thinking'], **values)


def artifact_path(config, relative):
    path = (config.output_dir / relative).resolve()
    if config.output_dir not in path.parents:
        raise ValueError(f'Output path escapes configured output_dir: {path}')
    return path


def read_jsonl(path):
    with path.open(encoding='utf-8') as stream:
        for number, line in enumerate(stream, 1):
            if line.strip():
                try:
                    yield json.loads(line)
                except ValueError as error:
                    raise ValueError(f'{path}:{number}: invalid JSON') from error


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                     prefix='.' + path.name, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False) + '\n')
            stream.close()
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def metadata_digest(path, expected):
    raw = path.read_bytes()
    if json.loads(raw) != expected:
        raise ValueError(f'Metadata changed while preparing the queue: {path}')
    return engine.digest(raw)


def prompt_rows(config, template):
    for (category, case_id), (path, meta) in engine.discover_metadata(config.root).items():
        case = f'{category}/chaozhuo/{case_id}'
        prompt = engine.render_prompt(template, meta)
        yield dict(case=case, run_id='main', id=meta['id'], meta=str(path),
                   meta_sha256=metadata_digest(path, meta), prompt_sha256=engine.digest(prompt.encode()),
                   judge_prompt=prompt)
