# 02 · Introduction

## 2.1 Background

Urban local bodies across India and the world handle thousands of sanitation
complaints every week — overflowing bins, construction debris on roads,
dumped medical waste, clogged drains. These complaints arrive through phone
hotlines, mobile apps and social media as unstructured text, are triaged
manually, and are rarely analysed in aggregate. The consequence is that the
municipality learns *what happened* but never *what is happening repeatedly,
where it concentrates, or what will happen next week*.

## 2.2 Motivation

Three information gaps motivate this project:

1. **Classification gap** — complaints are free text; no machine assigns a
   standard waste category or an urgency level, so routing to the correct
   department depends on the individual reading the ticket.
2. **Duplication gap** — the same overflowing bin is reported by several
   residents within minutes; each report is treated as new work, inflating
   perceived backlog and distorting statistics.
3. **Prediction gap** — authorities deploy sweeper teams and vehicles
   reactively. Without volume forecasts and hotspot maps, deployment is
   guesswork.

## 2.3 From SmartWaste 1.x to SmartWaste 2.0

SmartWaste 1.x was a reporting-and-tracking system: citizens submitted
complaints, administrators changed their status, and the data was stored.
SmartWaste 2.0 keeps that workflow and adds an intelligence layer:

| Capability | 1.x | 2.0 |
|---|---|---|
| Complaint submission & tracking | yes | yes |
| AI category / urgency prediction | no | yes (Module B) |
| Duplicate complaint detection | no | yes (Module C) |
| Geospatial hotspot clustering | no | yes (Module D) |
| Volume forecasting | no | yes (Module E) |
| Prediction explanations | no | yes (Module F) |
| Decision-support recommendations | no | yes (Module G) |
| Model evaluation harness | no | yes (`experiments/`) |
| PDF / CSV export, audit trail | partial | yes |

## 2.4 Methodology Overview

The project follows a classic software-engineering lifecycle — requirements,
design (architecture, DFDs, ER model), implementation, testing, evaluation
and deployment — with an added **experimental** track in which every
intelligent behaviour is measured offline against a labelled corpus before it
is trusted in the live path. Both tracks share the same code: the offline
evaluation imports the exact scoring functions the web application uses, so
reported numbers describe the production behaviour.

## 2.5 Document Map

This documentation set contains 24 sections covering the abstract,
introduction, problem statement, objectives, scope, literature survey,
feasibility, requirements, architecture, modules, data-flow and entity-
relationship design, database design, algorithms, machine-learning pipeline,
technology stack, implementation, interface design, testing, results,
security, deployment, conclusion and future scope with references.
