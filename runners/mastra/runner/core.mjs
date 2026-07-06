/**
 * Framework-agnostic runner core for the TypeScript (Mastra) runner — the Node
 * counterpart of runners/_bench_common/bench_common/core.py.
 *
 * It parses the identical CLI contract, times the handler, samples peak RSS, and
 * emits the SAME output JSON schema so the Python orchestrator can consume a
 * Mastra run exactly like any Python runner's. Each task handler has the shape
 *   async (taskDef, model, args) -> { answer, usage, extras }
 * where usage is { input, output, cached, tool_calls } (all zero by contract —
 * token accounting is done at the proxy from the run-id spans).
 */
import { readFileSync, mkdirSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import os from 'node:os';
import { parse as parseYaml } from 'yaml';

export const MODEL_ALIASES = ['gemini-2.5-flash', 'claude-haiku', 'gpt-4o-mini'];

export function parseArgs(argv) {
  const args = {
    task: null, variant: null, run_id: null, model_alias: null,
    proxy_base_url: null, output: null, timeout_seconds: 300,
    resume_state: null, resume_answer: null,
  };
  const map = {
    '--task': 'task', '--variant': 'variant', '--run-id': 'run_id',
    '--model-alias': 'model_alias', '--proxy-base-url': 'proxy_base_url',
    '--output': 'output', '--timeout-seconds': 'timeout_seconds',
    '--resume-state': 'resume_state', '--resume-answer': 'resume_answer',
  };
  for (let i = 0; i < argv.length; i += 1) {
    const key = map[argv[i]];
    if (key === undefined) throw new Error(`unknown arg ${argv[i]}`);
    let val = argv[i + 1];
    i += 1;
    if (key === 'timeout_seconds') val = parseInt(val, 10);
    args[key] = val;
  }
  for (const req of ['task', 'variant', 'run_id', 'model_alias', 'proxy_base_url', 'output']) {
    if (args[req] == null) throw new Error(`missing required --${req.replace('_', '-')}`);
  }
  if (!MODEL_ALIASES.includes(args.model_alias)) {
    throw new Error(`--model-alias must be one of ${MODEL_ALIASES.join(', ')}`);
  }
  return args;
}

export function loadTask(path) {
  return parseYaml(readFileSync(path, 'utf-8'));
}

export function hostInfo() {
  return {
    hostname: os.hostname(),
    os: `${os.type()} ${os.release()}`,
    cpu_model: (os.cpus()[0] && os.cpus()[0].model) || os.arch(),
    ram_gb: Math.round((os.totalmem() / 1024 ** 3) * 100) / 100,
  };
}

/** Port of bench_common.score_success — regex / exact_numeric; other kinds are
 *  scored by the dedicated drivers (same "not implemented" fallback as Python). */
export function scoreSuccess(spec, answer) {
  const kind = spec && spec.kind;
  if (kind === 'regex') {
    const text = typeof answer === 'string' ? answer : JSON.stringify(answer);
    return { ok: new RegExp(spec.pattern).test(text) };
  }
  if (kind === 'exact_numeric') {
    const val = parseFloat(String(answer).trim());
    if (Number.isNaN(val)) return { ok: false, reason: 'not numeric' };
    const target = spec.target !== undefined ? parseFloat(spec.target) : null;
    const tol = parseFloat(spec.tolerance || 0);
    return { ok: target !== null && Math.abs(val - target) <= tol };
  }
  return { ok: false, reason: `success kind ${JSON.stringify(kind)} not scored by the runner` };
}

function isoZ(d) {
  // toISOString() already yields e.g. 2026-07-05T12:34:56.789Z (UTC, ms precision).
  return d.toISOString();
}

/** Generic main: parse args, dispatch by task.id, time it, emit output JSON. */
export async function run(frameworkName, frameworkVersionFn, llmFactory, handlers) {
  const t0Cold = process.hrtime.bigint();
  const args = parseArgs(process.argv.slice(2));
  const task = loadTask(args.task);
  const taskId = task.id;
  if (!(taskId in handlers)) {
    process.stderr.write(`${frameworkName} runner has no handler for task ${JSON.stringify(taskId)}\n`);
    return 1;
  }
  const coldStartMs = Number(process.hrtime.bigint() - t0Cold) / 1e6;

  const model = llmFactory(args);

  // Sample RSS during the handler for a TRUE peak (not an end snapshot), like the
  // Python core's sampler thread.
  let peakRss = process.memoryUsage().rss;
  const sampler = setInterval(() => {
    peakRss = Math.max(peakRss, process.memoryUsage().rss);
  }, 50);
  const cpu0 = process.cpuUsage();

  const started = new Date();
  let answer = null;
  let usage = { input: 0, output: 0, cached: 0, tool_calls: 0 };
  let extras = {};
  let error = null;
  try {
    const result = await handlers[taskId](task, model, args);
    answer = result.answer;
    usage = result.usage || usage;
    extras = result.extras || {};
  } catch (e) {
    error = `${e && e.constructor ? e.constructor.name : 'Error'}: ${e && e.message ? e.message : e}`;
  }
  const ended = new Date();
  clearInterval(sampler);
  peakRss = Math.max(peakRss, process.memoryUsage().rss);
  const cpu = process.cpuUsage(cpu0);

  const success = error === null
    ? scoreSuccess(task.success || {}, answer)
    : { ok: false, reason: error };

  const payload = {
    run_id: args.run_id,
    task_id: task.id,
    variant: args.variant,
    framework: frameworkName,
    framework_version: frameworkVersionFn(),
    model_alias: args.model_alias,
    started_at: isoZ(started),
    ended_at: isoZ(ended),
    latency_ms: Math.round(ended.getTime() - started.getTime()),
    cold_start_ms: Math.round(coldStartMs),
    ttft_ms: null, // filled by the orchestrator from proxy spans
    tokens: {
      input: Math.trunc(usage.input || 0),
      output: Math.trunc(usage.output || 0),
      cached: Math.trunc(usage.cached || 0),
    },
    tool_calls: Math.trunc(usage.tool_calls || 0),
    ram_peak_mb: Math.round((peakRss / 1024 ** 2) * 100) / 100,
    cpu_user_s: Math.round((cpu.user / 1e6) * 1000) / 1000,
    cpu_sys_s: Math.round((cpu.system / 1e6) * 1000) / 1000,
    success,
    answer,
    error,
    host: hostInfo(),
    extras: extras || {},
  };
  mkdirSync(dirname(args.output), { recursive: true });
  writeFileSync(args.output, JSON.stringify(payload, null, 2));
  return 0;
}
