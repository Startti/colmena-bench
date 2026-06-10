//! Framework-specific work for the Colmena runner.
//!
//! We currently shell out to the `colmena` CLI (binary built from
//! `Startti/colmena` `develop`). This keeps the runner crate from depending
//! on Colmena's evolving public-API surface while we're in the
//! buildout phase. Once the library API is locked we can replace
//! `colmena_cli_run` with a direct `colmena::Agent::new(...).run(...)` call
//! and uncomment the `colmena = { git = ... }` dependency in Cargo.toml.
//!
//! What the wrapper expects from the `colmena` CLI:
//!
//!     colmena run-task \
//!         --task <task-dag.json> \
//!         --prompt-stdin \
//!         --model <gemini-2.5-flash|claude-haiku|gpt-4o-mini> \
//!         --proxy-base-url <url> \
//!         --proxy-api-key <bearer>
//!
//! Reads the prompt from stdin. Emits exactly one JSON object on stdout
//! with shape:
//!
//!     {"answer": "...", "usage": {"input": N, "output": N, "cached": N, "tool_calls": N}}
//!
//! Anything else on stdout fails the run (per runner_contract.md). Logs go to
//! stderr.
//!
//! If the `colmena` binary doesn't yet match this shape, update this file
//! (not the contract).

use anyhow::{anyhow, Context, Result};
use serde::Deserialize;
use serde_json::Value;
use std::io::Write;
use std::path::PathBuf;
use std::process::{Command, Stdio};

use crate::output::Task;
use crate::Args;

#[derive(Default, Debug, Clone, Copy)]
pub struct Usage {
    pub input: u64,
    pub output: u64,
    pub cached: u64,
    pub tool_calls: u64,
}

#[derive(Debug, Deserialize)]
struct CliOut {
    answer: Value,
    #[serde(default)]
    usage: Option<CliUsage>,
}

#[derive(Debug, Default, Deserialize)]
struct CliUsage {
    #[serde(default)]
    input: u64,
    #[serde(default)]
    output: u64,
    #[serde(default)]
    cached: u64,
    #[serde(default)]
    tool_calls: u64,
}

pub fn run_task_01(task: &Task, args: &Args) -> Result<(Value, Usage)> {
    let dag_path = task_dag_for_id(&task.id, args)?;
    let api_key = std::env::var("LITELLM_PROXY_API_KEY")
        .unwrap_or_else(|_| "sk-bench-runner-do-not-use-in-prod".to_string());

    let mut child = Command::new("colmena")
        .args([
            "run-task",
            "--task",
            dag_path.to_str().context("dag path not utf-8")?,
            "--prompt-stdin",
            "--model",
            &args.model_alias,
            "--proxy-base-url",
            &args.proxy_base_url,
            "--proxy-api-key",
            &api_key,
        ])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .context("spawning `colmena` — ensure it is on PATH (see runners/colmena/README.md)")?;

    {
        let stdin = child.stdin.as_mut().context("no stdin on colmena child")?;
        stdin.write_all(task.prompt.as_bytes())?;
    }

    let out = child.wait_with_output().context("waiting on colmena child")?;
    if !out.status.success() {
        return Err(anyhow!(
            "colmena CLI exit {}: {}",
            out.status,
            String::from_utf8_lossy(&out.stderr)
        ));
    }
    let stdout = String::from_utf8(out.stdout).context("colmena stdout not utf-8")?;
    let parsed: CliOut = serde_json::from_str(stdout.trim()).with_context(|| {
        format!("colmena stdout was not the expected JSON object: {stdout:?}")
    })?;
    let usage = parsed.usage.unwrap_or_default();
    Ok((
        parsed.answer,
        Usage {
            input: usage.input,
            output: usage.output,
            cached: usage.cached,
            tool_calls: usage.tool_calls,
        },
    ))
}

fn task_dag_for_id(task_id: &str, args: &Args) -> Result<PathBuf> {
    let suffix = PathBuf::from("runners/colmena/tasks").join(format!("{task_id}.json"));
    let mut tried: Vec<PathBuf> = Vec::new();

    // Walk up from the task YAML looking for the repo root (a directory
    // that has `runners/colmena/tasks/<id>.json`).
    let mut cur = args.task.parent().map(|p| p.to_path_buf());
    while let Some(dir) = cur {
        let candidate = dir.join(&suffix);
        if candidate.exists() {
            return Ok(candidate);
        }
        tried.push(candidate);
        cur = dir.parent().map(|p| p.to_path_buf());
    }
    // Then current working directory.
    let cwd_candidate = PathBuf::from(".").join(&suffix);
    if cwd_candidate.exists() {
        return Ok(cwd_candidate);
    }
    tried.push(cwd_candidate);

    Err(anyhow!(
        "no Colmena DAG found for task {task_id}; tried: {}",
        tried.iter().map(|p| p.display().to_string()).collect::<Vec<_>>().join(", ")
    ))
}
