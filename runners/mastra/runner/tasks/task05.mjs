/**
 * Task 5 — Mastra context-tax demo (the "context scrubbing" competitor arm), the
 * TypeScript sibling of runners/pydantic_ai/runner/tasks/task05.py.
 *
 * Replays the fixed 10-turn conversation with Mastra's idiomatic multi-turn
 * pattern: each turn calls agent.generate(messages, ...) with the FULL running
 * transcript, and the assistant + tool messages returned are appended back for the
 * next turn. That is the framework's default memory — the whole history, including
 * the ~32 KB base64 chart tool-return, is re-sent every turn and never trimmed.
 * This is the competitor baseline that Colmena's binary scrubber eliminates.
 *
 * Seeding: the report is planted as a pre-turn-0 user/assistant exchange (no LLM
 * call), matching how the other runners seed a static report + acknowledgement.
 *
 * Chart payload transport workaround: LiteLLM's Gemini translator auto-promotes any
 * tool/message text starting with "data:image/" into a Gemini image part (rejected
 * for a synthetic PNG). We prefix the payload with "[chart_data_uri]: " so it does
 * NOT start with "data:" — the full ~32 KB is still present as text, so the
 * context-tax growth is faithfully measured. (Every other runner does this.)
 *
 * Token accounting is via proxy spans bucketed by extras.turn_boundaries; the
 * returned usage is all zeros by contract.
 */
import { Agent } from '@mastra/core/agent';
import { createTool } from '@mastra/core/tools';
import { z } from 'zod';

import { S05 } from '../fixtures.mjs';

const nowIso = () => new Date().toISOString();

export async function run(taskDef, model, args) {
  const chartTool = createTool({
    id: S05.chart_tool_name, // "generate_chart"
    description: S05.chart_tool_description,
    inputSchema: z.object({ description: z.string() }),
    outputSchema: z.object({ chart: z.string() }),
    // Fixed payload regardless of input; prefixed so it does not start with data:.
    execute: async () => ({ chart: `[chart_data_uri]: ${S05.chart_data_uri}` }),
  });

  const agent = new Agent({
    name: 'ReportAnalyst',
    instructions: S05.system_message,
    model,
    tools: { [S05.chart_tool_name]: chartTool },
  });

  // Seed the report as a pre-turn-0 exchange (no LLM call), mirroring the other
  // runners' static system + report + acknowledgement seed.
  const messages = [
    { role: 'user', content: `Here is the report for this conversation:\n\n${S05.report_text}` },
    { role: 'assistant', content: 'Understood. I have the report and will answer your questions.' },
  ];

  const answers = [];
  const turnBoundaries = [nowIso()]; // boundary BEFORE turn 0

  for (let i = 0; i < S05.turns.length; i += 1) {
    const turn = S05.turns[i];
    messages.push({ role: 'user', content: turn.message });
    try {
      const res = await agent.generate(messages, { modelSettings: { temperature: 0.0 } });
      const text = String((res && res.text) || '');
      answers.push(text);
      // Append the full assistant/tool step messages so the ~32 KB chart return
      // stays in the re-sent transcript for every later turn (the context tax).
      const resp = res && res.response ? await res.response : null;
      const stepMsgs = (resp && resp.messages) || null;
      if (Array.isArray(stepMsgs) && stepMsgs.length) {
        for (const m of stepMsgs) messages.push(m);
      } else {
        messages.push({ role: 'assistant', content: text });
      }
    } catch (e) {
      answers.push(`[ERROR turn ${i}: ${e && e.message ? e.message : e}]`);
      messages.push({ role: 'assistant', content: '' });
    } finally {
      turnBoundaries.push(nowIso()); // boundary AFTER this turn
    }
  }

  return {
    answer: answers,
    usage: { input: 0, output: 0, cached: 0, tool_calls: 0 },
    extras: {
      turn_boundaries: turnBoundaries,
      turn_types: S05.turns.map((t) => t.type),
    },
  };
}
