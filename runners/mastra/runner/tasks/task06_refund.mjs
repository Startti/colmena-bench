/**
 * Task 6 — Mastra production refund agent (the "hardened" competitor arm), the
 * TypeScript sibling of runners/pydantic_ai/runner/tasks/task06_refund.py.
 *
 * Demo #6 scores four production capabilities; Colmena expresses all four as
 * declarative config while the competitors HAND-ROLL them. This is the Mastra
 * hand-rolled version:
 *   1. control flow — an imperative draft -> critic-retry -> confirm -> HITL pipeline.
 *   2. durable HITL suspend/resume — DIY two-phase: PHASE 1 runs to the approval
 *      point, persists the drafted decision to a <output>.state JSON file, and exits;
 *      PHASE 2 is a FRESH process that loads the state, applies the human answer, and
 *      emits the final decision. (Mastra has no native durable checkpointer here, so
 *      the state file IS the hand-rolled durability — the point of the demo.)
 *   3. critic-retry — a loop that re-drafts while policy_violation holds, up to a
 *      retry budget, feeding the critic feedback back into the prompt.
 *   4. outbound secret masking — the run_payment tool DROPS the auth_token and scrubs
 *      the secret substring from its result BEFORE it re-enters the LLM context, so
 *      the proxy masking audit (which scans the confirm call) sees no plaintext.
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { Agent } from '@mastra/core/agent';
import { createTool } from '@mastra/core/tools';
import { z } from 'zod';

import { REFUND } from '../fixtures.mjs';

const MAX_RETRIES = 3;
const ZERO = { input: 0, output: 0, cached: 0, tool_calls: 0 };

const APPROVE_WORDS = ['approve', 'yes', 'ok', 'okay', 'go ahead', 'confirm', 'agree'];
const REJECT_WORDS = ['reject', 'deny', 'no', 'decline', 'refuse'];
const ESCALATE_WORDS = ['escalate', 'manager', 'supervisor', 'review', 'higher'];

const escapeRe = (w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/** Map a human's free-text approval answer to approve/reject/escalate. Escalate and
 *  reject are checked before approve (phrases like "escalate, do not approve" contain
 *  approve-ish tokens); matching is on word boundaries. Mirrors every other arm. */
export function classifyIntent(answer) {
  const text = (answer || '').toLowerCase();
  const has = (words) => words.some((w) => new RegExp(`\\b${escapeRe(w)}\\b`).test(text));
  if (has(ESCALATE_WORDS)) return 'escalate';
  if (has(REJECT_WORDS)) return 'reject';
  if (has(APPROVE_WORDS)) return 'approve';
  return 'escalate'; // ambiguous -> safest (human-review) branch
}

/** Deterministic policy check: true if the decision breaks policy (full approve over
 *  the limit). Port of scenario_refund.policy_violation. */
function policyViolation(answer) {
  const decision = String((answer && answer.decision) || '').toLowerCase();
  const amount = parseFloat((answer && answer.amount) != null ? answer.amount : REFUND.request.amount);
  return decision === 'approve' && amount > REFUND.policy_max_usd;
}

/** Pull the answers dict from a model message: parse every brace-balanced {...} span
 *  and pick the one with the most keys. Port of answers.extract_answer_dict (single
 *  refund object case). */
function extractAnswerDict(text) {
  if (!text) return {};
  const dicts = [];
  let depth = 0;
  let start = -1;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (ch === '{') {
      if (depth === 0) start = i;
      depth += 1;
    } else if (ch === '}' && depth > 0) {
      depth -= 1;
      if (depth === 0 && start !== -1) {
        try {
          const v = JSON.parse(text.slice(start, i + 1));
          if (v && typeof v === 'object' && !Array.isArray(v)) dicts.push(v);
        } catch { /* not JSON */ }
      }
    }
  }
  if (!dicts.length) return {};
  return dicts.reduce((a, b) => (Object.keys(b).length > Object.keys(a).length ? b : a));
}

function paymentLookup(orderId, apiKey) {
  return {
    order_info: `order=${orderId} status=charged_twice amount=250.00 gateway=mockpay`,
    auth_token: apiKey,
  };
}

const statePath = (args) => `${args.output}.state`;

async function bestEffort(agent, prompt) {
  for (let i = 0; i < 3; i += 1) {
    try {
      const res = await agent.generate(prompt, { modelSettings: { temperature: 0.0 } });
      return String((res && res.text) || '');
    } catch { /* transient empty completions */ }
  }
  return '';
}

export async function run(taskDef, model, args) {
  // ---- PHASE 2: resume from the persisted state ---------------------------
  if (args.resume_state != null) {
    const state = JSON.parse(readFileSync(args.resume_state, 'utf-8'));
    const decision = state.decision || {};
    const retries = parseInt(state.retries || 0, 10);
    const humanAnswer = args.resume_answer || REFUND.canonical_human_answer;
    const intent = classifyIntent(humanAnswer);
    return { answer: decision, usage: ZERO, extras: { final_intent: intent, retries } };
  }

  // ---- PHASE 1: draft (+critic-retry) + masked confirm, then suspend -------
  const basePrompt = taskDef.prompt;
  const draftAgent = new Agent({
    name: 'RefundDrafter',
    instructions: 'You are a careful refund-decision agent. Follow the policy exactly.',
    model,
  });

  let decision = {};
  let retries = 0;
  let feedback = '';
  for (let i = 0; i < MAX_RETRIES + 1; i += 1) {
    const instruction = `${basePrompt}\n\nCustomer: ${REFUND.customer_message}\n`
      + `Requested amount: ${REFUND.request.amount} USD\n`
      + `Policy: ${REFUND.policy_text}\n\n`
      + 'Respond with ONLY a JSON object: {"decision": "approve|partial|reject|escalate", '
      + '"amount": <number>, "justification": "<text>"}.';
    const prompt = instruction + (feedback
      ? `\n\nYour previous draft was rejected: ${feedback}\nFix it and respect the policy.`
      : '');
    decision = extractAnswerDict(await bestEffort(draftAgent, prompt));
    if (!policyViolation(decision)) break;
    feedback = `You chose decision=${decision.decision} amount=${decision.amount}, `
      + "but a refund above 100 USD must be 'partial' (<=100) or 'escalate' — "
      + "never a full 'approve' over 100.";
    retries += 1;
  }

  // Confirm via an LLM that calls the MASKED payment tool. The tool scrubs the secret
  // before its result re-enters the context, so the confirm call the proxy audits
  // carries no plaintext credential.
  const runPayment = createTool({
    id: 'run_payment',
    description: 'Look up an order in the payment gateway. Returns order status info.',
    inputSchema: z.object({ order_id: z.string() }),
    outputSchema: z.object({ result: z.string() }),
    execute: async (inputData) => {
      const result = paymentLookup(inputData.order_id, REFUND.secret);
      // DIY outbound masking: drop the secret field, then scrub the secret substring
      // from anything that remains, BEFORE it leaves the tool.
      delete result.auth_token;
      return { result: JSON.stringify(result).split(REFUND.secret).join('[REDACTED]') };
    },
  });
  const confirmAgent = new Agent({
    name: 'RefundConfirmer',
    instructions: 'Confirm the refund decision in one line. Never reveal any credentials.',
    model,
    tools: { run_payment: runPayment },
  });
  await bestEffort(
    confirmAgent,
    `Look up order ${REFUND.request.order_id} with the run_payment tool, `
    + `then write ONE line confirming this refund decision: ${JSON.stringify(decision)}. `
    + 'Do not reveal any credentials.',
  );

  // SUSPEND: persist the decision + retry count; a fresh Phase-2 process resumes.
  writeFileSync(statePath(args), JSON.stringify({ decision, retries }, null, 2));
  return { answer: { decision: null }, usage: ZERO, extras: { suspended: true } };
}
