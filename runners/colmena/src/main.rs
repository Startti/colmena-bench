//! Colmena runner — Task 1 (hello world) for colmena-bench.
//!
//! See `runner_contract.md` for the CLI contract. This binary handles
//! everything except the framework-specific LLM call, which lives in
//! `engine::run_task_01` so it can be swapped between "shell out to colmena
//! CLI" and "use the colmena library directly" without touching the
//! contract code.

mod engine;
mod output;

use anyhow::{Context, Result};
use chrono::Utc;
use clap::Parser;
use std::path::PathBuf;
use std::time::Instant;

#[derive(Parser, Debug)]
#[command(about = "colmena runner")]
struct Args {
    #[arg(long)]
    task: PathBuf,
    #[arg(long)]
    variant: String,
    #[arg(long = "run-id")]
    run_id: String,
    #[arg(long = "model-alias")]
    model_alias: String,
    #[arg(long = "proxy-base-url")]
    proxy_base_url: String,
    #[arg(long)]
    output: PathBuf,
    #[arg(long = "timeout-seconds", default_value_t = 300)]
    timeout_seconds: u64,
}

fn main() -> Result<()> {
    let t_cold = Instant::now();
    let args = Args::parse();

    let task = output::load_task(&args.task).context("loading task YAML")?;
    let cold_start_ms = t_cold.elapsed().as_millis() as u64;

    let started = Utc::now();
    let result = engine::run_task_01(&task, &args);
    let ended = Utc::now();

    let (answer, usage, error) = match result {
        Ok((a, u)) => (a, u, None),
        Err(e) => (
            serde_json::Value::Null,
            engine::Usage::default(),
            Some(format!("{:#}", e)),
        ),
    };

    let success = output::score_success(&task.success, &answer, error.as_deref());

    output::emit(
        &args,
        &task,
        started,
        ended,
        cold_start_ms,
        &answer,
        &usage,
        &success,
        error.as_deref(),
    )
    .context("writing run output")?;

    Ok(())
}
