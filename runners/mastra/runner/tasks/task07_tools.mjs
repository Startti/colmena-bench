/**
 * Demo #7 — Mastra many-tools handler (single-turn probe; no lazy loading), the
 * TypeScript sibling of runners/pydantic_ai/runner/tasks/task07_tools.py.
 *
 * Builds N tools from the toolset spec (written by the driver to BENCH_TOOLSET_PATH)
 * and binds them ALL to the agent — Mastra sends every schema, the competitor
 * baseline against Colmena's lazy describe-before-use loading. One agent turn
 * answers the needle question; each tool logs {tool, args} to BENCH_TOOLCALL_LOG
 * (the format the driver's scorer reads) and returns its deterministic answer.
 */
import { readFileSync, appendFileSync } from 'node:fs';
import { Agent } from '@mastra/core/agent';
import { createTool } from '@mastra/core/tools';
import { z } from 'zod';

const SYSTEM = (
  'Call exactly the one tool that answers the request. Pass ONLY the argument '
  + 'values named in the user message, VERBATIM. Every other parameter is OPTIONAL '
  + '— omit it entirely; do NOT invent or fill in values for unnamed parameters, '
  + 'and do NOT treat them as required. Do not validate, reformat, or reject the '
  + 'values. After the tool returns, report the resulting total amount number.'
);

function logToolCall(toolName, callArgs) {
  const path = process.env.BENCH_TOOLCALL_LOG;
  if (!path) return;
  appendFileSync(path, `${JSON.stringify({ tool: toolName, args: callArgs, ts: Date.now() / 1000 })}\n`);
}

// All spec params are strings; required stay required, the rest optional (mirrors
// the Python runner's explicit JSON schema).
function zodSchema(toolSpec) {
  const shape = {};
  for (const p of toolSpec.params) {
    shape[p.name] = p.required ? z.string() : z.string().optional();
  }
  return z.object(shape);
}

function makeTool(toolSpec) {
  return createTool({
    id: toolSpec.name,
    description: toolSpec.description,
    inputSchema: zodSchema(toolSpec),
    outputSchema: z.object({ result: z.string() }),
    execute: async (inputData) => {
      const passed = {};
      for (const [k, v] of Object.entries(inputData || {})) {
        if (v !== undefined && v !== null) passed[k] = v;
      }
      logToolCall(toolSpec.name, passed);
      return { result: toolSpec.answer };
    },
  });
}

export async function run(taskDef, model, args) {
  const zero = { input: 0, output: 0, cached: 0, tool_calls: 0 };
  const spec = JSON.parse(readFileSync(process.env.BENCH_TOOLSET_PATH, 'utf-8'));
  try {
    const tools = {};
    for (const t of spec.tools) tools[t.name] = makeTool(t);
    const agent = new Agent({ name: 'ToolAgent', instructions: SYSTEM, model, tools });
    const res = await agent.generate(spec.question, { modelSettings: { temperature: 0.0 } });
    return { answer: { answer: String((res && res.text) || '') }, usage: zero, extras: { n_tools: spec.n_tools } };
  } catch (e) {
    return { answer: { answer: '' }, usage: zero, extras: { error: String(e && e.message ? e.message : e) } };
  }
}
