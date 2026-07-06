/**
 * Task 10 — Mastra secrets handler (Demo #10): the NAIVE competitor arm, the
 * TypeScript sibling of runners/pydantic_ai/runner/tasks/task10_secrets.py.
 *
 * Mastra has no native outbound secret masking, so the idiomatic collect-mid-
 * conversation pattern puts the credentials straight into the LLM transcript. This
 * handler does the simplest idiomatic thing: run the onboarding agent with the
 * pasted credentials in the prompt — so the proxy's leak audit (which scans every
 * LLM request's messages for the secret marker) flags the leak. It then POSTs the
 * REAL secret values to the mock connect endpoint, and makes a final call that
 * includes the mock's echoed response, so in the echo variant the echoed secret
 * also passes through the LLM.
 *
 * Contrast with Colmena (runners/colmena/runner/tasks/task10_secrets.py), whose
 * secure_suspend never lets the secret reach the LLM/proxy.
 */
import { Agent } from '@mastra/core/agent';

import { SECRETS } from '../fixtures.mjs';

const SECRET_KEYS = ['api_key', 'api_secret', 'webhook_signing_secret'];

// The leak fires on the REQUEST (the proxy audits request messages); a transient
// empty/malformed completion must NOT sink the cell. Retry a few times, then
// tolerate failure by returning ''.
async function askBestEffort(agent, prompt) {
  for (let i = 0; i < 3; i += 1) {
    try {
      const res = await agent.generate(prompt, { modelSettings: { temperature: 0.0 } });
      return String((res && res.text) || '');
    } catch {
      /* transient empty completions */
    }
  }
  return '';
}

export async function run(taskDef, model, args) {
  const s = SECRETS.secrets; // {api_key, api_secret, webhook_signing_secret} -> real fake values
  const creds = `api_key=${s.api_key}, api_secret=${s.api_secret}, `
    + `webhook_signing_secret=${s.webhook_signing_secret}`;

  // (1) idiomatic collection: the user pastes the credentials into the chat -> they
  //     enter the LLM context -> the proxy audit flags the leak.
  const onboard = new Agent({ name: 'Onboarder', instructions: SECRETS.onboarding_prompt, model });
  await askBestEffort(onboard, `Here are my credentials: ${creds}`); // -> LEAK

  // (2) connect: POST the 3 REAL values to the mock.
  const url = process.env.BENCH_MOCK_URL;
  const body = JSON.stringify(Object.fromEntries(SECRET_KEYS.map((k) => [k, s[k]])));
  const httpRes = await fetch(url, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body,
  });
  const resp = await httpRes.text();

  // (3) final call including the mock response (echo variant: response contains the
  //     secret -> it passes through the LLM here too).
  const summ = new Agent({
    name: 'Summarizer',
    instructions: 'Summarize the connection result in one line.',
    model,
  });
  await askBestEffort(summ, `The connect endpoint returned: ${resp}`);

  return {
    answer: 'connected',
    usage: { input: 0, output: 0, cached: 0, tool_calls: 0 },
    extras: { arm: 'naive', received_path: process.env.BENCH_MOCK_RECORD || null },
  };
}
