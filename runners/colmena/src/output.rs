//! Loading task YAMLs + emitting run_output.json conforming to the schema.
//!
//! Anything framework-specific belongs in engine.rs. This file is identical
//! in spirit to runners/<python>/runner/common.py — keep them in sync.

use anyhow::{Context, Result};
use chrono::{DateTime, Utc};
use regex::Regex;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::fs;
use std::path::Path;
use sysinfo::{CpuRefreshKind, MemoryRefreshKind, RefreshKind, System};

use crate::engine::Usage;
use crate::Args;

#[derive(Debug, Deserialize)]
pub struct Task {
    pub id: String,
    pub prompt: String,
    pub success: SuccessSpec,
    #[serde(default)]
    pub model_alias: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct SuccessSpec {
    pub kind: String,
    #[serde(default)]
    pub pattern: Option<String>,
    #[serde(default)]
    pub target: Option<f64>,
    #[serde(default)]
    pub tolerance: Option<f64>,
}

pub fn load_task(path: &Path) -> Result<Task> {
    let text = fs::read_to_string(path)
        .with_context(|| format!("reading {}", path.display()))?;
    let task: Task = serde_yaml::from_str(&text).context("parsing task YAML")?;
    Ok(task)
}

#[derive(Serialize)]
pub struct Success {
    pub ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub reason: Option<String>,
}

pub fn score_success(spec: &SuccessSpec, answer: &Value, error: Option<&str>) -> Success {
    if let Some(e) = error {
        return Success {
            ok: false,
            reason: Some(e.to_string()),
        };
    }
    match spec.kind.as_str() {
        "regex" => {
            let pat = spec.pattern.as_deref().unwrap_or("");
            let text = match answer {
                Value::String(s) => s.clone(),
                other => other.to_string(),
            };
            let ok = Regex::new(pat).map(|r| r.is_match(&text)).unwrap_or(false);
            Success { ok, reason: None }
        }
        "exact_numeric" => {
            let target = spec.target.unwrap_or(0.0);
            let tol = spec.tolerance.unwrap_or(0.0);
            let parsed = match answer {
                Value::Number(n) => n.as_f64(),
                Value::String(s) => s.trim().parse::<f64>().ok(),
                _ => None,
            };
            match parsed {
                Some(v) => Success {
                    ok: (v - target).abs() <= tol,
                    reason: None,
                },
                None => Success {
                    ok: false,
                    reason: Some("answer not numeric".into()),
                },
            }
        }
        other => Success {
            ok: false,
            reason: Some(format!("success kind {other:?} not implemented in T1 scaffold")),
        },
    }
}

fn host_info() -> Value {
    let mut sys = System::new_with_specifics(
        RefreshKind::new()
            .with_cpu(CpuRefreshKind::everything())
            .with_memory(MemoryRefreshKind::everything()),
    );
    sys.refresh_all();
    let hostname = System::host_name().unwrap_or_else(|| "unknown".into());
    let os = format!(
        "{} {}",
        System::name().unwrap_or_else(|| "?".into()),
        System::os_version().unwrap_or_else(|| "?".into())
    );
    let cpu_model = sys
        .cpus()
        .first()
        .map(|c| c.brand().to_string())
        .unwrap_or_else(|| "unknown".into());
    let ram_gb = (sys.total_memory() as f64) / (1024.0 * 1024.0 * 1024.0);
    json!({
        "hostname": hostname,
        "os": os,
        "cpu_model": cpu_model,
        "ram_gb": (ram_gb * 100.0).round() / 100.0,
    })
}

fn framework_version() -> &'static str {
    // Bumped manually when METHODOLOGY.md §1 changes.
    env!("CARGO_PKG_VERSION")
}

#[allow(clippy::too_many_arguments)]
pub fn emit(
    args: &Args,
    _task: &Task,
    started: DateTime<Utc>,
    ended: DateTime<Utc>,
    cold_start_ms: u64,
    answer: &Value,
    usage: &Usage,
    success: &Success,
    error: Option<&str>,
) -> Result<()> {
    let task_id = {
        // Re-read the id from disk so we don't carry the whole Task struct
        // through emit signature.
        let text = fs::read_to_string(&args.task)?;
        let task: Task = serde_yaml::from_str(&text)?;
        task.id
    };
    let latency_ms = (ended - started).num_milliseconds().max(0);
    let payload = json!({
        "run_id": args.run_id,
        "task_id": task_id,
        "variant": args.variant,
        "framework": "colmena",
        "framework_version": framework_version(),
        "model_alias": args.model_alias,
        "started_at": started.to_rfc3339_opts(chrono::SecondsFormat::Millis, true),
        "ended_at": ended.to_rfc3339_opts(chrono::SecondsFormat::Millis, true),
        "latency_ms": latency_ms,
        "cold_start_ms": cold_start_ms,
        "ttft_ms": Value::Null,
        "tokens": {
            "input": usage.input,
            "output": usage.output,
            "cached": usage.cached,
        },
        "tool_calls": usage.tool_calls,
        "ram_peak_mb": ram_peak_mb(),
        "success": success,
        "answer": answer,
        "error": error,
        "host": host_info(),
        "extras": {},
    });

    if let Some(parent) = args.output.parent() {
        fs::create_dir_all(parent).ok();
    }
    fs::write(&args.output, serde_json::to_string_pretty(&payload)?)?;
    Ok(())
}

fn ram_peak_mb() -> f64 {
    let mut sys = System::new();
    sys.refresh_processes();
    let pid = sysinfo::get_current_pid().ok();
    let bytes = pid
        .and_then(|p| sys.process(p).map(|proc| proc.memory()))
        .unwrap_or(0);
    (bytes as f64) / (1024.0 * 1024.0)
}
