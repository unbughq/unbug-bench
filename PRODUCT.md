# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Static HTML/CSS, one self-contained file per report (founder, 2026-10-15). Works offline, prints to PDF, easy to send.

## Users

The founder of Unbug and the investors they share results with privately. They read the report to decide whether Unbug's core claim holds and what to build next. Internal + investor audience; not a public release until sealed-exam results exist.

## Product Purpose

unbug-bench is the grader-side exam that tests Unbug, an AI on-call owner of one business promise ("never sell more stock than exists") in a real shop (Medusa 2.19.0). It compares Unbug against strong baselines on safety, honest claims, and human minutes, and publishes the results the way AI labs publish benchmarks. Success: results a skeptical reader trusts, whether or not they favor Unbug.

## Positioning

A benchmark built by the product's own team that reports against itself when the data says so. Sealed cases written by other model families, a judge the Unbug builders never see, outcome-based grading under heavy concurrent traffic, and charged human minutes as a first-class metric.

## Operating Context

Contestants run inside Harbor 0.24 multi-step tasks on boat.dev VMs. Each step lands a change; a separate verifier rebuilds a fresh shop and replays heavy traffic (10–30 runs). Contestants: A (plain Claude Code), B (A + fast-check and Stryker), C (Unbug), C0 (one-shot Unbug), and GPT 6.1 Sol via Codex. Practice uses the public case; the scored exam uses 5 sealed cases from a case factory.

## Capabilities and Constraints

- Hypothesis H1: Unbug is at most 5 points less safe than B and needs at least 30% fewer human minutes.
- Human-minute charges: question 5, escalation 15, each unknown/unprotected/unclaimed path 10, observed oversell 60.
- Sealed-case content, answer keys and judge internals must never appear in any report.
- Undecided: pass thresholds and outside review are not locked.

## Evidence on Hand

- Practice round 1 (2026-10-15, one try each, 30 judge runs/step): results in ~/unbug-practice-jobs/.
- Practice round 2 (redesigned step 4, 10 judge runs/step): ~/unbug-practice-jobs/round2/.
- No sealed-exam results exist yet. No external review yet. Never fabricate either.

## Product Principles

1. Report every number, including the ones that hurt Unbug.
2. Name the grader's own mistakes and how they were fixed.
3. Separate pilot evidence from scored evidence, always.
4. Name things in plain words; no internal IDs without a gloss.
