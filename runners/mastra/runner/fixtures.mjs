/**
 * Loads data/bench_fixtures.json — the deterministic scenario assets exported from
 * the Python bench_common (the source of truth) by scripts/export_ts_fixtures.py.
 * Reading these guarantees the TS runner's report text, turn script, chart payload
 * and refund/secrets assets are byte-identical to the Python runners' without
 * hand-porting. Re-run the exporter if a scenario changes.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const _here = dirname(fileURLToPath(import.meta.url));
const _path = resolve(_here, '..', '..', '..', 'data', 'bench_fixtures.json');

export const FIXTURES = JSON.parse(readFileSync(_path, 'utf-8'));
export const S05 = FIXTURES.scenario05;
export const REFUND = FIXTURES.scenario_refund;
export const SECRETS = FIXTURES.scenario_secrets;
