/**
 * Mastra LLM factory — an OpenAI-compatible provider pointed at the LiteLLM proxy.
 *
 * Mirrors every other runner: we drive Mastra through the proxy's OpenAI-compatible
 * /v1 route (not a native Google client) so token usage is captured at the proxy,
 * and we set the x-bench-run-id header on every request so the proxy routes this
 * run's spans to proxy/spans/run-<run_id>.jsonl. Returns a bound model handle that
 * each task wraps in its own Agent (parallel to how the LangChain runner returns a
 * ChatOpenAI and tasks bind their own tools).
 */
import { createOpenAICompatible } from '@ai-sdk/openai-compatible';

export function buildLlm(args) {
  const base = args.proxy_base_url.replace(/\/$/, '');
  const provider = createOpenAICompatible({
    name: 'litellm',
    baseURL: `${base}/v1`,
    apiKey: process.env.LITELLM_PROXY_API_KEY || 'sk-bench-runner-do-not-use-in-prod',
    headers: { 'x-bench-run-id': args.run_id },
  });
  return provider(args.model_alias);
}
