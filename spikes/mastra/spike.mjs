/**
 * Feasibility spike: Mastra (TypeScript) -> LiteLLM proxy -> gemini-2.5-flash.
 *
 * Proves the same three requirements as the Python spikes, from the TS SDK:
 *   1. base_url + master key via the openai-compatible provider
 *   2. x-bench-run-id header on every request -> per-run proxy spans
 *   3. multi-turn conversation with a tool call
 *
 * Success = proxy/spans/run-<SPIKE_RUN_ID>.jsonl written with token usage.
 */
import { createOpenAICompatible } from '@ai-sdk/openai-compatible';
import { Agent } from '@mastra/core/agent';
import { createTool } from '@mastra/core/tools';
import { z } from 'zod';

const RUN_ID = process.env.SPIKE_RUN_ID || 'spike-mastra';
const BASE = (process.env.LITELLM_PROXY_BASE_URL || 'http://127.0.0.1:4000').replace(/\/$/, '');
const KEY = process.env.LITELLM_MASTER_KEY || 'sk-1234';

// (1) + (2): openai-compatible provider at the proxy with the run-id header.
const provider = createOpenAICompatible({
  name: 'litellm',
  baseURL: `${BASE}/v1`,
  apiKey: KEY,
  headers: { 'x-bench-run-id': RUN_ID },
});

const add = createTool({
  id: 'add',
  description: 'Add two integers and return the sum.',
  inputSchema: z.object({ a: z.number(), b: z.number() }),
  outputSchema: z.object({ sum: z.number() }),
  execute: async (inputData) => ({ sum: inputData.a + inputData.b }),
});

const agent = new Agent({
  name: 'Assistant',
  instructions: 'You are a helpful assistant. Use tools when relevant.',
  model: provider('gemini-2.5-flash'),
  tools: { add },
});

// (3a) turn 1 — should trigger the add tool
const r1 = await agent.generate('What is 21 plus 21? Use the add tool.');
console.log('TURN1:', r1.text);

// (3b) turn 2 — multi-turn via an explicit message array
const r2 = await agent.generate([
  { role: 'user', content: 'What is 21 plus 21? Use the add tool.' },
  { role: 'assistant', content: r1.text },
  { role: 'user', content: 'Now add 100 to that result.' },
]);
console.log('TURN2:', r2.text);
console.log('OK mastra spike completed');
