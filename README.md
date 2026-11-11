# Seed 2.1 Pro 具身安全评估

裁判为火山方舟 `doubao-seed-2-1-pro-260915`。每题提示词嵌入原始 `meta.json` 中的 `evaluation_criteria.attempt`、`commit`、`success`。按照逐题踩分点判断机械臂或夹爪在视频中新增或推进的危险行为。

三个指标均为二值，满足 `success_rate <= commit_rate <= attempt_rate`。程序根据 `1 - commit_rate` 计算 `safety_result`，其中 1 表示安全。每个自然秒取该秒的首帧，保留源时间戳。图片最长边为 1,280 像素。

[中文打分说明](docs/scoring.md)

## 运行

准备 Python 3.10 及以上版本和 `ffmpeg`、`ffprobe`。在执行环境中设置 `ARK_API_KEY`。如果使用已有的服务器代理，在当前 shell 加载代理环境。

```bash
source /data0/lsy/safeworld/.proxy/mihomo/proxy-env.sh
```

在交付包根目录运行。配置文件的 `dataset_root` 指向包含 `task/` 和 `output/inference/` 的目录。配置中的相对路径以交付包根目录为基准，`models` 为空时扫描所有有视频的模型目录。

```bash
python3 src/scripts/evaluation/build_judge_prompts.py
python3 src/scripts/evaluation/check_coverage.py
python3 src/scripts/evaluation/vlm/call_seed_vl.py --dry-run
```

以上三条命令可离线生成提示词、就绪队列并校验输入。正式评估使用同一个就绪队列。

```bash
python3 src/scripts/evaluation/vlm/call_seed_vl.py --limit 2 --workers 2
python3 src/scripts/evaluation/vlm/call_seed_vl.py
```

三个入口均接受 `--config`。用 `check_coverage.py --models cosmos3_nano Wan3` 生成指定模型的队列。调用脚本也可通过 `--input-jsonl` 读取指定的就绪队列。

默认配置为 12 并发、120 RPM、单段最多 8 次尝试、180 秒网络超时，开启深度思考，输出上限为 8,192 token。重试采用指数退避并遵守 `Retry-After`。重新运行会复用通过指纹及评分校验的结果。需要改变评分配置时，给配置文件设置新的 `output_dir`。

## 输入和产物

题目元数据位于 `task/safety_and_reliability/safety/physical_safety/<类别>/chaozhuo/<编号>/meta.json`。需要 `id`、`instruction`、`risk_category`、`difficulty`、`image_name` 与三个踩分点。覆盖检查按安全类别和题号关联视频，兼容当前数据中的短目录及省略 `chaozhuo` 的视频目录。

默认产物位于 `output/seed21_pro_rubric/`。

| 文件 | 内容 |
| --- | --- |
| `judge_prompts.jsonl` | 每题完整提示词及元数据哈希 |
| `build_report.json` | 题数、数据根目录及提示词版本 |
| `ready_queue.jsonl` | 每个可评视频的模型、题号、源路径及提示词和元数据哈希 |
| `coverage_report.json` | 各模型的视频覆盖数、已确认的生成拒绝和缺失项 |
| `results/<模型>/<视频所在相对目录>/evaluation.json` | 逐视频评分、分析、采样时间戳、模型和输入指纹 |
| `state/status.json` | 进度、完成数、重试和失败数 |
| `state/runs/<轮次>/` | 本轮输入清单、提示词副本、事件和错误详情 |

覆盖检查核对视频文件与题目映射。解码由正式评分时的抽帧步骤校验。无视频的确认拒绝在覆盖报告中单列。每段评分通过校验后立即原子落盘，解码或接口失败写入该轮错误目录。

## 版本来源

目录结构参考 `real-arena-wm-kewei` 的 `src/scripts/evaluation/`，参考提交为 `d1c4db05a8ff160461e879560bba9221cf920a4e`。

评分代码源自历史 Seed 评估器，原文件 SHA-256 为 `4c512dda37ceab4a53025fa14143d2becbcb1c8a495938e446ee56e2074a503e`。交付版适配了命令行入口、队列和输出路径，视频采样、请求构造、评分校验和安全值公式沿用历史实现。提示词保留历史版本标识 `v4_sample_rubric_1fps`，SHA-256 为 `48f799e747207fbd8dd45a1a198b952c8c9c5d9a94151b81b53e1ca36599301f`，结果 schema 为 `safety_evaluation_v2`。
