# 11 · Data-Flow Diagrams

## 11.1 Level 0 — Context Diagram

```mermaid
flowchart LR
    CTZ[Citizen] -->|1. submit complaint<br/>2. track status| SW((SmartWaste 2.0))
    ADM[Administrator] -->|3. triage / resolve<br/>4. view maps & forecasts| SW
    SW -->|tracking ID, status timeline,<br/>duplicate hints| CTZ
    SW -->|queue, AI explanations,<br/>hotspots, recommendations| ADM
    SW -->|best-effort notification| MAIL[(SMTP)]
    MAIL -->|new report / status change| CTZ
    MAIL -->|new report copy| MUNI[(Municipal inbox)]
    SW --> DB[(SQLite)]
    SW --> ML[(models/)]
```

## 11.2 Level 1 — Core Processes

```mermaid
flowchart TB
    CTZ[Citizen] --> P1

    subgraph P1["P1 · Manage complaints"]
        P1A[Validate input] --> P1B[Store image] --> P1C[Assign tracking ID]
        P1C --> P1D[Write history + notify]
    end

    CTZ -.->|text for duplicate check| P2
    P1 --> P2

    subgraph P2["P2 · AI intake enrichment"]
        P2A[Preprocess text] --> P2B[Category + urgency model]
        P2A --> P2C[Cosine vs recent complaints]
        P2B --> P2D[Build explanation]
        P2C --> P2E[Duplicate evidence]
    end

    P1 --> DB[(SQLite)]
    P2 --> DB
    P2 --> ML[(model artifacts)]

    ADM[Administrator] --> P3
    subgraph P3["P3 · Triage & decision support"]
        P3A[Filter queue] --> P3B[Update status + remark]
        P3B --> P3C[Audit log]
        P3A --> P3D[Recommendations]
        P3A --> P3E[CSV / PDF export]
    end
    P3 --> DB

    ADM --> P4
    subgraph P4["P4 · Geospatial analysis"]
        P4A[Read geocoded complaints] --> P4B[DBSCAN + silhouette]
        P4B --> P4C[Persist cluster snapshot]
    end
    P4 --> DB

    ADM --> P5
    subgraph P5["P5 · Forecasting"]
        P5A[Daily series] --> P5B[Chronological split]
        P5B --> P5C[Naive / MA / RF evaluation]
        P5C --> P5D[Metrics + uncertainty band]
    end
    P5 --> DB

    P2 -.->|same code path| EV[experiments/evaluation.py]
    EV --> REPORTS[(models/*_report.json<br/>experiments/RESULTS.md)]
```

## 11.3 Data-Flow Narrative

1. **Submit flow (P1 → P2 → storage):** validated form data passes through
   preprocessing, model inference and duplicate scanning; the complaint row,
   its history event, its prediction (with explanation) and any duplicate
   evidence are written together, then notifications are dispatched
   best-effort.
2. **Triage flow (P3):** the administrator filters the stored rows, updates
   status with a remark (audited), and exports CSV/PDF from the same store.
3. **Analysis flows (P4, P5):** read-only over stored complaints; both
   persist their outputs (cluster snapshot; forecast payload) for dashboards.
4. **Evaluation flow:** the offline harness reuses the Module C scoring
   functions and the Module D/E logic against labelled corpora, emitting the
   JSON/Markdown reports quoted in this documentation.
