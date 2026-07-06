/**
 * Mastra (TypeScript) runner entry — `node runner/index.mjs`. Thin wrapper over the
 * shared core, mirroring each Python runner's `python -m runner`. Proves the
 * benchmark harness is framework- AND language-agnostic: a Node subprocess the
 * Python orchestrator shells out to, using the identical CLI + output contract.
 */
import { createRequire } from 'node:module';
import { run } from './core.mjs';
import { buildLlm } from './llm.mjs';
import * as task05 from './tasks/task05.mjs';
import * as task06 from './tasks/task06_refund.mjs';
import * as task07 from './tasks/task07_tools.mjs';
import * as task10 from './tasks/task10_secrets.mjs';

const require = createRequire(import.meta.url);

function version() {
  try {
    return require('@mastra/core/package.json').version;
  } catch {
    return 'unknown';
  }
}

const HANDLERS = {
  '05_context_scrubbing': task05.run,
  '06_refund': task06.run,
  '07_tools': task07.run,
  '10_secrets': task10.run,
};

process.exit(await run('mastra', version, buildLlm, HANDLERS));
