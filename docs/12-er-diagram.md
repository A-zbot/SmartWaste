# 12 · Entity-Relationship Diagram

```mermaid
erDiagram
    USERS ||--o{ REPORTS : owns
    USERS ||--o{ NOTIFICATIONS : receives
    USERS ||--o{ FEEDBACK : writes
    USERS ||--o{ COMPLAINT_IMAGES : uploads
    REPORTS ||--|| COMPLAINT_IMAGES : has_submission_image
    REPORTS ||--o{ COMPLAINT_IMAGES : has_resolution_images
    REPORTS ||--o{ COMPLAINT_HISTORY : accumulates
    REPORTS ||--o| PREDICTIONS : receives
    REPORTS ||--o| FEEDBACK : receives
    REPORTS ||--o{ NOTIFICATIONS : triggers
    REPORTS }o--|| COMPLAINT_CLUSTERS : member_of

    USERS {
        int id PK
        text name
        text email UK
        text password_hash
        text role "citizen or admin"
        int is_active
        timestamp created_at
        timestamp updated_at
    }

    REPORTS {
        int id PK
        text tracking_id UK
        text name "reporter display name"
        text mobile
        text location
        text area
        text waste_type "citizen category"
        text priority "citizen priority"
        text description
        text image "submission photo filename"
        text status "Submitted to Rejected"
        real latitude
        real longitude
        text ai_category "Module B output"
        text ai_urgency
        real ai_confidence
        int ai_needs_review
        text admin_remarks
        timestamp created_at
        timestamp updated_at
        timestamp resolved_at
        int user_id FK "nullable - anonymous reports"
        text source "live, seed or synthetic"
    }

    COMPLAINT_IMAGES {
        int id PK
        int report_id FK
        text filename
        text kind "submission or resolution"
        text caption
        int uploaded_by FK
        timestamp created_at
    }

    COMPLAINT_HISTORY {
        int id PK
        int report_id FK
        text old_status
        text new_status
        text remark
        text actor_type "system, admin or citizen"
        int actor_id
        text actor_label
        timestamp created_at
    }

    PREDICTIONS {
        int id PK
        int report_id FK
        text model_name
        text model_version
        text predicted_category
        text predicted_urgency
        real confidence
        int needs_review
        text explanation "JSON - Module F"
        timestamp created_at
    }

    COMPLAINT_CLUSTERS {
        int id PK
        text label "H1, H2, ..."
        real centroid_lat
        real centroid_lng
        int complaint_count
        int unresolved_count
        text top_category
        text report_ids "JSON array"
        text params "JSON - eps, quality, ..."
        timestamp computed_at
    }

    NOTIFICATIONS {
        int id PK
        int user_id FK
        int report_id FK
        text title
        text message
        text link
        int is_read
        timestamp created_at
    }

    FEEDBACK {
        int id PK
        int report_id FK "UNIQUE - one per report"
        int user_id FK
        int rating "1 to 5 CHECK"
        text comment
        timestamp created_at
    }

    MESSAGES {
        int id PK
        text name
        text email
        text subject
        text message
        timestamp created_at
    }

    AUDIT_LOGS {
        int id PK
        text actor_type "system, admin or citizen"
        int actor_id
        text actor_label
        text action
        text entity
        text entity_id
        text detail
        text ip
        timestamp created_at
    }
```

## 12.1 Relationship Notes

* **USERS → REPORTS** is *optional* (`ON DELETE SET NULL`): anonymous
  complaints are allowed and remain viewable through their tracking link.
* **REPORTS → PREDICTIONS** is 0..1 in practice (latest prediction is
  read with `ORDER BY id DESC LIMIT 1`); history keeps older rows.
* **REPORTS → FEEDBACK** is one-to-one (`UNIQUE(report_id)`), enforced by
  the schema.
* **COMPLAINT_CLUSTERS** is a *snapshot table*, not a normal parent of
  reports: `report_ids` is a JSON array of member IDs from the most recent
  run (the whole table is replaced on re-clustering).
* **AUDIT_LOGS** and **MESSAGES** are standalone (weak) entities; audit rows
  reference entities textually (`entity`, `entity_id`) so they survive
  deletion of the referenced row.
